import os
import sys
import time
import random
import asyncio
import statistics
from datetime import datetime
from typing import Dict, List, Any

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

import anyio
try:
    import httpx
except ImportError:
    import httpx2 as httpx

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, defer

import backend.app.database as db_mod
from backend.seed.seed_data import seed_database
from backend.services.sla_engine import evaluate_travel_sla
from backend.services.routing_engine import calculate_queue_score_tier2
from backend.app.models import Ticket
import backend.app.main as app_main

def percentile(data: List[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    d = k - f
    return s[f] + d * (s[c] - s[f])

# Original B3 query function saved
orig_evaluate_triage = app_main._evaluate_and_paginate_triage_query

def unoptimized_evaluate_triage(query, db, role: str, limit: int, offset: int, now: datetime) -> Dict[str, Any]:
    # Full ORM hydration (B3 reverted behavior)
    all_candidates = query.options(defer(Ticket.description)).all()
    scored_tickets = []
    for t in all_candidates:
        sla = evaluate_travel_sla(
            status=t.status, check_in_date=t.check_in_date, lcd_date=t.lcd_date,
            priority=t.priority, intent=t.intent, now=now
        )
        queue_score = calculate_queue_score_tier2(
            priority=t.priority, check_in_date=t.check_in_date, lcd_date=t.lcd_date,
            intent=t.intent, now=now
        )
        scored_tickets.append((queue_score, sla, t))
    scored_tickets.sort(key=lambda x: (x[0], -x[2].created_at.timestamp() if x[2].created_at else 0), reverse=True)
    paginated_slice = scored_tickets[offset : offset + limit]
    results = []
    for queue_score, sla, t in paginated_slice:
        results.append({
            "id": t.id, "tboh_id": t.tboh_id, "agency_id": t.agency_id, "title": t.title,
            "intent": t.intent, "priority": t.priority, "status": t.status,
            "check_in_date": t.check_in_date.isoformat(),
            "lcd_date": t.lcd_date.isoformat() if t.lcd_date else None,
            "assigned_to": t.assigned_to if role != "Requester" else None,
            "routing_reason": t.routing_reason if role != "Requester" else None,
            "sla": sla, "queue_score": queue_score if role != "Requester" else None,
            "created_at": t.created_at.isoformat()
        })
    return {"total": len(all_candidates), "tickets": results}

async def run_benchmark_iteration(client, clients: int, duration_sec: int, ticket_ids: List[str]) -> Dict[str, Any]:
    latencies_all = []
    latencies_2xx = []
    statuses = {}
    stop_event = asyncio.Event()
    start_time = time.time()
    end_time = start_time + duration_sec
    total_reqs = 0

    app_main.RATE_LIMIT_PER_MINUTE = 1000000

    async def worker(worker_id: int):
        nonlocal total_reqs
        user_id = f"USR-{101 + (worker_id % 4)}"
        lead_headers = {"X-User-ID": user_id, "X-Role": "Lead", "X-Agency-ID": "AGY-001"}
        while not stop_event.is_set():
            roll = random.random()
            t0 = time.perf_counter()
            st = 599
            try:
                if roll < 0.70:
                    r = await client.get("/api/tickets?view=triage&limit=25", headers=lead_headers)
                elif roll < 0.90:
                    tid = random.choice(ticket_ids) if ticket_ids else "TCK-1001"
                    r = await client.get(f"/api/tickets/{tid}", headers=lead_headers)
                elif roll < 0.95:
                    r = await client.post("/api/tickets", headers=lead_headers, json={
                        "title": f"Tkt-{worker_id}", "description": "Benchmark load ticket",
                        "tboh_id": f"TBOH-SWEEP-{worker_id}-{time.time()}"[-30:],
                        "check_in_date": "2026-12-01T10:00:00Z", "priority": "Medium",
                        "agency_id": "AGY-001", "intent": "Refund Request"
                    })
                else:
                    tid = random.choice(ticket_ids) if ticket_ids else "TCK-1001"
                    r = await client.post(f"/api/tickets/{tid}/assign", headers=lead_headers, json={"agent_id": "USR-101"})
                st = r.status_code
            except Exception:
                st = 599
            elapsed = (time.perf_counter() - t0) * 1000.0
            latencies_all.append(elapsed)
            if 200 <= st < 300:
                latencies_2xx.append(elapsed)
            statuses[st] = statuses.get(st, 0) + 1
            total_reqs += 1

    tasks = [asyncio.create_task(worker(i)) for i in range(clients)]
    await asyncio.sleep(duration_sec)
    stop_event.set()
    await asyncio.gather(*tasks, return_exceptions=True)

    actual_duration = time.time() - start_time
    count_2xx = len(latencies_2xx)
    goodput = count_2xx / actual_duration if actual_duration > 0 else 0.0
    return {
        "duration": actual_duration,
        "total_requests": total_reqs,
        "count_2xx": count_2xx,
        "goodput": goodput,
        "statuses": statuses,
        "latencies_all": latencies_all,
        "latencies_2xx": latencies_2xx,
        "p50_2xx": percentile(latencies_2xx, 50) if latencies_2xx else 0.0,
        "p95_2xx": percentile(latencies_2xx, 95) if latencies_2xx else 0.0,
        "p50_all": percentile(latencies_all, 50) if latencies_all else 0.0
    }

async def benchmark_config(config_name: str, config_fn, levels: List[int], variants: List[str], duration: int = 10, repeats: int = 2) -> List[str]:
    lines = []
    lines.append(f"\n==================================================================================================")
    lines.append(f"CONFIG: {config_name}")
    lines.append(f"Levels: {levels}, Duration: {duration}s, Repeats: {repeats}")
    lines.append(f"==================================================================================================")

    for var in variants:
        lines.append(f"\n### Variant ({var}): {'~456 normal seed' if var == 'a' else '5000 triage-heavy'} ---")
        lines.append(f"{'Clients':<8} | {'Total':<7} | {'2xx':<7} | {'Goodput (2xx/s)':<18} | {'Shed 503%':<10} | {'Err 599%':<9} | {'2xx p50 (ms)':<16} | {'2xx p95 (ms)':<16} | {'All p50 (ms)':<16}")
        lines.append("-" * 125)

        for lvl in levels:
            temp_db = os.path.abspath(f"test_sweep_{var}_{lvl}.db")
            if os.path.exists(temp_db):
                try: os.remove(temp_db)
                except: pass

            test_engine = create_engine(
                f"sqlite:///{temp_db}",
                connect_args={"check_same_thread": False},
                pool_size=30,
                max_overflow=20,
                pool_timeout=5
            )
            TestSession = sessionmaker(bind=test_engine)

            # Rebind engine & get_db override
            db_mod.Base.metadata.create_all(test_engine)
            db_mod.ensure_schema_migrations(test_engine)
            db_mod.engine = test_engine
            db_mod.SessionLocal = TestSession

            def get_test_db():
                db = TestSession()
                try:
                    yield db
                finally:
                    db.close()

            app_main.app.dependency_overrides[db_mod.get_db] = get_test_db

            # Seed
            s = TestSession()
            total_seed = 5000 if var == "b" else 456
            seed_database(s, engine_bind=test_engine, total_tickets=total_seed, drop_existing=False)
            if var == "b":
                s.query(Ticket).update({Ticket.assigned_to: None, Ticket.status: "New"})
                s.commit()
            ticket_ids = [t.id for t in s.query(Ticket.id).limit(20).all()]
            s.close()

            # Apply config-specific setting
            config_fn()

            transport = httpx.ASGITransport(app=app_main.app)
            runs = []
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=40.0) as client:
                # Warmup
                await run_benchmark_iteration(client, clients=5, duration_sec=2, ticket_ids=ticket_ids)
                # Repeats
                for r_i in range(repeats):
                    res = await run_benchmark_iteration(client, clients=lvl, duration_sec=duration, ticket_ids=ticket_ids)
                    runs.append(res)

            # Cleanup override and engine
            app_main.app.dependency_overrides.pop(db_mod.get_db, None)
            test_engine.dispose()
            if os.path.exists(temp_db):
                try: os.remove(temp_db)
                except: pass

            # Aggregate repeats
            tot_req = sum(r["total_requests"] for r in runs)
            tot_2xx = sum(r["count_2xx"] for r in runs)
            goodputs = [r["goodput"] for r in runs]
            med_gp = statistics.median(goodputs)
            p50_2xxs = [r["p50_2xx"] for r in runs if r["p50_2xx"] > 0]
            med_p50 = statistics.median(p50_2xxs) if p50_2xxs else 0.0
            p95_2xxs = [r["p95_2xx"] for r in runs if r["p95_2xx"] > 0]
            med_p95 = statistics.median(p95_2xxs) if p95_2xxs else 0.0
            p50_alls = [r["p50_all"] for r in runs]
            med_all = statistics.median(p50_alls) if p50_alls else 0.0

            comb_statuses = {}
            for r in runs:
                for k, v in r["statuses"].items():
                    comb_statuses[k] = comb_statuses.get(k, 0) + v
            count_503 = comb_statuses.get(503, 0)
            count_599 = comb_statuses.get(599, 0)
            shed_pct = (count_503 / tot_req * 100.0) if tot_req > 0 else 0.0
            err_pct = (count_599 / tot_req * 100.0) if tot_req > 0 else 0.0

            gp_str = f"{med_gp:.1f} ({min(goodputs):.1f}-{max(goodputs):.1f})"
            row = f"{lvl:<8} | {tot_req:<7} | {tot_2xx:<7} | {gp_str:<18} | {shed_pct:5.1f}%     | {err_pct:5.1f}%    | {med_p50:8.1f} ms      | {med_p95:8.1f} ms      | {med_all:8.1f} ms"
            lines.append(row)
            print(f"[{config_name} Var-{var} C={lvl}] {row}")

    return lines

async def main():
    print("==========================================================================================")
    print("STEP 4: FAIR RE-MEASUREMENT SWEEP ACROSS 4 CONFIGURATIONS")
    print("==========================================================================================")
    levels = [10, 25, 50, 100]
    variants = ["a", "b"]

    all_output = []

    # Config 1: HEAD
    def cfg_head():
        app_main.TRIAGE_CACHE_ENABLED = True
        app_main._evaluate_and_paginate_triage_query = orig_evaluate_triage
    lines_head = await benchmark_config("Config (i) HEAD (B3 Tuple + B4 SWR Cache ON)", cfg_head, levels, variants)
    all_output.extend(lines_head)

    # Config 2: HEAD with B3 reverted (full ORM hydration)
    def cfg_no_b3():
        app_main.TRIAGE_CACHE_ENABLED = True
        app_main._evaluate_and_paginate_triage_query = unoptimized_evaluate_triage
    lines_no_b3 = await benchmark_config("Config (ii) HEAD with B3 Reverted (Full ORM Hydration + SWR)", cfg_no_b3, levels, variants)
    all_output.extend(lines_no_b3)

    # Config 3: HEAD with TRIAGE_CACHE_ENABLED=0
    def cfg_no_cache():
        app_main.TRIAGE_CACHE_ENABLED = False
        app_main._evaluate_and_paginate_triage_query = orig_evaluate_triage
    lines_no_cache = await benchmark_config("Config (iii) HEAD with TRIAGE_CACHE_ENABLED=0", cfg_no_cache, levels, variants)
    all_output.extend(lines_no_cache)

    # Config 4: HEAD with B4 reverted (Pure B3 without SWR)
    def cfg_no_b4():
        app_main.TRIAGE_CACHE_ENABLED = False
        app_main._evaluate_and_paginate_triage_query = orig_evaluate_triage
    lines_no_b4 = await benchmark_config("Config (iv) HEAD with B4 Reverted (Pure B3 Tuple Projection, No SWR)", cfg_no_b4, levels, variants)
    all_output.extend(lines_no_b4)

    output_path = os.path.join(REPO_ROOT, "docs", "perf_runs", "step4_4configs_sweep.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(all_output) + "\n")
    print(f"\nSaved 4-config benchmark sweep to {output_path}")

if __name__ == "__main__":
    anyio.run(main)

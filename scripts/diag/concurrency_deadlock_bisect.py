import os
import sys

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath("."))

temp_db_path = os.path.abspath("test_bisect_temp.db")
if os.path.exists(temp_db_path):
    try: os.remove(temp_db_path)
    except: pass

os.environ["DATABASE_URL"] = f"sqlite:///{temp_db_path}"
os.environ["DB_POOL_SIZE"] = "2"
os.environ["DB_MAX_OVERFLOW"] = "0"
os.environ["DB_POOL_TIMEOUT"] = "3"
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000000"

import asyncio
import time
import traceback
import threading
from typing import Dict, List, Tuple
import anyio
import anyio.to_thread
try:
    import httpx
except ImportError:
    import httpx2 as httpx
from sqlalchemy import event

from backend.app.database import engine, Base, SessionLocal, ensure_schema_migrations
from backend.seed.seed_data import seed_database
from backend.app.main import app
from backend.app.models import Ticket

async def run_bisect():
    # Set AnyIO limiter
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = 4

    print("==========================================================================================")
    print("STEP 2: CONCURRENCY-ONLY DEADLOCK BISECT SETUP")
    print("==========================================================================================")
    print(f"DB_POOL_SIZE: {engine.pool.size()}")
    print(f"DB_MAX_OVERFLOW: {engine.pool._max_overflow}")
    print(f"DB_POOL_TIMEOUT: {engine.pool._timeout}")
    print(f"AnyIO Default Thread Limiter total_tokens: {limiter.total_tokens}")

    # Seed isolated DB
    ensure_schema_migrations(engine)
    db = SessionLocal()
    seed_database(db, engine_bind=engine, total_tickets=50, drop_existing=False)
    db.close()

    # Track checkouts
    active_checkouts: Dict[int, Tuple[float, List[str], str]] = {}
    lock = threading.Lock()

    @event.listens_for(engine, "checkout")
    def on_checkout(dbapi_con, con_record, con_proxy):
        tid = threading.get_ident()
        stack = traceback.format_stack(limit=8)
        with lock:
            active_checkouts[id(dbapi_con)] = (time.time(), stack, threading.current_thread().name)

    @event.listens_for(engine, "checkin")
    def on_checkin(dbapi_con, con_record):
        with lock:
            active_checkouts.pop(id(dbapi_con), None)

    db = SessionLocal()
    t = db.query(Ticket).filter(Ticket.status == "Open").first()
    if not t:
        t = db.query(Ticket).first()
    ticket_id = t.id
    db.close()

    lead_headers = {"X-User-ID": "USR-104", "X-Role": "Lead", "X-Agency-ID": "AGY-001"}
    agent_headers = {"X-User-ID": "USR-101", "X-Role": "Agent", "X-Agency-ID": "AGY-001"}

    test_endpoints = [
        ("GET", "/health", "health_check", lead_headers, None),
        ("GET", "/ready", "readiness_check", lead_headers, None),
        ("POST", "/api/ai/suggest-intent", "api_suggest_intent", lead_headers, {
            "title": "Refund flight", "description": "Flight cancelled by airline"
        }),
        ("GET", "/api/tickets?view=triage&limit=25", "list_tickets [view=triage]", lead_headers, None),
        ("GET", "/api/tickets?view=my_queue&limit=25", "list_tickets [view=my_queue]", agent_headers, None),
        ("GET", "/api/tickets?view=by_region&limit=25", "list_tickets [view=by_region]", lead_headers, None),
        ("GET", "/api/tickets?view=by_intent&limit=25", "list_tickets [view=by_intent]", lead_headers, None),
        ("GET", "/api/tickets?view=linked&limit=25", "list_tickets [view=linked]", lead_headers, None),
        ("POST", "/api/tickets", "create_ticket", lead_headers, {
            "title": "Bisect Test Ticket", "description": "Test ticket for concurrency bisect",
            "tboh_id": "TBOH-BISECT-001", "check_in_date": "2026-12-01T10:00:00Z",
            "priority": "Medium", "intent": "Refund Request", "agency_id": "AGY-001"
        }),
        ("GET", f"/api/tickets/{ticket_id}", "get_ticket_details", lead_headers, None),
        ("POST", f"/api/tickets/{ticket_id}/assign", "assign_ticket", lead_headers, {"agent_id": "USR-101"}),
        ("POST", f"/api/tickets/{ticket_id}/unassign", "unassign_ticket", lead_headers, {}),
        ("POST", f"/api/tickets/{ticket_id}/status", "update_ticket_status", lead_headers, {"status": "Pending"}),
        ("POST", f"/api/tickets/{ticket_id}/escalate", "escalate_ticket", lead_headers, {"reason": "Executive attention required"}),
        ("POST", f"/api/tickets/{ticket_id}/transfer", "transfer_ticket", lead_headers, {"target_agent_id": "USR-102", "reason": "Realignment"}),
        ("POST", f"/api/tickets/{ticket_id}/messages", "post_ticket_message", lead_headers, {"message_type": "InternalNote", "content": "Note"}),
        ("GET", f"/api/tickets/{ticket_id}/side-threads", "list_side_threads", lead_headers, None),
        ("POST", f"/api/tickets/{ticket_id}/side-threads", "create_side_thread", lead_headers, {
            "supplier_name": "Hotel", "subject": "Inquiry", "recipients": ["res@hotel.com"], "initial_message": "Msg"
        }),
        ("POST", f"/api/tickets/{ticket_id}/link-suggestion", "link_suggested_bug", lead_headers, {"bug_link": "https://bugs/1"}),
        ("GET", "/api/insights/themes", "get_top_themes", lead_headers, None),
        ("GET", "/api/export/tickets.csv", "export_tickets_csv", lead_headers, None),
    ]

    transport = httpx.ASGITransport(app=app)
    
    print("\n--- PART A: PER-ENDPOINT CONCURRENCY BISECT (12 concurrent requests) ---")
    header = f"{'Endpoint':<42} | {'Statuses':<24} | {'Drain Time':<11} | {'Idle CheckedOut':<16} | {'Candidate?'}"
    print(header)
    print("-" * len(header))

    candidates = []

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=15.0) as client:
        for method, path, label, headers, payload in test_endpoints:
            # Run 12 concurrent requests
            async def send_req(i):
                try:
                    if method == "GET":
                        r = await client.get(path, headers=headers)
                    elif method == "POST":
                        # Ensure unique tboh_id for create_ticket
                        pl = payload.copy() if payload else None
                        if pl and "tboh_id" in pl:
                            pl["tboh_id"] = f"TBOH-BISECT-{label[:5]}-{i}-{time.time()}"[-30:]
                        r = await client.post(path, headers=headers, json=pl)
                    return r.status_code
                except Exception as e:
                    return 599

            t0 = time.perf_counter()
            tasks = [send_req(i) for i in range(12)]
            results = await asyncio.gather(*tasks)
            drain_time = time.perf_counter() - t0

            # Count statuses
            status_counts = {}
            for s in results:
                status_counts[s] = status_counts.get(s, 0) + 1
            status_str = ", ".join(f"{k}:{v}" for k, v in sorted(status_counts.items()))

            # 10s idle check for leaks
            await asyncio.sleep(10.0)
            with lock:
                checked_out_idle = engine.pool.checkedout()

            is_candidate = "YES" if (checked_out_idle > 0 or 503 in status_counts or 599 in status_counts) else "NO"
            if is_candidate == "YES":
                candidates.append((label, status_counts, checked_out_idle))

            row = f"{label:<42} | {status_str:<24} | {drain_time:>8.2f} s | {checked_out_idle:<16} | {is_candidate}"
            print(row)

            if checked_out_idle > 0:
                print("  [LEAKED CONNECTION HOLDER STACKS]:")
                with lock:
                    for cid, (t_time, st, t_name) in active_checkouts.items():
                        print(f"    Thread {t_name} holding for {time.time()-t_time:.1f}s:")
                        for f in st[-5:]:
                            print("      " + f.strip())

        # Mixed set: 12 concurrent requests mixed across endpoints
        print("\n--- MIXED SET CONCURRENCY TEST (12 concurrent requests across endpoints) ---")
        mixed_cases = [
            ("GET", "/api/tickets?view=triage&limit=25", lead_headers, None),
            ("GET", f"/api/tickets/{ticket_id}", lead_headers, None),
            ("POST", "/api/tickets", lead_headers, {
                "title": "Mixed Ticket", "description": "Mixed description",
                "tboh_id": "TBOH-MIXED-001", "check_in_date": "2026-12-01T10:00:00Z",
                "priority": "Medium", "agency_id": "AGY-001"
            }),
            ("POST", f"/api/tickets/{ticket_id}/assign", lead_headers, {"agent_id": "USR-101"}),
            ("GET", "/api/insights/themes", lead_headers, None),
            ("GET", "/api/tickets?view=my_queue&limit=25", agent_headers, None),
            ("GET", "/api/export/tickets.csv", lead_headers, None),
            ("GET", "/health", lead_headers, None),
            ("GET", "/ready", lead_headers, None),
            ("POST", "/api/ai/suggest-intent", lead_headers, {"title": "Flight cancel", "description": "Please refund"}),
            ("GET", "/api/tickets?view=by_region&limit=25", lead_headers, None),
            ("GET", "/api/tickets?view=by_intent&limit=25", lead_headers, None),
        ]

        async def send_mixed(m, p, h, pl, idx):
            try:
                p_copy = pl.copy() if pl else None
                if p_copy and "tboh_id" in p_copy:
                    p_copy["tboh_id"] = f"TBOH-M-{idx}-{time.time()}"[-30:]
                if m == "GET":
                    r = await client.get(p, headers=h)
                elif m == "POST":
                    r = await client.post(p, headers=h, json=p_copy)
                return r.status_code
            except Exception:
                return 599

        t0 = time.perf_counter()
        tasks = [send_mixed(m, p, h, pl, i) for i, (m, p, h, pl) in enumerate(mixed_cases)]
        results = await asyncio.gather(*tasks)
        drain_time = time.perf_counter() - t0

        status_counts = {}
        for s in results:
            status_counts[s] = status_counts.get(s, 0) + 1
        status_str = ", ".join(f"{k}:{v}" for k, v in sorted(status_counts.items()))

        await asyncio.sleep(10.0)
        with lock:
            checked_out_idle = engine.pool.checkedout()

        print(f"Mixed Set | Statuses: {status_str} | Drain Time: {drain_time:.2f} s | Idle CheckedOut: {checked_out_idle}")

    # Cleanup temp db
    if os.path.exists(temp_db_path):
        try: os.remove(temp_db_path)
        except: pass

if __name__ == "__main__":
    anyio.run(run_bisect)

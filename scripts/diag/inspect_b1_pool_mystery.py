import os
import sys

sys.path.insert(0, os.path.abspath("."))

temp_db_path = os.path.abspath("test_b1_mystery_temp.db")
if os.path.exists(temp_db_path):
    try: os.remove(temp_db_path)
    except: pass

os.environ["DATABASE_URL"] = f"sqlite:///{temp_db_path}"
os.environ["DB_POOL_SIZE"] = "30"
os.environ["DB_MAX_OVERFLOW"] = "20"
os.environ["DB_POOL_TIMEOUT"] = "5"
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000000"

import asyncio
import time
import traceback
import threading
import random
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

async def run_b1_mystery():
    limiter = anyio.to_thread.current_default_thread_limiter()
    print("==========================================================================================")
    print("STEP 2 INVESTIGATION: B1 POOL MYSTERY (POOL 30/20 vs THREADPOOL 40)")
    print("==========================================================================================")
    print(f"DB_POOL_SIZE: {engine.pool.size()}")
    print(f"DB_MAX_OVERFLOW: {engine.pool._max_overflow}")
    print(f"DB_POOL_TIMEOUT: {engine.pool._timeout}")
    print(f"AnyIO Default Thread Limiter total_tokens: {limiter.total_tokens}")

    # Seed isolated DB with normal seed (~456 tickets)
    ensure_schema_migrations(engine)
    db = SessionLocal()
    seed_database(db, engine_bind=engine, total_tickets=456, drop_existing=False)
    db.close()

    # Track active checkouts and pool timeout events
    active_checkouts = {} # id(dbapi_con) -> (thread_id, thread_name, start_time, stack)
    timeout_captures = []
    lock = threading.Lock()
    first_timeout_event = threading.Event()

    @event.listens_for(engine, "checkout")
    def on_checkout(dbapi_con, con_record, con_proxy):
        tid = threading.get_ident()
        tname = threading.current_thread().name
        stack = traceback.format_stack(limit=25)
        with lock:
            active_checkouts[id(dbapi_con)] = (tid, tname, time.time(), stack)

    @event.listens_for(engine, "checkin")
    def on_checkin(dbapi_con, con_record):
        with lock:
            active_checkouts.pop(id(dbapi_con), None)

    # Wrap pool._do_get or monitor timeouts
    original_do_get = engine.pool._do_get
    def tracked_do_get(*args, **kwargs):
        try:
            return original_do_get(*args, **kwargs)
        except Exception as e:
            if "Timeout" in type(e).__name__ or "timeout" in str(e).lower():
                with lock:
                    checked_count = engine.pool.checkedout()
                    borrowed = limiter.borrowed_tokens
                    # Snapshot active holders
                    snapshot = []
                    now = time.time()
                    for cid, (tid, tname, stime, st) in list(active_checkouts.items()):
                        snapshot.append({
                            "cid": cid, "tid": tid, "tname": tname,
                            "duration_sec": now - stime,
                            "stack": st
                        })
                    timeout_captures.append({
                        "timestamp": now,
                        "checked_count": checked_count,
                        "borrowed_tokens": borrowed,
                        "pool_size": engine.pool.size(),
                        "overflow": engine.pool.overflow(),
                        "holders": snapshot
                    })
                    first_timeout_event.set()
            raise

    engine.pool._do_get = tracked_do_get

    transport = httpx.ASGITransport(app=app)
    lead_headers = {"X-User-ID": "USR-104", "X-Role": "Lead", "X-Agency-ID": "AGY-001"}

    db = SessionLocal()
    ticket_ids = [t.id for t in db.query(Ticket.id).limit(10).all()]
    db.close()

    print("\nRunning closed-loop load test with 100 concurrent clients for 15 seconds...")

    # Workload mix: 70% triage, 20% detail, 5% create, 5% assign
    stop_event = asyncio.Event()

    status_counts = {}
    total_requests = 0

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=30.0) as client:
        async def client_worker(worker_id):
            nonlocal total_requests
            while not stop_event.is_set():
                roll = random.random()
                try:
                    if roll < 0.70:
                        r = await client.get("/api/tickets?view=triage&limit=25", headers=lead_headers)
                    elif roll < 0.90:
                        tid = random.choice(ticket_ids) if ticket_ids else "TCK-1001"
                        r = await client.get(f"/api/tickets/{tid}", headers=lead_headers)
                    elif roll < 0.95:
                        r = await client.post("/api/tickets", headers=lead_headers, json={
                            "title": f"Tkt-{worker_id}", "description": "Desc for mystery test",
                            "tboh_id": f"TBOH-MYS-{worker_id}-{time.time()}"[-30:],
                            "check_in_date": "2026-12-01T10:00:00Z", "priority": "Medium",
                            "agency_id": "AGY-001", "intent": "Refund Request"
                        })
                    else:
                        tid = random.choice(ticket_ids) if ticket_ids else "TCK-1001"
                        r = await client.post(f"/api/tickets/{tid}/assign", headers=lead_headers, json={"agent_id": "USR-101"})

                    sc = r.status_code
                    status_counts[sc] = status_counts.get(sc, 0) + 1
                    total_requests += 1
                except Exception as e:
                    status_counts[599] = status_counts.get(599, 0) + 1
                    total_requests += 1

        workers = [asyncio.create_task(client_worker(i)) for i in range(100)]
        # Run for 15 seconds or until timeout is captured
        await asyncio.sleep(15.0)
        stop_event.set()
        await asyncio.gather(*workers, return_exceptions=True)

    print(f"\nTotal Requests Completed: {total_requests}")
    print(f"Status Distribution: {status_counts}")
    print(f"Pool Timeouts Captured: {len(timeout_captures)}")

    if timeout_captures:
        first = timeout_captures[0]
        print("\n==========================================================================================")
        print("FIRST POOL-TIMEOUT CAPTURE MOMENT METRICS:")
        print("==========================================================================================")
        print(f"  Timestamp: {first['timestamp']}")
        print(f"  CheckedOut Connections: {first['checked_count']} (out of max pool capacity 50)")
        print(f"  AnyIO Borrowed Tokens:  {first['borrowed_tokens']} (out of total tokens 40)")
        print(f"  Pool Overflow:          {first['overflow']}")
        print(f"  Number of Active Holders: {len(first['holders'])}")
        # Check duplicate thread IDs
        tids = [h['tid'] for h in first['holders']]
        from collections import Counter
        tid_counts = Counter(tids)
        multi_holder_threads = {t: c for t, c in tid_counts.items() if c > 1}
        print(f"\n  UNIQUE THREADS HOLDING CONNECTIONS: {len(tid_counts)}")
        print(f"  THREADS HOLDING >1 CONNECTION: {multi_holder_threads}")

        thread_categories = {}
        for h in first['holders']:
            tname = h['tname']
            thread_categories[tname] = thread_categories.get(tname, 0) + 1
        print(f"\n  HOLDER THREAD CATEGORIES (Total {len(first['holders'])}):")
        for tname, cnt in sorted(thread_categories.items()):
            print(f"    {tname}: {cnt} connections")

        if multi_holder_threads:
            sample_tid = list(multi_holder_threads.keys())[0]
            print(f"\n==========================================================================================")
            print(f"INSPECTING MULTI-HOLDER THREAD {sample_tid} (holds {multi_holder_threads[sample_tid]} connections!):")
            print(f"==========================================================================================")
            sample_holders = [h for h in first['holders'] if h['tid'] == sample_tid]
            for i, sh in enumerate(sample_holders):
                print(f"\n  --- Connection #{i+1} [CID: {sh['cid']}, Duration: {sh['duration_sec']:.2f}s] ---")
                for frame in sh['stack']:
                    print("    " + frame.strip())
        for h in first['holders']:
            tname = h['tname']
            thread_categories[tname] = thread_categories.get(tname, 0) + 1
        print(f"\n  HOLDER THREAD CATEGORIES (Total {len(first['holders'])}):")
        for tname, cnt in sorted(thread_categories.items()):
            print(f"    {tname}: {cnt} connections")

        print("\n  SAMPLE HOLDER THREADS & STACKS AT TIMEOUT MOMENT:")
        for idx, h in enumerate(first['holders'][:10]):
            frames = [f.strip().replace('\n', ' ') for f in h['stack'] if 'backend' in f or 'site-packages' in f][-3:]
            print(f"    Holder #{idx+1} [TID: {h['tid']}, Name: {h['tname']}, Held: {h['duration_sec']:.2f}s]:")
            for f in frames:
                print(f"      {f}")
    else:
        print("\nNo pool timeouts occurred during this 15s window under HEAD.")
        print(f"Max checkedout connections remained healthy. Current checkedout: {engine.pool.checkedout()}")

    # Cleanup temp db
    if os.path.exists(temp_db_path):
        try: os.remove(temp_db_path)
        except: pass

if __name__ == "__main__":
    anyio.run(run_b1_mystery)

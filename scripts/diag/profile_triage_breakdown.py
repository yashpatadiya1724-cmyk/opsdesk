import os
import sys
import time
import cProfile
import pstats
import tempfile
import statistics
from datetime import datetime

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.diag.make_triage_heavy_db import make_triage_heavy_db
from backend.seed.seed_data import seed_database
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, defer
from backend.app.models import Ticket
from backend.app.database import Base
from backend.services.sla_engine import evaluate_travel_sla
from backend.services.routing_engine import calculate_queue_score_tier2

def stats_str(arr):
    return f"median={statistics.median(arr):.2f} ms (min={min(arr):.2f}, max={max(arr):.2f})"

def main():
    print("==========================================================================================")
    print("A6 TRIAGE BREAKDOWN PROFILING: BEFORE (UNOPTIMIZED) vs AFTER (B3 TUPLE PROJECTION)")
    print("Database: Variant (b) ~5000 tickets, unassigned triage heavy")
    print("Repetitions: N=10 runs each, Cache: OFF")
    print("==========================================================================================")

    temp_dir = tempfile.mkdtemp()
    temp_db_src = os.path.join(temp_dir, "seed.db")
    temp_db_b = os.path.join(temp_dir, "triage_heavy.db")

    engine_src = create_engine(f"sqlite:///{temp_db_src}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine_src)
    SessionSrc = sessionmaker(bind=engine_src)
    sess_src = SessionSrc()
    print("Seeding base 5000 tickets...")
    seed_database(sess_src, engine_bind=engine_src, total_tickets=5000)
    sess_src.close()
    engine_src.dispose()

    unassigned_cnt = make_triage_heavy_db(temp_db_src, temp_db_b)
    print(f"Variant (b) created with {unassigned_cnt} unassigned rows.\n")

    engine_b = create_engine(f"sqlite:///{temp_db_b}", connect_args={"check_same_thread": False})
    SessionB = sessionmaker(bind=engine_b)

    N = 10
    now = datetime.utcnow()

    # --------------------------------------------------------------------------------------
    # 1. BEFORE: Full ORM Hydration (All 5000 rows hydrated as Ticket models)
    # --------------------------------------------------------------------------------------
    before_db_fetch = []
    before_scoring = []
    before_sort = []
    before_dict = []
    before_total = []

    for _ in range(N):
        sess = SessionB()
        t0 = time.perf_counter()

        # DB fetch + full ORM hydration
        t_db0 = time.perf_counter()
        query = sess.query(Ticket).filter(
            Ticket.status.in_(["New", "Open", "Pending", "Escalated"]),
            Ticket.assigned_to.is_(None)
        )
        all_candidates = query.options(defer(Ticket.description)).all()
        t_db1 = time.perf_counter()

        # Scoring loop
        t_score0 = time.perf_counter()
        scored_tickets = []
        for t in all_candidates:
            sla = evaluate_travel_sla(
                status=t.status,
                check_in_date=t.check_in_date,
                lcd_date=t.lcd_date,
                priority=t.priority,
                intent=t.intent,
                now=now
            )
            queue_score = calculate_queue_score_tier2(
                priority=t.priority,
                check_in_date=t.check_in_date,
                lcd_date=t.lcd_date,
                intent=t.intent,
                now=now
            )
            scored_tickets.append((queue_score, sla, t))
        t_score1 = time.perf_counter()

        # Sort
        t_sort0 = time.perf_counter()
        scored_tickets.sort(key=lambda x: (x[0], -x[2].created_at.timestamp() if x[2].created_at else 0), reverse=True)
        paginated_slice = scored_tickets[0:50]
        t_sort1 = time.perf_counter()

        # Dict preparation
        t_dict0 = time.perf_counter()
        results = []
        for queue_score, sla, t in paginated_slice:
            results.append({
                "id": t.id,
                "tboh_id": t.tboh_id,
                "agency_id": t.agency_id,
                "title": t.title,
                "intent": t.intent,
                "priority": t.priority,
                "status": t.status,
                "check_in_date": t.check_in_date.isoformat(),
                "lcd_date": t.lcd_date.isoformat() if t.lcd_date else None,
                "assigned_to": t.assigned_to,
                "routing_reason": t.routing_reason,
                "sla": sla,
                "queue_score": queue_score,
                "created_at": t.created_at.isoformat()
            })
        payload = {"total": len(all_candidates), "tickets": results}
        t_dict1 = time.perf_counter()

        t_tot = time.perf_counter() - t0
        before_db_fetch.append((t_db1 - t_db0) * 1000.0)
        before_scoring.append((t_score1 - t_score0) * 1000.0)
        before_sort.append((t_sort1 - t_sort0) * 1000.0)
        before_dict.append((t_dict1 - t_dict0) * 1000.0)
        before_total.append(t_tot * 1000.0)
        sess.close()

    # --------------------------------------------------------------------------------------
    # 2. AFTER: B3 Tuple Projection + Slice Hydration (Lightweight query + top-K slice)
    # --------------------------------------------------------------------------------------
    after_db_fetch = []
    after_scoring = []
    after_sort = []
    after_slice_hydration = []
    after_dict = []
    after_total = []

    for _ in range(N):
        sess = SessionB()
        t0 = time.perf_counter()

        # Tuple projection query
        t_db0 = time.perf_counter()
        query = sess.query(Ticket).filter(
            Ticket.status.in_(["New", "Open", "Pending", "Escalated"]),
            Ticket.assigned_to.is_(None)
        )
        candidate_rows = query.with_entities(
            Ticket.id,
            Ticket.priority,
            Ticket.check_in_date,
            Ticket.lcd_date,
            Ticket.intent,
            Ticket.created_at,
            Ticket.status
        ).all()
        t_db1 = time.perf_counter()

        # Scoring loop over tuples
        t_score0 = time.perf_counter()
        scored_items = []
        for row in candidate_rows:
            t_id, priority_val, check_in_date_val, lcd_date_val, intent_val, created_at_val, status_val = row
            sla = evaluate_travel_sla(
                status=status_val,
                check_in_date=check_in_date_val,
                lcd_date=lcd_date_val,
                priority=priority_val,
                intent=intent_val,
                now=now
            )
            queue_score = calculate_queue_score_tier2(
                priority=priority_val,
                check_in_date=check_in_date_val,
                lcd_date=lcd_date_val,
                intent=intent_val,
                now=now
            )
            scored_items.append((queue_score, sla, t_id, created_at_val))
        t_score1 = time.perf_counter()

        # Sort
        t_sort0 = time.perf_counter()
        scored_items.sort(key=lambda x: (x[0], -x[3].timestamp() if x[3] else 0), reverse=True)
        paginated_slice = scored_items[0:50]
        t_sort1 = time.perf_counter()

        # Slice hydration (50 rows only)
        t_hyd0 = time.perf_counter()
        slice_ids = [item[2] for item in paginated_slice]
        slice_tickets_by_id = {
            t.id: t for t in sess.query(Ticket).options(defer(Ticket.description)).filter(Ticket.id.in_(slice_ids)).all()
        }
        t_hyd1 = time.perf_counter()

        # Dict preparation
        t_dict0 = time.perf_counter()
        results = []
        for queue_score, sla, t_id, _ in paginated_slice:
            t = slice_tickets_by_id.get(t_id)
            if not t:
                continue
            results.append({
                "id": t.id,
                "tboh_id": t.tboh_id,
                "agency_id": t.agency_id,
                "title": t.title,
                "intent": t.intent,
                "priority": t.priority,
                "status": t.status,
                "check_in_date": t.check_in_date.isoformat(),
                "lcd_date": t.lcd_date.isoformat() if t.lcd_date else None,
                "assigned_to": t.assigned_to,
                "routing_reason": t.routing_reason,
                "sla": sla,
                "queue_score": queue_score,
                "created_at": t.created_at.isoformat()
            })
        payload = {"total": len(candidate_rows), "tickets": results}
        t_dict1 = time.perf_counter()

        t_tot = time.perf_counter() - t0
        after_db_fetch.append((t_db1 - t_db0) * 1000.0)
        after_scoring.append((t_score1 - t_score0) * 1000.0)
        after_sort.append((t_sort1 - t_sort0) * 1000.0)
        after_slice_hydration.append((t_hyd1 - t_hyd0) * 1000.0)
        after_dict.append((t_dict1 - t_dict0) * 1000.0)
        after_total.append(t_tot * 1000.0)
        sess.close()

    print("=== BEFORE (FULL ORM HYDRATION) - N=10 runs ===")
    print(f"1. DB Fetch + Full ORM Hydration : {stats_str(before_db_fetch)}")
    print(f"2. Python Scoring Loop           : {stats_str(before_scoring)}")
    print(f"3. Python Sorting                : {stats_str(before_sort)}")
    print(f"4. Dict & Formatting             : {stats_str(before_dict)}")
    print(f"Total Triage Request Time (BEFORE): {stats_str(before_total)}")

    print("\n=== AFTER (B3 TUPLE PROJECTION + TOP-50 SLICE) - N=10 runs ===")
    print(f"1. DB Tuple Projection Query     : {stats_str(after_db_fetch)}")
    print(f"2. Python Scoring Loop (Tuples)  : {stats_str(after_scoring)}")
    print(f"3. Python Sorting                : {stats_str(after_sort)}")
    print(f"4. Slice Hydration (50 rows)     : {stats_str(after_slice_hydration)}")
    print(f"5. Dict & Formatting             : {stats_str(after_dict)}")
    print(f"Total Triage Request Time (AFTER) : {stats_str(after_total)}")

    med_before = statistics.median(before_total)
    med_after = statistics.median(after_total)
    diff_ms = med_before - med_after
    print(f"\nNet In-Process Improvement: {med_before:.2f} ms -> {med_after:.2f} ms (Delta: -{diff_ms:.2f} ms)")

if __name__ == "__main__":
    main()

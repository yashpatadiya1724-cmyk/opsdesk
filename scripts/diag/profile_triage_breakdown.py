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
from backend.app.models import Ticket, User
from backend.app.database import Base
from backend.services.sla_engine import evaluate_travel_sla
from backend.services.routing_engine import calculate_queue_score_tier2

def main():
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
    print(f"Variant (b) created with {unassigned_cnt} unassigned rows.")

    engine_b = create_engine(f"sqlite:///{temp_db_b}", connect_args={"check_same_thread": False})
    SessionB = sessionmaker(bind=engine_b)

    # Breakdown profiling: N=10 repetitions
    N = 10
    db_fetch_times = []
    scoring_times = []
    sort_times = []
    dict_build_times = []
    total_times = []

    now = datetime.utcnow()

    for i in range(N):
        sess = SessionB()
        t0 = time.perf_counter()

        # 1. DB fetch + ORM hydration
        t_db0 = time.perf_counter()
        query = sess.query(Ticket).filter(
            Ticket.status.in_(["New", "Open", "Pending", "Escalated"]),
            Ticket.assigned_to.is_(None)
        )
        all_candidates = query.options(defer(Ticket.description)).all()
        t_db1 = time.perf_counter()

        # 2. Scoring loop
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

        # 3. Sort
        t_sort0 = time.perf_counter()
        scored_tickets.sort(key=lambda x: (x[0], -x[2].created_at.timestamp() if x[2].created_at else 0), reverse=True)
        paginated_slice = scored_tickets[0:50]
        t_sort1 = time.perf_counter()

        # 4. Dict / JSON preparation
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

        t_total = time.perf_counter() - t0

        db_fetch_times.append((t_db1 - t_db0) * 1000.0)
        scoring_times.append((t_score1 - t_score0) * 1000.0)
        sort_times.append((t_sort1 - t_sort0) * 1000.0)
        dict_build_times.append((t_dict1 - t_dict0) * 1000.0)
        total_times.append(t_total * 1000.0)

        sess.close()

    print("\n=== TRIAGE BREAKDOWN MEASUREMENTS (N=10 runs, ms) ===")
    def stats_str(arr):
        return f"median={statistics.median(arr):.2f} ms (min={min(arr):.2f}, max={max(arr):.2f})"

    print(f"1. DB Fetch + ORM Hydration : {stats_str(db_fetch_times)}")
    print(f"2. Python Scoring Loop      : {stats_str(scoring_times)}")
    print(f"3. Python Sorting           : {stats_str(sort_times)}")
    print(f"4. Dict & Formatting        : {stats_str(dict_build_times)}")
    print(f"Total Triage Request Time   : {stats_str(total_times)}")

    # cProfile run
    print("\n=== cProfile TOP 15 CUMULATIVE TIME ===")
    profiler = cProfile.Profile()
    sess = SessionB()
    profiler.enable()

    query = sess.query(Ticket).filter(
        Ticket.status.in_(["New", "Open", "Pending", "Escalated"]),
        Ticket.assigned_to.is_(None)
    )
    all_candidates = query.options(defer(Ticket.description)).all()
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
        q_score = calculate_queue_score_tier2(
            priority=t.priority,
            check_in_date=t.check_in_date,
            lcd_date=t.lcd_date,
            intent=t.intent,
            now=now
        )
        scored_tickets.append((q_score, sla, t))
    scored_tickets.sort(key=lambda x: (x[0], -x[2].created_at.timestamp() if x[2].created_at else 0), reverse=True)
    paginated_slice = scored_tickets[0:50]

    profiler.disable()
    sess.close()

    stats = pstats.Stats(profiler).sort_stats("cumulative")
    stats.print_stats(15)

if __name__ == "__main__":
    main()

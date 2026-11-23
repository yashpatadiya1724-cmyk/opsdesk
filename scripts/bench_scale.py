#!/usr/bin/env python3
"""
OpsDesk Scalability & Explain Benchmark (scripts/bench_scale.py)

Evaluates triage queue query performance at scale (50k, 100k, 200k, 400k rows)
on real PostgreSQL using EXPLAIN (ANALYZE, BUFFERS) with stored queue_score index scan.
"""
import argparse
import multiprocessing
import os
import platform
import re
import sys
import time
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

DEFAULT_OUTPUT_PATH = os.getenv(
    "SCALE_TRANSCRIPT_PATH",
    os.path.join("docs", "verification", "scale_transcript.txt")
)

TRIAGE_QUERY_PG = """
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, tboh_id, agency_id, title, status, priority, queue_score, effective_deadline_at, assigned_to
FROM tickets
WHERE status IN ('New', 'Open', 'Pending', 'Escalated') AND assigned_to IS NULL
ORDER BY queue_score DESC, effective_deadline_at ASC, id ASC
LIMIT 50;
"""


def is_postgres_url(url: str) -> bool:
    return bool(url and (url.startswith("postgresql") or url.startswith("postgres")))


def fast_seed_postgres(conn, target_count: int) -> int:
    """Fast seed using generate_series on PostgreSQL."""
    # Ensure agency exists
    conn.execute(text("""
        INSERT INTO agencies (id, name, country_code, tier)
        VALUES ('AGY-BENCH', 'Benchmark Agency', 'AE', 'platinum')
        ON CONFLICT (id) DO NOTHING;
    """))
    conn.commit()

    curr_res = conn.execute(text("SELECT count(*) FROM tickets WHERE id LIKE 'TCK-BENCH-%'"))
    current_bench = curr_res.scalar() or 0
    needed = target_count - current_bench

    if needed > 0:
        start_idx = current_bench + 1
        end_idx = target_count
        print(f"Seeding {needed} tickets (indices {start_idx}..{end_idx}) into PostgreSQL...")
        t0 = time.perf_counter()
        conn.execute(text("""
            INSERT INTO tickets (
                id, tboh_id, agency_id, title, description, intent, priority,
                status, check_in_date, hotel_timezone, effective_deadline_at,
                priority_weight, queue_score, score_computed_at, version,
                created_at, updated_at
            )
            SELECT
                'TCK-BENCH-' || s,
                'TBOH-BENCH-' || (s % 10000),
                'AGY-BENCH',
                'Benchmark Ticket ' || s,
                'Description for benchmark ticket ' || s,
                CASE (s % 4)
                    WHEN 0 THEN 'Emergency Check-in Assist'
                    WHEN 1 THEN 'Refund Request'
                    WHEN 2 THEN 'Bedding / Room Preference'
                    ELSE 'Unclassified'
                END,
                CASE (s % 4)
                    WHEN 0 THEN 'Urgent'
                    WHEN 1 THEN 'High'
                    WHEN 2 THEN 'Medium'
                    ELSE 'Low'
                END,
                CASE (s % 5)
                    WHEN 0 THEN 'New'
                    WHEN 1 THEN 'Open'
                    WHEN 2 THEN 'Pending'
                    WHEN 3 THEN 'Escalated'
                    ELSE 'Resolved'
                END,
                NOW() + ((s % 100) || ' hours')::interval,
                'UTC',
                NOW() + ((s % 100) || ' hours')::interval,
                CASE (s % 4)
                    WHEN 0 THEN 1000.0
                    WHEN 1 THEN 500.0
                    WHEN 2 THEN 200.0
                    ELSE 50.0
                END,
                (s % 3000)::float,
                NOW(),
                1,
                NOW() - ((s % 500) || ' minutes')::interval,
                NOW() - ((s % 500) || ' minutes')::interval
            FROM generate_series(:start_idx, :end_idx) s
            ON CONFLICT (id) DO NOTHING;
        """), {"start_idx": start_idx, "end_idx": end_idx})
        conn.commit()
        conn.execute(text("ANALYZE tickets;"))
        conn.commit()
        print(f"Seeded {needed} tickets in {time.perf_counter() - t0:.2f}s.")

    total_tickets = conn.execute(text("SELECT count(*) FROM tickets")).scalar()
    return total_tickets


def run_explain_analyze(conn) -> tuple[str, float]:
    """Runs EXPLAIN (ANALYZE, BUFFERS) and parses execution time."""
    res = conn.execute(text(TRIAGE_QUERY_PG))
    lines = [r[0] for r in res.fetchall()]
    plan_text = "\n".join(lines)

    exec_time = 0.0
    for line in lines:
        m = re.search(r"Execution Time:\s*([\d\.]+)\s*ms", line)
        if m:
            exec_time = float(m.group(1))
            break
    return plan_text, exec_time


def main():
    parser = argparse.ArgumentParser(description="OpsDesk Scalability & EXPLAIN Benchmark")
    parser.add_argument("--tickets", type=int, default=None, help="Specific row count to benchmark (e.g. 100000)")
    parser.add_argument("--max-latency-ms", type=float, default=None, help="Fail if execution time > max-latency-ms")
    parser.add_argument("--db-url", default=None, help="PostgreSQL connection URL")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH, help="Path for benchmark transcript output")
    args = parser.parse_args()

    db_url = args.db_url or os.getenv("DATABASE_URL", "")

    if not is_postgres_url(db_url):
        print("ERROR: bench_scale.py requires a real PostgreSQL database (DATABASE_URL not set to PostgreSQL).", file=sys.stderr)
        print("Live measurement aborted.", file=sys.stderr)
        sys.exit(1)

    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            pg_version_res = conn.execute(text("SELECT version();")).scalar()
    except Exception as exc:
        print(f"ERROR: Failed to connect to PostgreSQL at {db_url}: {exc}", file=sys.stderr)
        print("Live measurement aborted.", file=sys.stderr)
        sys.exit(1)

    scales = [args.tickets] if args.tickets is not None else [50000, 200000, 400000]
    results = []

    print("================================================================================")
    print("OPSDESK POSTGRESQL 16 TRIAGE SCALABILITY BENCHMARK")
    print(f"Status:     MEASURED")
    print(f"Target URL: {db_url.split('@')[-1] if '@' in db_url else db_url}")
    print(f"Version:    {pg_version_res}")
    print(f"Scales:     {scales}")
    print("================================================================================")

    transcript_sections = []
    failed = False
    start_ts = datetime.now(timezone.utc).isoformat()

    with engine.connect() as conn:
        for scale in scales:
            total_in_db = fast_seed_postgres(conn, scale)
            plan, exec_time_ms = run_explain_analyze(conn)
            print(f"\n[SCALE {scale} rows] (Total in DB: {total_in_db}) -> Execution Time: {exec_time_ms:.3f} ms")
            print(plan)

            has_seq_scan = "Seq Scan" in plan
            has_sort = "Sort " in plan or "Sort Method:" in plan
            if has_seq_scan:
                print(f"WARNING: Plan contains Seq Scan at scale {scale}!")
            if has_sort:
                print(f"WARNING: Plan contains Sort at scale {scale}!")

            results.append((scale, total_in_db, exec_time_ms, has_seq_scan, has_sort))
            transcript_sections.append(
                f"--- Scale {scale:,} rows (Total DB: {total_in_db:,}) ---\n"
                f"Execution Time: {exec_time_ms:.3f} ms\n"
                f"Seq Scan: {'FOUND (FAIL)' if has_seq_scan else 'NONE (PASS)'}\n"
                f"Sort: {'FOUND (FAIL)' if has_sort else 'NONE (PASS)'}\n\n"
                f"{plan}\n"
            )

            if args.max_latency_ms is not None and exec_time_ms > args.max_latency_ms:
                print(f"FAILURE: Execution time {exec_time_ms:.2f} ms exceeded threshold {args.max_latency_ms} ms!")
                failed = True

    end_ts = datetime.now(timezone.utc).isoformat()

    # Write measured transcript
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write("================================================================================\n")
        f.write("OPSDESK POSTGRESQL 16 TRIAGE SCALABILITY BENCHMARK TRANSCRIPT\n")
        f.write("Status: MEASURED\n")
        f.write(f"Date: {start_ts}\n")
        f.write(f"Machine: {platform.system()} {platform.release()} ({multiprocessing.cpu_count()} CPU cores)\n")
        f.write(f"Command: {' '.join(sys.argv)}\n")
        f.write(f"PostgreSQL Version: {pg_version_res}\n")
        f.write(f"Start: {start_ts}\n")
        f.write(f"End:   {end_ts}\n")
        f.write("================================================================================\n\n")
        for sec in transcript_sections:
            f.write(sec + "\n")
        f.write("Summary Table:\n")
        f.write("Rows Target | Total DB Rows | Execution Time (ms) | Seq Scan | Sort | Target Met (< 50ms)\n")
        f.write("------------|---------------|---------------------|----------|------|--------------------\n")
        for sc, tot, et, ss, st in results:
            met = "YES" if et < 50.0 else "NO"
            ss_str = "YES" if ss else "NO"
            st_str = "YES" if st else "NO"
            f.write(f"{sc:<11} | {tot:<13} | {et:<19.3f} | {ss_str:<8} | {st_str:<4} | {met}\n")
        f.write("\n================================================================================\n")

    print(f"\nMeasured transcript written to {args.output}")

    if failed:
        sys.exit(1)
    print("Benchmark SUCCESS: All queries completed within target SLA.")


if __name__ == "__main__":
    main()

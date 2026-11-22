"""
OpsDesk Synthetic Load & Concurrency Benchmark
Measures latency (p50, p95, p99), HTTP status distribution, and DB locking under load.
Runs repeated benchmark iterations (default N=5) with separate warmup and multi-config SQLite contention analysis.

NOTE: All figures are measured on local Windows development machine.
They are NOT production SLA numbers.
"""

import os
import sys
import time
import uuid
import asyncio
import argparse
import sqlite3
import tempfile
import threading
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

try:
    import httpx
except ImportError:
    try:
        import httpx2 as httpx
    except ImportError:
        print("httpx is required.")
        sys.exit(1)


def percentile(data: List[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_data) - 1)
    d = k - f
    return sorted_data[f] + d * (sorted_data[c] - sorted_data[f])


class BenchmarkRunner:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def scenario_read_heavy(self, total_requests: int = 150, concurrency: int = 15) -> Dict[str, Any]:
        """Scenario 1: Read-heavy burst of GET /api/tickets?view=triage."""
        latencies: List[float] = []
        statuses: Dict[int, int] = {}
        locked_errors = 0
        sem = asyncio.Semaphore(concurrency)

        user_ids = ["USR-101", "USR-102", "USR-103", "USR-104"]

        async def worker(req_idx: int):
            nonlocal locked_errors
            user_id = user_ids[req_idx % len(user_ids)]
            async with sem:
                async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
                    t0 = time.perf_counter()
                    try:
                        resp = await client.get("/api/tickets?view=triage", headers={"X-User-Id": user_id})
                        elapsed = (time.perf_counter() - t0) * 1000.0
                        latencies.append(elapsed)
                        statuses[resp.status_code] = statuses.get(resp.status_code, 0) + 1
                        if "database is locked" in resp.text:
                            locked_errors += 1
                    except Exception as e:
                        elapsed = (time.perf_counter() - t0) * 1000.0
                        latencies.append(elapsed)
                        statuses[599] = statuses.get(599, 0) + 1
                        if "locked" in str(e).lower():
                            locked_errors += 1

        tasks = [asyncio.create_task(worker(i)) for i in range(total_requests)]
        await asyncio.gather(*tasks)

        return {
            "name": "Scenario 1: Read-Heavy Triage (GET /api/tickets?view=triage)",
            "total": len(latencies),
            "statuses": statuses,
            "latencies": latencies,
            "locked_errors": locked_errors
        }

    async def scenario_duration_load(
        self,
        duration_seconds: float,
        concurrency: int = 10,
        workers: int = 10
    ) -> Dict[str, Any]:
        """Runs continuous triage queue requests for specified duration."""
        latencies: List[float] = []
        statuses: Dict[int, int] = {}
        locked_errors = 0
        sem = asyncio.Semaphore(concurrency)
        user_ids = ["USR-101", "USR-102", "USR-103", "USR-104"]
        end_time = time.monotonic() + duration_seconds

        async def worker(worker_idx: int):
            nonlocal locked_errors
            user_id = user_ids[worker_idx % len(user_ids)]
            async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
                while time.monotonic() < end_time:
                    async with sem:
                        t0 = time.perf_counter()
                        try:
                            resp = await client.get("/api/tickets?view=triage", headers={"X-User-Id": user_id})
                            elapsed = (time.perf_counter() - t0) * 1000.0
                            latencies.append(elapsed)
                            statuses[resp.status_code] = statuses.get(resp.status_code, 0) + 1
                            if "database is locked" in resp.text:
                                locked_errors += 1
                        except Exception as e:
                            elapsed = (time.perf_counter() - t0) * 1000.0
                            latencies.append(elapsed)
                            statuses[599] = statuses.get(599, 0) + 1
                            if "locked" in str(e).lower():
                                locked_errors += 1

        tasks = [asyncio.create_task(worker(i)) for i in range(workers)]
        await asyncio.gather(*tasks)

        return {
            "name": f"Duration Load ({duration_seconds}s, concurrency={concurrency})",
            "total": len(latencies),
            "statuses": statuses,
            "latencies": latencies,
            "locked_errors": locked_errors
        }

    async def scenario_mixed_read_write(self, iterations: int = 30, concurrency: int = 10) -> Dict[str, Any]:
        """Scenario 2: Concurrent ticket creations, claims/assignments, and queue triage reads."""
        latencies: List[float] = []
        statuses: Dict[int, int] = {}
        locked_errors = 0
        sem = asyncio.Semaphore(concurrency)

        async def worker(idx: int):
            nonlocal locked_errors
            async with sem:
                async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
                    now = datetime.now(timezone.utc)
                    payload = {
                        "agency_id": "AGY-001",
                        "tboh_id": f"TBOH-LOAD-{idx}",
                        "title": f"Load Benchmark Ticket {idx}",
                        "description": "Stress testing concurrent read write ticket flows",
                        "priority": "High" if idx % 2 == 0 else "Medium",
                        "check_in_date": (now + timedelta(days=3)).isoformat(),
                        "lcd_date": (now + timedelta(hours=12)).isoformat(),
                        "first_message": "Automated benchmark creation message"
                    }
                    t0 = time.perf_counter()
                    try:
                        create_resp = await client.post(
                            "/api/tickets",
                            json=payload,
                            headers={"X-User-Id": "USR-201", "Idempotency-Key": f"load-{idx}-{uuid.uuid4()}"}
                        )
                        elapsed = (time.perf_counter() - t0) * 1000.0
                        latencies.append(elapsed)
                        statuses[create_resp.status_code] = statuses.get(create_resp.status_code, 0) + 1

                        ticket_id = None
                        if create_resp.status_code == 201:
                            ticket_id = create_resp.json().get("id")

                        if ticket_id:
                            t1 = time.perf_counter()
                            assign_resp = await client.post(
                                f"/api/tickets/{ticket_id}/assign",
                                json={"assigned_to": "USR-101"},
                                headers={"X-User-Id": "USR-104"}
                            )
                            elapsed_assign = (time.perf_counter() - t1) * 1000.0
                            latencies.append(elapsed_assign)
                            statuses[assign_resp.status_code] = statuses.get(assign_resp.status_code, 0) + 1

                        t2 = time.perf_counter()
                        triage_resp = await client.get("/api/tickets?view=triage", headers={"X-User-Id": "USR-101"})
                        elapsed_triage = (time.perf_counter() - t2) * 1000.0
                        latencies.append(elapsed_triage)
                        statuses[triage_resp.status_code] = statuses.get(triage_resp.status_code, 0) + 1

                    except Exception as e:
                        elapsed = (time.perf_counter() - t0) * 1000.0
                        latencies.append(elapsed)
                        statuses[599] = statuses.get(599, 0) + 1
                        if "locked" in str(e).lower():
                            locked_errors += 1

        tasks = [asyncio.create_task(worker(i)) for i in range(iterations)]
        await asyncio.gather(*tasks)

        return {
            "name": "Scenario 2: Mixed Read/Write Concurrency (POST ticket + POST assign + GET triage)",
            "total": len(latencies),
            "statuses": statuses,
            "latencies": latencies,
            "locked_errors": locked_errors
        }

    async def scenario_export_and_reads(self, export_count: int = 6, read_count: int = 40) -> Dict[str, Any]:
        """Scenario 3: Concurrent CSV export requests alongside queue reads."""
        latencies: List[float] = []
        statuses: Dict[int, int] = {}
        locked_errors = 0

        async def run_export(idx: int):
            nonlocal locked_errors
            async with httpx.AsyncClient(base_url=self.base_url, timeout=45.0) as client:
                t0 = time.perf_counter()
                try:
                    resp = await client.get("/api/export/tickets.csv", headers={"X-User-Id": "USR-104"})
                    elapsed = (time.perf_counter() - t0) * 1000.0
                    latencies.append(elapsed)
                    statuses[resp.status_code] = statuses.get(resp.status_code, 0) + 1
                except Exception as e:
                    elapsed = (time.perf_counter() - t0) * 1000.0
                    latencies.append(elapsed)
                    statuses[599] = statuses.get(599, 0) + 1
                    if "locked" in str(e).lower():
                        locked_errors += 1

        async def run_read(idx: int):
            nonlocal locked_errors
            async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
                t0 = time.perf_counter()
                try:
                    resp = await client.get("/api/tickets?view=triage", headers={"X-User-Id": "USR-101"})
                    elapsed = (time.perf_counter() - t0) * 1000.0
                    latencies.append(elapsed)
                    statuses[resp.status_code] = statuses.get(resp.status_code, 0) + 1
                except Exception as e:
                    elapsed = (time.perf_counter() - t0) * 1000.0
                    latencies.append(elapsed)
                    statuses[599] = statuses.get(599, 0) + 1
                    if "locked" in str(e).lower():
                        locked_errors += 1

        export_tasks = [asyncio.create_task(run_export(i)) for i in range(export_count)]
        read_tasks = [asyncio.create_task(run_read(i)) for i in range(read_count)]

        await asyncio.gather(*(export_tasks + read_tasks))

        return {
            "name": "Scenario 3: Concurrent CSV Exports + Queue Reads (concurrency limiter testing)",
            "total": len(latencies),
            "statuses": statuses,
            "latencies": latencies,
            "locked_errors": locked_errors
        }


def run_sqlite_contention_benchmark(num_threads: int = 8, writes_per_thread: int = 25):
    """
    Lane L3: Standalone SQLite multi-threaded contention benchmark.
    Tests 8 threads x 25 writes (200 writes) across 3 configurations:
      (i)   DELETE journal + busy_timeout=0
      (ii)  DELETE journal + busy_timeout=5000
      (iii) WAL journal + busy_timeout=5000
    """
    print("\n" + "=" * 80)
    print("SQLITE WRITE CONTENTION REPRODUCTION (8 threads x 25 writes = 200 total writes)")
    print("=" * 80)

    configs = [
        ("DELETE", 0, "DELETE mode with zero busy_timeout"),
        ("DELETE", 5000, "DELETE mode with 5000ms busy_timeout"),
        ("WAL", 5000, "WAL mode with 5000ms busy_timeout")
    ]

    for jmode, btimeout, desc in configs:
        temp_db_fd, temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(temp_db_fd)
        try:
            con = sqlite3.connect(temp_db_path)
            cur = con.cursor()
            cur.execute(f"PRAGMA journal_mode={jmode}")
            cur.execute(f"PRAGMA busy_timeout={btimeout}")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("CREATE TABLE contention_bench (id INTEGER PRIMARY KEY, thread_id INT, val INT)")
            con.commit()
            con.close()

            locked_errors = 0
            success_commits = 0
            lock = threading.Lock()

            def writer_task(tid: int):
                nonlocal locked_errors, success_commits
                c = sqlite3.connect(temp_db_path, timeout=(btimeout / 1000.0))
                try:
                    c.execute(f"PRAGMA busy_timeout={btimeout}")
                except sqlite3.OperationalError:
                    pass
                for w in range(writes_per_thread):
                    try:
                        c.execute("INSERT INTO contention_bench (thread_id, val) VALUES (?, ?)", (tid, w))
                        c.commit()
                        with lock:
                            success_commits += 1
                    except sqlite3.OperationalError as exc:
                        if "locked" in str(exc).lower():
                            with lock:
                                locked_errors += 1
                c.close()

            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = [executor.submit(writer_task, t) for t in range(num_threads)]
                for f in futures:
                    f.result()

            print(f"[{desc}]")
            print(f"  Successful Commits: {success_commits} / {num_threads * writes_per_thread}")
            print(f"  'Database is locked' Errors: {locked_errors}")
        finally:
            try:
                os.remove(temp_db_path)
                for ext in ["-wal", "-shm"]:
                    p = temp_db_path + ext
                    if os.path.exists(p):
                        os.remove(p)
            except Exception:
                pass


def compute_repeated_scenario_metrics(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    import statistics
    p50_list = [percentile(r["latencies"], 50) for r in runs]
    p95_list = [percentile(r["latencies"], 95) for r in runs]
    p99_list = [percentile(r["latencies"], 99) for r in runs]
    all_lats = [lat for r in runs for lat in r["latencies"]]

    combined_statuses: Dict[int, int] = {}
    total_locked = 0
    for r in runs:
        total_locked += r.get("locked_errors", 0)
        for code, count in r.get("statuses", {}).items():
            combined_statuses[code] = combined_statuses.get(code, 0) + count

    return {
        "runs_count": len(runs),
        "median_p50": statistics.median(p50_list) if p50_list else 0.0,
        "median_p95": statistics.median(p95_list) if p95_list else 0.0,
        "median_p99": statistics.median(p99_list) if p99_list else 0.0,
        "min_lat": min(all_lats) if all_lats else 0.0,
        "max_lat": max(all_lats) if all_lats else 0.0,
        "p50_min_max": (min(p50_list), max(p50_list)) if p50_list else (0.0, 0.0),
        "statuses": combined_statuses,
        "total_locked_errors": total_locked
    }


def seed_tickets_if_requested(tickets_target: int, db_url: Optional[str] = None):
    url = db_url or os.getenv("DATABASE_URL")
    if not url:
        return
    try:
        from sqlalchemy import create_engine
        engine = create_engine(url)
        with engine.connect() as conn:
            if url.startswith("postgresql") or url.startswith("postgres"):
                from scripts.bench_scale import fast_seed_postgres
                fast_seed_postgres(conn, tickets_target)
    except Exception as exc:
        print(f"Notice: Seeding {tickets_target} tickets skipped or encountered notice: {exc}")


async def main():
    import json
    parser = argparse.ArgumentParser(description="Run OpsDesk synthetic load test with N repeats or continuous duration")
    parser.add_argument("--base-url", default=os.getenv("API_BASE_URL", "http://127.0.0.1:8000"), help="Base URL of OpsDesk API")
    parser.add_argument("--repeat", type=int, default=5, help="Number of benchmark iterations when duration not set (default: 5)")
    parser.add_argument("--db-path", default=None, help="Path to database currently backing server")
    parser.add_argument("--tickets", type=int, default=None, help="Target ticket count in DB before running load test")
    parser.add_argument("--duration", type=float, default=None, help="Duration in seconds to run load test continuously")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrency limit for requests (default: 10)")
    parser.add_argument("--workers", type=int, default=None, help="Number of worker tasks (defaults to concurrency)")
    parser.add_argument("--json", dest="json_path", default=None, help="Path to write JSON results")
    parser.add_argument("--assert-p95-ms", type=float, default=None, help="Assert p95 latency <= threshold")
    parser.add_argument("--assert-error-rate", type=float, default=None, help="Assert error rate <= threshold (e.g. 0.01 for 1 percent)")
    args = parser.parse_args()

    num_workers = args.workers if args.workers is not None else args.concurrency
    runner = BenchmarkRunner(base_url=args.base_url)

    # Seed if requested
    if args.tickets:
        seed_tickets_if_requested(args.tickets, db_url=args.db_path)

    # Verify server connectivity
    async with httpx.AsyncClient(base_url=args.base_url, timeout=5.0) as client:
        try:
            r = await client.get("/ready")
            if r.status_code != 200:
                r = await client.get("/health")
        except Exception:
            try:
                r = await client.get("/health")
            except Exception as e:
                print(f"Error connecting to server at {args.base_url}: {e}")
                sys.exit(1)

    rate_limit_env = os.environ.get("RATE_LIMIT_PER_MINUTE", "120 (default)")
    db_display = args.db_path or os.environ.get("DATABASE_URL", "sqlite:///./opsdesk.db")

    # If duration-based load test was requested
    if args.duration is not None and args.duration > 0:
        print("=" * 80)
        print(f"OPSDESK DURATION LOAD TEST ({args.duration}s, concurrency={args.concurrency}, workers={num_workers})")
        print(f"Target URL:                 {args.base_url}")
        print(f"Database Path / URL:        {db_display}")
        print(f"RATE_LIMIT_PER_MINUTE Env:  {rate_limit_env}")
        print("=" * 80)

        res = await runner.scenario_duration_load(
            duration_seconds=args.duration,
            concurrency=args.concurrency,
            workers=num_workers
        )

        lats = res["latencies"]
        total = res["total"]
        statuses = res["statuses"]
        p50 = percentile(lats, 50)
        p95 = percentile(lats, 95)
        p99 = percentile(lats, 99)
        min_lat = min(lats) if lats else 0.0
        max_lat = max(lats) if lats else 0.0

        errors = sum(count for code, count in statuses.items() if code >= 400)
        error_rate = (errors / total) if total > 0 else 0.0
        rps = (total / args.duration) if args.duration > 0 else 0.0

        print(f"\n--- Results Summary ---")
        print(f"Total Requests:         {total} ({rps:.1f} req/s)")
        print(f"Status Breakdown:       {statuses}")
        print(f"Error Rate:             {error_rate * 100:.2f}% ({errors} errors)")
        print(f"DB 'locked' errors:     {res['locked_errors']}")
        print(f"p50 Latency:            {p50:.2f} ms")
        print(f"p95 Latency:            {p95:.2f} ms")
        print(f"p99 Latency:            {p99:.2f} ms")
        print(f"Min / Max:              {min_lat:.2f} ms / {max_lat:.2f} ms")

        metrics_out = {
            "total_requests": total,
            "requests_per_second": rps,
            "error_rate": error_rate,
            "p50_ms": p50,
            "p95_ms": p95,
            "p99_ms": p99,
            "min_ms": min_lat,
            "max_ms": max_lat,
            "duration_seconds": args.duration,
            "concurrency": args.concurrency,
            "workers": num_workers,
            "statuses": statuses
        }

        if args.json_path:
            os.makedirs(os.path.dirname(args.json_path) or ".", exist_ok=True)
            with open(args.json_path, "w", encoding="utf-8") as f:
                json.dump(metrics_out, f, indent=2)
            print(f"Wrote JSON metrics to {args.json_path}")

        failed = False
        if args.assert_p95_ms is not None and p95 > args.assert_p95_ms:
            print(f"ASSERTION FAILED: p95 latency {p95:.2f}ms exceeds target {args.assert_p95_ms}ms")
            failed = True
        if args.assert_error_rate is not None and error_rate > args.assert_error_rate:
            print(f"ASSERTION FAILED: error rate {error_rate * 100:.2f}% exceeds target {args.assert_error_rate * 100:.2f}%")
            failed = True

        if failed:
            sys.exit(1)
        return

    # Standard repeated scenario mode
    print("=" * 80)
    print(f"OPSDESK MULTI-RUN LOAD & CONCURRENCY BENCHMARK (N={args.repeat})")
    print(f"Target URL:                 {args.base_url}")
    print(f"Database Path / URL:        {db_display}")
    print(f"RATE_LIMIT_PER_MINUTE Env:  {rate_limit_env}")
    print(f"Iterations (N):             {args.repeat}")
    print("=" * 80)

    # 1. Warmup round (isolated from metrics)
    print("\nExecuting warmup round (10 requests)...")
    await runner.scenario_read_heavy(total_requests=10, concurrency=2)
    print("Warmup complete. Starting benchmark runs...")

    s1_runs: List[Dict[str, Any]] = []
    s2_runs: List[Dict[str, Any]] = []
    s3_runs: List[Dict[str, Any]] = []

    for r_idx in range(args.repeat):
        print(f"\n--- Iteration {r_idx + 1} / {args.repeat} ---")
        s1 = await runner.scenario_read_heavy(total_requests=150, concurrency=args.concurrency)
        s2 = await runner.scenario_mixed_read_write(iterations=30, concurrency=args.concurrency)
        s3 = await runner.scenario_export_and_reads(export_count=6, read_count=40)
        s1_runs.append(s1)
        s2_runs.append(s2)
        s3_runs.append(s3)

    # Compute aggregates across runs
    m1 = compute_repeated_scenario_metrics(s1_runs)
    m2 = compute_repeated_scenario_metrics(s2_runs)
    m3 = compute_repeated_scenario_metrics(s3_runs)

    print("\n" + "=" * 80)
    print(f"REPEATED BENCHMARK AGGREGATE RESULTS (N={args.repeat})")
    print("=" * 80)

    print(f"\n--- Scenario 1: Read-Heavy Triage (150 reqs, concurrency={args.concurrency}) ---")
    print(f"Status Breakdown:       {m1['statuses']}")
    print(f"DB 'locked' errors:     {m1['total_locked_errors']}")
    print(f"Median p50 Latency:     {m1['median_p50']:.2f} ms")
    print(f"Median p95 Latency:     {m1['median_p95']:.2f} ms")
    print(f"Median p99 Latency:     {m1['median_p99']:.2f} ms")

    print(f"\n--- Scenario 2: Mixed Read/Write Concurrency ---")
    print(f"Status Breakdown:       {m2['statuses']}")
    print(f"DB 'locked' errors:     {m2['total_locked_errors']}")
    print(f"Median p50 Latency:     {m2['median_p50']:.2f} ms")
    print(f"Median p95 Latency:     {m2['median_p95']:.2f} ms")

    print(f"\n--- Scenario 3: Concurrent CSV Exports + Queue Reads ---")
    print(f"Status Breakdown:       {m3['statuses']}")
    print(f"DB 'locked' errors:     {m3['total_locked_errors']}")

    if args.json_path:
        os.makedirs(os.path.dirname(args.json_path) or ".", exist_ok=True)
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump({"s1": m1, "s2": m2, "s3": m3}, f, indent=2)

    # Run standalone SQLite contention benchmark
    if not (args.db_path and "postgres" in args.db_path):
        run_sqlite_contention_benchmark(num_threads=8, writes_per_thread=25)


if __name__ == "__main__":
    asyncio.run(main())

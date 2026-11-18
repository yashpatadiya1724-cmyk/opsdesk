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
from typing import List, Dict, Any
from datetime import datetime, timedelta
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
        latencies_all: List[float] = []
        latencies_2xx: List[float] = []
        statuses: Dict[int, int] = {}
        locked_errors = 0
        sem = asyncio.Semaphore(concurrency)

        user_ids = ["USR-101", "USR-102", "USR-103", "USR-104"]
        t_start = time.time()

        async def worker(req_idx: int):
            nonlocal locked_errors
            user_id = user_ids[req_idx % len(user_ids)]
            async with sem:
                async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
                    t0 = time.perf_counter()
                    st = 599
                    try:
                        resp = await client.get("/api/tickets?view=triage", headers={"X-User-Id": user_id})
                        elapsed = (time.perf_counter() - t0) * 1000.0
                        st = resp.status_code
                        latencies_all.append(elapsed)
                        if 200 <= st < 300:
                            latencies_2xx.append(elapsed)
                        statuses[st] = statuses.get(st, 0) + 1
                        if "database is locked" in resp.text:
                            locked_errors += 1
                    except Exception as e:
                        elapsed = (time.perf_counter() - t0) * 1000.0
                        latencies_all.append(elapsed)
                        statuses[599] = statuses.get(599, 0) + 1
                        if "locked" in str(e).lower():
                            locked_errors += 1

        tasks = [asyncio.create_task(worker(i)) for i in range(total_requests)]
        await asyncio.gather(*tasks)
        duration = time.time() - t_start

        return {
            "name": "Scenario 1: Read-Heavy Triage (GET /api/tickets?view=triage)",
            "total": len(latencies_all),
            "duration": duration,
            "statuses": statuses,
            "latencies_all": latencies_all,
            "latencies_2xx": latencies_2xx,
            "locked_errors": locked_errors
        }

    async def scenario_mixed_read_write(self, iterations: int = 30, concurrency: int = 10) -> Dict[str, Any]:
        """Scenario 2: Concurrent ticket creations, claims/assignments, and queue triage reads."""
        latencies_all: List[float] = []
        latencies_2xx: List[float] = []
        statuses: Dict[int, int] = {}
        locked_errors = 0
        sem = asyncio.Semaphore(concurrency)
        t_start = time.time()

        async def worker(idx: int):
            nonlocal locked_errors
            async with sem:
                async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
                    now = datetime.utcnow()
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
                    st = 599
                    ticket_id = None
                    try:
                        create_resp = await client.post(
                            "/api/tickets",
                            json=payload,
                            headers={"X-User-Id": "USR-201", "Idempotency-Key": f"load-{idx}-{uuid.uuid4()}"}
                        )
                        elapsed = (time.perf_counter() - t0) * 1000.0
                        st = create_resp.status_code
                        latencies_all.append(elapsed)
                        if 200 <= st < 300:
                            latencies_2xx.append(elapsed)
                        statuses[st] = statuses.get(st, 0) + 1

                        if create_resp.status_code in (200, 201):
                            data = create_resp.json()
                            ticket_id = data.get("ticket", {}).get("id") or data.get("id")
                    except Exception as e:
                        elapsed = (time.perf_counter() - t0) * 1000.0
                        latencies_all.append(elapsed)
                        statuses[599] = statuses.get(599, 0) + 1
                        if "locked" in str(e).lower():
                            locked_errors += 1

                    if ticket_id:
                        t1 = time.perf_counter()
                        try:
                            assign_resp = await client.post(
                                f"/api/tickets/{ticket_id}/assign",
                                json={"agent_id": "USR-101"},
                                headers={"X-User-Id": "USR-102"}
                            )
                            elapsed1 = (time.perf_counter() - t1) * 1000.0
                            ast = assign_resp.status_code
                            latencies_all.append(elapsed1)
                            if 200 <= ast < 300:
                                latencies_2xx.append(elapsed1)
                            statuses[ast] = statuses.get(ast, 0) + 1
                        except Exception as e:
                            elapsed1 = (time.perf_counter() - t1) * 1000.0
                            latencies_all.append(elapsed1)
                            statuses[599] = statuses.get(599, 0) + 1
                            if "locked" in str(e).lower():
                                locked_errors += 1

                    t2 = time.perf_counter()
                    try:
                        triage_resp = await client.get("/api/tickets?view=triage", headers={"X-User-Id": "USR-101"})
                        elapsed2 = (time.perf_counter() - t2) * 1000.0
                        tst = triage_resp.status_code
                        latencies_all.append(elapsed2)
                        if 200 <= tst < 300:
                            latencies_2xx.append(elapsed2)
                        statuses[tst] = statuses.get(tst, 0) + 1
                    except Exception as e:
                        elapsed2 = (time.perf_counter() - t2) * 1000.0
                        latencies_all.append(elapsed2)
                        statuses[599] = statuses.get(599, 0) + 1
                        if "locked" in str(e).lower():
                            locked_errors += 1

        tasks = [asyncio.create_task(worker(i)) for i in range(iterations)]
        await asyncio.gather(*tasks)
        duration = time.time() - t_start

        return {
            "name": "Scenario 2: Mixed Read/Write Concurrency",
            "total": len(latencies_all),
            "duration": duration,
            "statuses": statuses,
            "latencies_all": latencies_all,
            "latencies_2xx": latencies_2xx,
            "locked_errors": locked_errors
        }

    async def scenario_export_and_reads(self, export_count: int = 6, read_count: int = 40) -> Dict[str, Any]:
        """Scenario 3: Concurrent CSV exports (bounded by limiter) alongside queue triage reads."""
        latencies_all: List[float] = []
        latencies_2xx: List[float] = []
        statuses: Dict[int, int] = {}
        locked_errors = 0
        t_start = time.time()

        async def run_export(idx: int):
            nonlocal locked_errors
            async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
                t0 = time.perf_counter()
                try:
                    resp = await client.get("/api/export/tickets.csv", headers={"X-User-Id": "USR-101"})
                    elapsed = (time.perf_counter() - t0) * 1000.0
                    st = resp.status_code
                    latencies_all.append(elapsed)
                    if 200 <= st < 300:
                        latencies_2xx.append(elapsed)
                    statuses[st] = statuses.get(st, 0) + 1
                except Exception as e:
                    elapsed = (time.perf_counter() - t0) * 1000.0
                    latencies_all.append(elapsed)
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
                    st = resp.status_code
                    latencies_all.append(elapsed)
                    if 200 <= st < 300:
                        latencies_2xx.append(elapsed)
                    statuses[st] = statuses.get(st, 0) + 1
                except Exception as e:
                    elapsed = (time.perf_counter() - t0) * 1000.0
                    latencies_all.append(elapsed)
                    statuses[599] = statuses.get(599, 0) + 1
                    if "locked" in str(e).lower():
                        locked_errors += 1

        export_tasks = [asyncio.create_task(run_export(i)) for i in range(export_count)]
        read_tasks = [asyncio.create_task(run_read(i)) for i in range(read_count)]

        await asyncio.gather(*(export_tasks + read_tasks))
        duration = time.time() - t_start

        return {
            "name": "Scenario 3: Concurrent CSV Exports + Queue Reads",
            "total": len(latencies_all),
            "duration": duration,
            "statuses": statuses,
            "latencies_all": latencies_all,
            "latencies_2xx": latencies_2xx,
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
            cur.execute("CREATE TABLE contention_bench (id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id INT, val INT)")
            con.commit()
            con.close()

            locked_errors = 0
            success_commits = 0
            lock = threading.Lock()

            def writer_task(tid: int):
                nonlocal locked_errors, success_commits
                c = sqlite3.connect(temp_db_path)
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
    
    # 2xx-exclusive latencies
    p50_2xx_list = [percentile(r["latencies_2xx"], 50) for r in runs if r.get("latencies_2xx")]
    p95_2xx_list = [percentile(r["latencies_2xx"], 95) for r in runs if r.get("latencies_2xx")]
    p99_2xx_list = [percentile(r["latencies_2xx"], 99) for r in runs if r.get("latencies_2xx")]
    all_2xx_lats = [lat for r in runs for lat in r.get("latencies_2xx", [])]

    # All-response latencies (including fast 503s)
    p50_all_list = [percentile(r["latencies_all"], 50) for r in runs if r.get("latencies_all")]
    all_lats = [lat for r in runs for lat in r.get("latencies_all", [])]

    combined_statuses: Dict[int, int] = {}
    total_locked = sum(r.get("locked_errors", 0) for r in runs)
    total_duration = sum(r.get("duration", 0.0) for r in runs)
    total_requests = 0

    for r in runs:
        for code, count in r.get("statuses", {}).items():
            combined_statuses[code] = combined_statuses.get(code, 0) + count
            total_requests += count

    count_2xx = sum(count for code, count in combined_statuses.items() if 200 <= code < 300)
    count_503 = combined_statuses.get(503, 0)
    count_599 = combined_statuses.get(599, 0)
    count_429 = combined_statuses.get(429, 0)
    count_409 = combined_statuses.get(409, 0)

    goodput_2xx_s = count_2xx / total_duration if total_duration > 0 else 0.0
    shed_rate_503_pct = (count_503 / total_requests * 100.0) if total_requests > 0 else 0.0
    error_rate_599_pct = (count_599 / total_requests * 100.0) if total_requests > 0 else 0.0

    return {
        "runs_count": len(runs),
        "total_requests": total_requests,
        "count_2xx": count_2xx,
        "goodput_2xx_s": goodput_2xx_s,
        "count_503": count_503,
        "count_599": count_599,
        "count_429": count_429,
        "count_409": count_409,
        "shed_rate_503_pct": shed_rate_503_pct,
        "error_rate_599_pct": error_rate_599_pct,
        "median_p50_2xx": statistics.median(p50_2xx_list) if p50_2xx_list else 0.0,
        "median_p95_2xx": statistics.median(p95_2xx_list) if p95_2xx_list else 0.0,
        "median_p99_2xx": statistics.median(p99_2xx_list) if p99_2xx_list else 0.0,
        "p50_2xx_min_max": (min(p50_2xx_list), max(p50_2xx_list)) if p50_2xx_list else (0.0, 0.0),
        "median_p50_all": statistics.median(p50_all_list) if p50_all_list else 0.0,
        "min_lat": min(all_lats) if all_lats else 0.0,
        "max_lat": max(all_lats) if all_lats else 0.0,
        "statuses": combined_statuses,
        "total_locked_errors": total_locked
    }


async def main():
    parser = argparse.ArgumentParser(description="Run OpsDesk synthetic load test with N repeats")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Base URL of OpsDesk API")
    parser.add_argument("--repeat", type=int, default=5, help="Number of benchmark iterations (default: 5)")
    parser.add_argument("--db-path", default=None, help="Path to database currently backing server")
    args = parser.parse_args()

    runner = BenchmarkRunner(base_url=args.base_url)

    # Verify server connectivity
    try:
        async with httpx.AsyncClient(base_url=args.base_url, timeout=5.0) as client:
            resp = await client.get("/health")
            if resp.status_code != 200:
                print(f"Server health check failed: status {resp.status_code}")
                sys.exit(1)
    except Exception as e:
        print(f"Error connecting to server at {args.base_url}: {e}")
        sys.exit(1)

    rate_limit_env = os.environ.get("RATE_LIMIT_PER_MINUTE", "120 (default)")
    db_display = args.db_path or os.environ.get("DATABASE_URL", "sqlite:///./opsdesk.db")

    print("=" * 130)
    print("OPSDESK MULTI-RUN LOAD & CONCURRENCY BENCHMARK (N=5)")
    print(f"Target URL:                 {args.base_url}")
    print(f"Database Path / URL:        {db_display}")
    print(f"RATE_LIMIT_PER_MINUTE Env:  {rate_limit_env}")
    print(f"Iterations (N):             {args.repeat}")
    print("Machine:                    Local Windows development machine (not production SLA)")
    print("=" * 130)

    # 1. Warmup round (isolated from metrics)
    print("\nExecuting warmup round (10 requests)...")
    await runner.scenario_read_heavy(total_requests=10, concurrency=2)
    print("Warmup complete. Starting benchmark runs...")

    s1_runs: List[Dict[str, Any]] = []
    s2_runs: List[Dict[str, Any]] = []
    s3_runs: List[Dict[str, Any]] = []

    for r_idx in range(args.repeat):
        print(f"\n--- Iteration {r_idx + 1} / {args.repeat} ---")
        s1 = await runner.scenario_read_heavy(total_requests=150, concurrency=15)
        s2 = await runner.scenario_mixed_read_write(iterations=30, concurrency=10)
        s3 = await runner.scenario_export_and_reads(export_count=6, read_count=40)
        s1_runs.append(s1)
        s2_runs.append(s2)
        s3_runs.append(s3)

    # Compute aggregates across runs
    m1 = compute_repeated_scenario_metrics(s1_runs)
    m2 = compute_repeated_scenario_metrics(s2_runs)
    m3 = compute_repeated_scenario_metrics(s3_runs)

    print("\n" + "=" * 160)
    print(f"{'Scenario':<40} | {'Total':<6} | {'2xx':<6} | {'Goodput':<12} | {'Shed 503%':<9} | {'Err 599%':<8} | {'429/409':<7} | {'2xx p50 (ms)':<16} | {'2xx p95 (ms)':<16} | {'2xx p99 (ms)':<16} | {'All p50 (ms)':<16}")
    print("-" * 160)
    scenarios = [
        ("Scenario 1: Read-Heavy Triage (150 reqs)", m1),
        ("Scenario 2: Mixed Read/Write Concurrency", m2),
        ("Scenario 3: Concurrent CSV Exports + Reads", m3),
    ]
    for s_name, m in scenarios:
        gp_str = f"{m['goodput_2xx_s']:.1f}/s"
        shed_str = f"{m['shed_rate_503_pct']:.1f}%"
        err_str = f"{m['error_rate_599_pct']:.1f}%"
        c_str = f"{m['count_429']}/{m['count_409']}"
        p50_2xx = f"{m['median_p50_2xx']:.1f} ms"
        p95_2xx = f"{m['median_p95_2xx']:.1f} ms"
        p99_2xx = f"{m['median_p99_2xx']:.1f} ms"
        p50_all = f"{m['median_p50_all']:.1f} ms"
        print(f"{s_name:<40} | {m['total_requests']:<6} | {m['count_2xx']:<6} | {gp_str:<12} | {shed_str:<9} | {err_str:<8} | {c_str:<7} | {p50_2xx:<16} | {p95_2xx:<16} | {p99_2xx:<16} | {p50_all:<16}")
    print("=" * 160)

    # Detailed status prints
    for s_name, m in scenarios:
        print(f"\n[{s_name}]")
        print(f"  Statuses:           {m['statuses']}")
        print(f"  2xx p50 Range:      {m['p50_2xx_min_max'][0]:.2f}ms - {m['p50_2xx_min_max'][1]:.2f}ms")
        print(f"  All p50 (incl 503): {m['median_p50_all']:.2f} ms")
        print(f"  Locked Errors:      {m['total_locked_errors']}")

    # Run standalone SQLite contention benchmark
    run_sqlite_contention_benchmark(num_threads=8, writes_per_thread=25)


if __name__ == "__main__":
    asyncio.run(main())

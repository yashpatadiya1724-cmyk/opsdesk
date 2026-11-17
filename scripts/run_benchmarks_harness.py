import os
import sys
import time
import uuid
import random
import asyncio
import statistics
import subprocess
import tempfile
import shutil
from typing import List, Dict, Any
from datetime import datetime, timedelta
try:
    import httpx
except ImportError:
    import httpx2 as httpx

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PYTHON_EXE = sys.executable

def percentile(data: List[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_data) - 1)
    d = k - f
    return sorted_data[f] + d * (sorted_data[c] - sorted_data[f])

async def run_closed_loop_test(base_url: str, users: int, duration_sec: int) -> Dict[str, Any]:
    latencies: List[float] = []
    statuses: Dict[int, int] = {}
    locked_errors = 0
    lock = asyncio.Lock()

    # Pre-fetch candidate ticket IDs
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        try:
            res = await client.get("/api/tickets?view=triage&limit=50", headers={"X-User-Id": "USR-101"})
            ticket_ids = [t["id"] for t in res.json().get("tickets", [])] if res.status_code == 200 else []
        except Exception:
            ticket_ids = []
    if not ticket_ids:
        ticket_ids = ["TCK-1001", "TCK-1002", "TCK-1004", "TCK-1005", "TCK-1006"]

    start_time = time.time()
    end_time = start_time + duration_sec

    async def virtual_user(uid_idx: int):
        nonlocal locked_errors
        user_id = f"USR-{101 + (uid_idx % 4)}"
        req_count = 0
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            while time.time() < end_time:
                req_count += 1
                r_type = random.random()
                t0 = time.perf_counter()
                try:
                    if r_type < 0.70:
                        # 70% GET /api/tickets?view=triage
                        resp = await client.get("/api/tickets?view=triage", headers={"X-User-Id": user_id})
                    elif r_type < 0.90:
                        # 20% GET /api/tickets/{id}
                        tid = random.choice(ticket_ids)
                        resp = await client.get(f"/api/tickets/{tid}", headers={"X-User-Id": user_id})
                    elif r_type < 0.95:
                        # 5% POST /api/tickets (Idempotency-Key)
                        now = datetime.utcnow()
                        payload = {
                            "agency_id": "AGY-001",
                            "tboh_id": f"TBOH-LOAD-{uid_idx}-{req_count}-{int(time.time()*1000)}",
                            "title": f"Load Benchmark Ticket {uid_idx}-{req_count}",
                            "description": "Stress testing concurrent ticket creation",
                            "priority": "Medium",
                            "check_in_date": (now + timedelta(days=5)).isoformat(),
                            "first_message": "Automated benchmark ticket creation"
                        }
                        resp = await client.post(
                            "/api/tickets",
                            json=payload,
                            headers={"X-User-Id": user_id, "Idempotency-Key": f"key-{uid_idx}-{req_count}-{uuid.uuid4()}"}
                        )
                    else:
                        # 5% POST /api/tickets/{id}/assign
                        tid = random.choice(ticket_ids)
                        resp = await client.post(
                            f"/api/tickets/{tid}/assign",
                            json={"agent_id": "USR-102"},
                            headers={"X-User-Id": "USR-101"}
                        )
                    elapsed = (time.perf_counter() - t0) * 1000.0
                    async with lock:
                        latencies.append(elapsed)
                        statuses[resp.status_code] = statuses.get(resp.status_code, 0) + 1
                        if "database is locked" in resp.text:
                            locked_errors += 1
                except Exception as exc:
                    elapsed = (time.perf_counter() - t0) * 1000.0
                    async with lock:
                        latencies.append(elapsed)
                        statuses[599] = statuses.get(599, 0) + 1
                        if "locked" in str(exc).lower():
                            locked_errors += 1

    tasks = [asyncio.create_task(virtual_user(i)) for i in range(users)]
    await asyncio.gather(*tasks)

    actual_duration = time.time() - start_time
    rps = len(latencies) / actual_duration if actual_duration > 0 else 0.0

    return {
        "users": users,
        "duration": actual_duration,
        "total_requests": len(latencies),
        "rps": rps,
        "p50": percentile(latencies, 50),
        "p95": percentile(latencies, 95),
        "p99": percentile(latencies, 99),
        "statuses": statuses,
        "locked_errors": locked_errors,
        "latencies": latencies
    }

async def benchmark_suite(base_url: str, levels: List[int], duration_sec: int, repeats: int):
    results_by_level = {}
    for users in levels:
        print(f"\n>>> Running Concurrency Level: {users} users (Duration: {duration_sec}s, Repeats: {repeats}) <<<")
        runs = []
        for r in range(repeats):
            print(f"  Iteration {r + 1}/{repeats} ...", end="", flush=True)
            res = await run_closed_loop_test(base_url, users, duration_sec)
            runs.append(res)
            print(f" done (RPS: {res['rps']:.1f}, p50: {res['p50']:.1f}ms, p95: {res['p95']:.1f}ms, status: {res['statuses']})")
            await asyncio.sleep(1)

        # Compute median run by RPS
        sorted_runs = sorted(runs, key=lambda x: x["rps"])
        med_run = sorted_runs[len(runs) // 2]

        rps_list = [r["rps"] for r in runs]
        p50_list = [r["p50"] for r in runs]
        p95_list = [r["p95"] for r in runs]
        p99_list = [r["p99"] for r in runs]

        # Aggregate statuses across all repeats
        combined_statuses: Dict[int, int] = {}
        total_locked = 0
        for r in runs:
            total_locked += r["locked_errors"]
            for code, count in r["statuses"].items():
                combined_statuses[code] = combined_statuses.get(code, 0) + count

        results_by_level[users] = {
            "median_rps": statistics.median(rps_list),
            "min_rps": min(rps_list),
            "max_rps": max(rps_list),
            "median_p50": statistics.median(p50_list),
            "min_p50": min(p50_list),
            "max_p50": max(p50_list),
            "median_p95": statistics.median(p95_list),
            "min_p95": min(p95_list),
            "max_p95": max(p95_list),
            "median_p99": statistics.median(p99_list),
            "min_p99": min(p99_list),
            "max_p99": max(p99_list),
            "combined_statuses": combined_statuses,
            "total_locked": total_locked,
            "raw_runs": runs
        }
    return results_by_level

def main():
    temp_dir = tempfile.mkdtemp()
    temp_db = os.path.join(temp_dir, "perf_test.db")
    temp_log = os.path.join(temp_dir, "server.log")
    port = 8135

    print(f"Creating and seeding test database at {temp_db} with 5000 tickets...")
    env_seed = os.environ.copy()
    env_seed["DATABASE_URL"] = f"sqlite:///{temp_db}"
    env_seed["PYTHONPATH"] = REPO_ROOT

    # Run seed script
    cmd_seed = [PYTHON_EXE, "backend/seed/seed_data.py", "--tickets", "5000", "--reset", "--yes"]
    subprocess.run(cmd_seed, cwd=REPO_ROOT, env=env_seed, check=True)

    # Start uvicorn server with 1 worker
    env_server = os.environ.copy()
    env_server["DATABASE_URL"] = f"sqlite:///{temp_db}"
    env_server["PYTHONPATH"] = REPO_ROOT
    env_server["RATE_LIMIT_PER_MINUTE"] = "100000"  # Prevent loopback throttling during load test

    log_file = open(temp_log, "w", encoding="utf-8")
    server_proc = subprocess.Popen(
        [PYTHON_EXE, "-m", "uvicorn", "backend.app.main:app", "--port", str(port), "--host", "127.0.0.1", "--workers", "1"],
        cwd=REPO_ROOT,
        env=env_server,
        stdout=log_file,
        stderr=log_file
    )

    base_url = f"http://127.0.0.1:{port}"
    print(f"Waiting for server at {base_url} to start...")
    time.sleep(3)

    try:
        # Check server readiness
        for _ in range(15):
            try:
                r = httpx.get(f"{base_url}/health", timeout=2.0)
                if r.status_code == 200:
                    print("Server is healthy and ready!")
                    break
            except Exception:
                time.sleep(1)
        else:
            print("Server failed to respond to /health in 15s")
            sys.exit(1)

        # Run benchmark
        levels = [25, 100, 250]
        duration = 30
        repeats = 3

        print(f"\nStarting closed-loop load test: levels={levels}, duration={duration}s, repeats={repeats}")
        results = asyncio.run(benchmark_suite(base_url, levels, duration, repeats))

        # Check server log for "database is locked"
        log_file.flush()
        log_file.close()
        server_locked_count = 0
        with open(temp_log, "r", encoding="utf-8", errors="ignore") as lf:
            for line in lf:
                if "database is locked" in line.lower():
                    server_locked_count += 1

        print("\n" + "=" * 95)
        print("PERFORMANCE BASELINE RESULTS (5,000 Tickets DB, Closed-Loop Concurrency)")
        print("=" * 95)
        header = f"{'Users':<8} | {'Median RPS':<12} | {'p50 (ms)':<16} | {'p95 (ms)':<16} | {'p99 (ms)':<16} | {'Statuses':<25} | {'DB Locked':<10}"
        print(header)
        print("-" * 95)
        for u in levels:
            data = results[u]
            rps_str = f"{data['median_rps']:.1f} ({data['min_rps']:.1f}-{data['max_rps']:.1f})"
            p50_str = f"{data['median_p50']:.1f} ({data['min_p50']:.1f}-{data['max_p50']:.1f})"
            p95_str = f"{data['median_p95']:.1f} ({data['min_p95']:.1f}-{data['max_p95']:.1f})"
            p99_str = f"{data['median_p99']:.1f} ({data['min_p99']:.1f}-{data['max_p99']:.1f})"
            status_str = str(data['combined_statuses'])
            locked_str = f"{data['total_locked']} (srv:{server_locked_count})"
            print(f"{u:<8} | {rps_str:<12} | {p50_str:<16} | {p95_str:<16} | {p99_str:<16} | {status_str:<25} | {locked_str:<10}")

    finally:
        print("\nStopping uvicorn server...")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except Exception:
            server_proc.kill()
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
        print("Cleanup complete.")

if __name__ == "__main__":
    main()

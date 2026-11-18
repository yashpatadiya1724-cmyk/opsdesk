import os
import sys
import time
import uuid
import random
import asyncio
import argparse
import tempfile
import shutil
import subprocess
from datetime import datetime
from typing import Dict, List

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    import httpx
except ImportError:
    import httpx2 as httpx

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--port", type=int, default=8008)
    parser.add_argument("--duration", type=int, default=90)
    parser.add_argument("--clients", type=int, default=100)
    args = parser.parse_args()

    # 1. Setup isolated temporary DB
    temp_dir = tempfile.mkdtemp(prefix=f"opsdesk_ts_{args.label}_")
    db_path = os.path.join(temp_dir, "perf_timeseries.db")
    pool_samples_file = os.path.join(temp_dir, "pool_samples.txt")

    env = os.environ.copy()
    env["PYTHONPATH"] = REPO_ROOT
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["RATE_LIMIT_PER_MINUTE"] = "1000000" # Limiter off for capacity
    env["POOL_SAMPLES_FILE"] = pool_samples_file
    venv_python = sys.executable

    print("=" * 80)
    print(f"90-SECOND TIME-SERIES LOAD RUN: {args.label}")
    print("=" * 80)

    # Pre-seed temporary database
    print(f"Creating and seeding temporary database: {db_path}...")
    seed_cmd = [
        venv_python, "-c",
        f"import sys; sys.path.insert(0, r'{REPO_ROOT}'); from backend.app.database import engine, Base, SessionLocal; from backend.seed.seed_data import seed_database; Base.metadata.create_all(bind=engine); db = SessionLocal(); seed_database(db); db.close()"
    ]
    subprocess.run(seed_cmd, env=env, check=True)
    print("Database seeded successfully.")

    # Inspect config values to print in header
    from backend.app.database import DB_POOL_SIZE, DB_MAX_OVERFLOW, DB_POOL_TIMEOUT
    in_flight = os.getenv("IN_FLIGHT_CONCURRENCY_LIMIT", "30 (default)")
    max_q = os.getenv("CONCURRENCY_QUEUE_MAX_SIZE", "15 (default)")
    print(f"HEADER: POOL: size={DB_POOL_SIZE}, overflow={DB_MAX_OVERFLOW}, timeout={DB_POOL_TIMEOUT}s")
    print(f"HEADER: ANYIO: thread_limit=40 (default AnyIO CapacityLimiter)")
    print(f"HEADER: CONCURRENCY_LIMITER: in_flight={in_flight}, queue_max={max_q}")
    print(f"HEADER: CLIENT_TIMEOUT: 30.0s")
    print(f"HEADER: LOAD: clients={args.clients}, think_time=0ms (T=0), duration={args.duration}s")
    print(f"HEADER: VARIANT: (a) [normal seed: ~456 unassigned]")
    print("-" * 80)

    # 2. Launch server with pool monitor
    server_script = os.path.join(REPO_ROOT, "scripts", "diag", "run_server_ts.py")
    server_proc = subprocess.Popen(
        [venv_python, server_script, "--port", str(args.port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    base_url = f"http://127.0.0.1:{args.port}"

    # Wait for server ready
    ready = False
    for _ in range(30):
        try:
            r = httpx.get(f"{base_url}/health", timeout=1.0)
            if r.status_code == 200:
                ready = True
                break
        except Exception:
            time.sleep(0.5)

    if not ready:
        server_proc.kill()
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError("Server failed to start on port " + str(args.port))

    print(f"Server is healthy on {base_url}. Commencing 90s load traffic...")

    # Pre-fetch candidate tickets
    try:
        r = httpx.get(f"{base_url}/api/tickets?view=triage&limit=50", headers={"X-User-Id": "USR-101"}, timeout=10.0)
        ticket_ids = [t["id"] for t in r.json().get("tickets", [])] if r.status_code == 200 else []
    except Exception:
        ticket_ids = []
    if not ticket_ids:
        ticket_ids = ["TCK-1001", "TCK-1002", "TCK-1004", "TCK-1005"]

    # Run load loop
    completed_events = [] # (sec_from_start, status_code, latency_ms)
    t0 = time.time()
    end_time = t0 + args.duration

    async def client_worker(idx: int):
        user_id = f"USR-{101 + (idx % 4)}"
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as cl:
            while time.time() < end_time:
                r_type = random.random()
                req_t0 = time.perf_counter()
                st = 599
                try:
                    if r_type < 0.70:
                        resp = await cl.get("/api/tickets?view=triage&limit=25", headers={"X-User-Id": user_id})
                        st = resp.status_code
                    elif r_type < 0.90:
                        t_id = random.choice(ticket_ids)
                        resp = await cl.get(f"/api/tickets/{t_id}", headers={"X-User-Id": user_id})
                        st = resp.status_code
                    elif r_type < 0.95:
                        body = {
                            "title": f"Load ticket {uuid.uuid4().hex[:6]}",
                            "description": "Timeseries benchmark payload",
                            "tboh_id": f"TBOH-{random.randint(10000, 99999)}",
                            "priority": random.choice(["Low", "Medium", "High", "Urgent"]),
                            "check_in_date": "2026-12-15T10:00:00Z",
                            "agency_id": "AGY-001"
                        }
                        headers = {"X-User-Id": user_id, "Idempotency-Key": f"load-{uuid.uuid4().hex}"}
                        resp = await cl.post("/api/tickets", json=body, headers=headers)
                        st = resp.status_code
                    else:
                        t_id = random.choice(ticket_ids)
                        resp = await cl.post(
                            f"/api/tickets/{t_id}/assign",
                            json={"agent_id": "USR-102" if user_id == "USR-101" else "USR-101"},
                            headers={"X-User-Id": user_id}
                        )
                        st = resp.status_code
                except httpx.TimeoutException:
                    st = 599
                except Exception:
                    st = 599
                req_t1 = time.perf_counter()
                now_rel = time.time() - t0
                completed_events.append((now_rel, st, (req_t1 - req_t0) * 1000))

    async def run_all():
        tasks = [asyncio.create_task(client_worker(i)) for i in range(args.clients)]
        await asyncio.gather(*tasks)

    asyncio.run(run_all())

    # Stop server
    server_proc.terminate()
    try:
        server_proc.wait(timeout=5)
    except Exception:
        server_proc.kill()

    # Read pool samples
    pool_by_sec = {}
    if os.path.exists(pool_samples_file):
        with open(pool_samples_file, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 2:
                    try:
                        sec = int(float(parts[0]))
                        checked_out = int(parts[1])
                        pool_by_sec[sec] = checked_out
                    except Exception:
                        pass

    # Bucket per second (1 to 90)
    sec_buckets = {}
    for s in range(1, args.duration + 1):
        sec_buckets[s] = {"2xx": 0, "503": 0, "599": 0, "other": 0}

    for rel_t, st, lat in completed_events:
        sec = int(rel_t) + 1
        if 1 <= sec <= args.duration:
            if 200 <= st < 300:
                sec_buckets[sec]["2xx"] += 1
            elif st == 503:
                sec_buckets[sec]["503"] += 1
            elif st == 599:
                sec_buckets[sec]["599"] += 1
            else:
                sec_buckets[sec]["other"] += 1

    # Write CSV
    os.makedirs(os.path.dirname(args.output_csv), exist_ok=True)
    with open(args.output_csv, "w", encoding="utf-8") as f:
        f.write("Second,Completed_2xx,Shed_503,Timeout_599,Pool_CheckedOut\n")
        for s in range(1, args.duration + 1):
            p_co = pool_by_sec.get(s, 0)
            f.write(f"{s},{sec_buckets[s]['2xx']},{sec_buckets[s]['503']},{sec_buckets[s]['599']},{p_co}\n")

    # Summarize
    tot_2xx = sum(b["2xx"] for b in sec_buckets.values())
    tot_503 = sum(b["503"] for b in sec_buckets.values())
    tot_599 = sum(b["599"] for b in sec_buckets.values())
    tot_req = tot_2xx + tot_503 + tot_599 + sum(b["other"] for b in sec_buckets.values())
    goodput = tot_2xx / args.duration

    print("-" * 80)
    print(f"RUN SUMMARY ({args.label}):")
    print(f"Total Completed 2xx: {tot_2xx}")
    print(f"Total Shed 503:      {tot_503}")
    print(f"Total Timeout 599:   {tot_599}")
    print(f"Total Requests:      {tot_req}")
    print(f"Average Goodput:     {goodput:.2f} 2xx/s")
    print(f"CSV saved to:        {args.output_csv}")
    print("=" * 80)

    # Cleanup temp db
    shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    main()

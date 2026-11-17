import os
import sys
import time
import json
import uuid
import shutil
import random
import asyncio
import argparse
import tempfile
import statistics
import subprocess
from datetime import datetime
from typing import List, Dict, Any, Optional

try:
    import httpx
except ImportError:
    import httpx2 as httpx

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PYTHON_EXE = sys.executable

def percentile(data: List[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    d = k - f
    return s[f] + d * (s[c] - s[f])

async def run_closed_loop_clients(
    base_url: str,
    clients: int,
    duration_sec: int,
    think_time_ms: int = 0
) -> Dict[str, Any]:
    latencies: List[float] = []
    statuses: Dict[int, int] = {}
    locked_count = 0

    # Pre-fetch candidate tickets
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as cl:
        try:
            r = await cl.get("/api/tickets?view=triage&limit=50", headers={"X-User-Id": "USR-101"})
            ticket_ids = [t["id"] for t in r.json().get("tickets", [])] if r.status_code == 200 else []
        except Exception:
            ticket_ids = []
    if not ticket_ids:
        ticket_ids = ["TCK-1001", "TCK-1002", "TCK-1004", "TCK-1005"]

    t0_wall = datetime.utcnow().isoformat()
    print(f"[{t0_wall}] Load run started: clients={clients}, duration={duration_sec}s, think_time={think_time_ms}ms")

    start_time = time.time()
    end_time = start_time + duration_sec

    async def worker(worker_idx: int):
        nonlocal locked_count
        user_id = f"USR-{101 + (worker_idx % 4)}"
        client_timeout = 30.0

        async with httpx.AsyncClient(base_url=base_url, timeout=client_timeout) as client:
            while time.time() < end_time:
                r_type = random.random()
                t_req0 = time.perf_counter()
                status_code = 599

                try:
                    if r_type < 0.70:
                        # 70% triage query
                        resp = await client.get("/api/tickets?view=triage&limit=25", headers={"X-User-Id": user_id})
                        status_code = resp.status_code
                    elif r_type < 0.90:
                        # 20% ticket detail
                        t_id = random.choice(ticket_ids)
                        resp = await client.get(f"/api/tickets/{t_id}", headers={"X-User-Id": user_id})
                        status_code = resp.status_code
                    elif r_type < 0.95:
                        # 5% ticket creation with idempotency key
                        body = {
                            "title": f"Load test ticket {uuid.uuid4().hex[:6]}",
                            "description": "Load benchmark ticket payload",
                            "tboh_id": f"TBOH-{random.randint(10000, 99999)}",
                            "priority": random.choice(["Low", "Medium", "High", "Urgent"]),
                            "check_in_date": (datetime.utcnow() + random.choice([None, None, None])).isoformat() if False else "2026-12-15T10:00:00",
                            "agency_id": "AGY-001"
                        }
                        headers = {
                            "X-User-Id": user_id,
                            "Idempotency-Key": f"load-{uuid.uuid4().hex}"
                        }
                        resp = await client.post("/api/tickets", json=body, headers=headers)
                        status_code = resp.status_code
                    else:
                        # 5% assign ticket
                        t_id = random.choice(ticket_ids)
                        target_agent = "USR-102" if user_id == "USR-101" else "USR-101"
                        resp = await client.post(
                            f"/api/tickets/{t_id}/assign",
                            json={"agent_id": target_agent},
                            headers={"X-User-Id": user_id}
                        )
                        status_code = resp.status_code

                except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout):
                    status_code = 599
                except Exception as exc:
                    if "database is locked" in str(exc).lower():
                        locked_count += 1
                    status_code = 599

                elapsed_ms = (time.perf_counter() - t_req0) * 1000.0
                latencies.append(elapsed_ms)
                statuses[status_code] = statuses.get(status_code, 0) + 1

                if think_time_ms > 0:
                    await asyncio.sleep(think_time_ms / 1000.0)

    tasks = [asyncio.create_task(worker(i)) for i in range(clients)]
    await asyncio.gather(*tasks)

    actual_duration = time.time() - start_time
    total_reqs = len(latencies)
    rps = total_reqs / actual_duration if actual_duration > 0 else 0.0

    return {
        "t0_wall": t0_wall,
        "rps": rps,
        "p50": percentile(latencies, 50.0),
        "p95": percentile(latencies, 95.0),
        "p99": percentile(latencies, 99.0),
        "statuses": statuses,
        "total_requests": total_reqs,
        "locked_errors": locked_count,
        "duration_sec": actual_duration
    }

def run_single_experiment(
    variant: str,
    cache_enabled: bool,
    clients: int,
    duration: int = 30,
    repeats: int = 3,
    think_time_ms: int = 0,
    enable_dump: bool = False,
    enable_rate_limit: bool = False,
    port: int = 8138,
    label: str = "run"
) -> Dict[str, Any]:
    temp_dir = tempfile.mkdtemp()
    temp_db = os.path.join(temp_dir, "perf.db")
    dump_file = os.path.join(temp_dir, "debug_dump.txt")
    pool_log = os.path.join(temp_dir, "pool_status.txt")
    cpu_log = os.path.join(temp_dir, "cpu_usage.csv")

    # 1. Prepare base seed DB
    src_db = os.path.join(temp_dir, "base_seed.db")
    env_seed = os.environ.copy()
    env_seed["DATABASE_URL"] = f"sqlite:///{src_db}"
    env_seed["PYTHONPATH"] = REPO_ROOT
    subprocess.run([PYTHON_EXE, "backend/seed/seed_data.py", "--tickets", "5000", "--reset", "--yes"],
                   cwd=REPO_ROOT, env=env_seed, check=True, capture_output=True)

    if variant == "b":
        from scripts.diag.make_triage_heavy_db import make_triage_heavy_db
        unassigned_cnt = make_triage_heavy_db(src_db, temp_db)
        print(f"Initialized Variant (b) [triage-heavy] DB: {unassigned_cnt} unassigned rows.")
    else:
        shutil.copyfile(src_db, temp_db)
        print("Initialized Variant (a) [normal seed] DB: 456 unassigned rows.")

    # 2. Server Environment
    env_server = os.environ.copy()
    env_server["DATABASE_URL"] = f"sqlite:///{temp_db}"
    env_server["PYTHONPATH"] = REPO_ROOT
    env_server["TRIAGE_CACHE_ENABLED"] = "true" if cache_enabled else "false"
    if enable_rate_limit:
        env_server["RATE_LIMIT_PER_MINUTE"] = "120"
    else:
        env_server["RATE_LIMIT_PER_MINUTE"] = "1000000"

    if enable_dump:
        env_server["OPSDESK_DEBUG_DUMP"] = "1"

    # Start Server
    server_cmd = [
        PYTHON_EXE, "scripts/diag/run_server_debug.py",
        "--port", str(port),
        "--dump-file", dump_file,
        "--pool-log", pool_log
    ]
    server_proc = subprocess.Popen(server_cmd, cwd=REPO_ROOT, env=env_server)
    base_url = f"http://127.0.0.1:{port}"

    time.sleep(2)
    # Wait for server ready
    for _ in range(15):
        try:
            r = httpx.get(f"{base_url}/health", timeout=2.0)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(1)
    else:
        server_proc.kill()
        raise RuntimeError("Server failed to respond to /health in 15s")

    # Start CPU Monitoring via PowerShell Get-Counter or wmic
    # Sampling server_proc.pid and current python pid
    cpu_monitor_proc = None
    try:
        ps_script = f"""
        $srvId = {server_proc.pid}
        $cliId = {os.getpid()}
        "Time,ServerCpu,ClientCpu" | Out-File -FilePath '{cpu_log}' -Encoding utf8
        while ($true) {{
            $sCpu = 0; $cCpu = 0
            try {{ $sCpu = (Get-Process -Id $srvId -ErrorAction SilentlyContinue).CPU }} catch {{}}
            try {{ $cCpu = (Get-Process -Id $cliId -ErrorAction SilentlyContinue).CPU }} catch {{}}
            $t = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
            "$t,$sCpu,$cCpu" | Out-File -FilePath '{cpu_log}' -Append -Encoding utf8
            Start-Sleep -Seconds 2
        }}
        """
        cpu_monitor_proc = subprocess.Popen(["powershell", "-NoProfile", "-Command", ps_script])
    except Exception as e:
        print(f"Warning: Could not start CPU monitor: {e}")

    runs_data = []
    try:
        # Warmup run (5s, not included in results)
        print(f"Running warmup (10 clients, 5s)...")
        _ = asyncio.run(run_closed_loop_clients(base_url, clients=10, duration_sec=5, think_time_ms=think_time_ms))

        # Measured runs
        for i in range(repeats):
            print(f"Starting Run {i+1}/{repeats} (clients={clients}, duration={duration}s)...")
            res = asyncio.run(run_closed_loop_clients(base_url, clients=clients, duration_sec=duration, think_time_ms=think_time_ms))
            runs_data.append(res)
            print(f"  Run {i+1} Result: RPS={res['rps']:.1f}, p50={res['p50']:.1f}ms, p95={res['p95']:.1f}ms, p99={res['p99']:.1f}ms, Statuses={res['statuses']}")

    finally:
        if cpu_monitor_proc:
            cpu_monitor_proc.terminate()
            try:
                cpu_monitor_proc.wait(timeout=3)
            except Exception:
                cpu_monitor_proc.kill()

        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except Exception:
            server_proc.kill()

    # Aggregate results
    rps_list = [r["rps"] for r in runs_data]
    p50_list = [r["p50"] for r in runs_data]
    p95_list = [r["p95"] for r in runs_data]
    p99_list = [r["p99"] for r in runs_data]

    combined_statuses: Dict[int, int] = {}
    total_locked = sum(r["locked_errors"] for r in runs_data)
    for r in runs_data:
        for code, count in r["statuses"].items():
            combined_statuses[code] = combined_statuses.get(code, 0) + count

    # Read pool status log if present
    pool_log_content = ""
    if os.path.exists(pool_log):
        with open(pool_log, "r", encoding="utf-8", errors="ignore") as pf:
            pool_log_content = pf.read()

    # Read dump file if present
    dump_content = ""
    if os.path.exists(dump_file):
        with open(dump_file, "r", encoding="utf-8", errors="ignore") as df:
            dump_content = df.read()

    # Read CPU log
    cpu_content = ""
    if os.path.exists(cpu_log):
        with open(cpu_log, "r", encoding="utf-8", errors="ignore") as cf:
            cpu_content = cf.read()

    result = {
        "label": label,
        "variant": variant,
        "cache_enabled": cache_enabled,
        "clients": clients,
        "duration": duration,
        "repeats": repeats,
        "think_time_ms": think_time_ms,
        "median_rps": statistics.median(rps_list) if rps_list else 0.0,
        "min_rps": min(rps_list) if rps_list else 0.0,
        "max_rps": max(rps_list) if rps_list else 0.0,
        "median_p50": statistics.median(p50_list) if p50_list else 0.0,
        "min_p50": min(p50_list) if p50_list else 0.0,
        "max_p50": max(p50_list) if p50_list else 0.0,
        "median_p95": statistics.median(p95_list) if p95_list else 0.0,
        "min_p95": min(p95_list) if p95_list else 0.0,
        "max_p95": max(p95_list) if p95_list else 0.0,
        "median_p99": statistics.median(p99_list) if p99_list else 0.0,
        "min_p99": min(p99_list) if p99_list else 0.0,
        "max_p99": max(p99_list) if p99_list else 0.0,
        "combined_statuses": combined_statuses,
        "total_locked": total_locked,
        "runs": runs_data,
        "pool_log": pool_log_content,
        "dump_content": dump_content,
        "cpu_content": cpu_content
    }

    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass

    return result

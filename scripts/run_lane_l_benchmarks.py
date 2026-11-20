import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import time
import shutil
import tempfile
import subprocess

TEMP_DIR = tempfile.mkdtemp()
DB_BASELINE = os.path.join(TEMP_DIR, "baseline.db")
DB_BASE = os.path.join(TEMP_DIR, "base.db")

ORIGINAL_DB = os.path.join(REPO_ROOT, "opsdesk.db")
PYTHON_EXE = sys.executable

print(f"Creating temp database copies in {TEMP_DIR}...")
shutil.copyfile(ORIGINAL_DB, DB_BASELINE)
shutil.copyfile(ORIGINAL_DB, DB_BASE)

# Apply migrations to temp copies if needed
from sqlalchemy import create_engine
from backend.app.database import ensure_schema_migrations
ensure_schema_migrations(create_engine(f"sqlite:///{DB_BASELINE}"))
ensure_schema_migrations(create_engine(f"sqlite:///{DB_BASE}"))

# 1. Start Baseline Server (from REPO_ROOT) on port 8121
env_baseline = os.environ.copy()
env_baseline["DATABASE_URL"] = f"sqlite:///{DB_BASELINE}"
env_baseline["PYTHONPATH"] = REPO_ROOT

log_baseline = open(os.path.join(TEMP_DIR, "baseline.log"), "w")
log_base = open(os.path.join(TEMP_DIR, "base.log"), "w")

proc_baseline = subprocess.Popen(
    [PYTHON_EXE, "-m", "uvicorn", "backend.app.main:app", "--port", "8121", "--host", "127.0.0.1"],
    cwd=REPO_ROOT,
    env=env_baseline,
    stdout=log_baseline,
    stderr=log_baseline
)

# 2. Start BASE Server on port 8122
env_base = os.environ.copy()
env_base["DATABASE_URL"] = f"sqlite:///{DB_BASE}"
env_base["PYTHONPATH"] = REPO_ROOT

proc_base = subprocess.Popen(
    [PYTHON_EXE, "-m", "uvicorn", "backend.app.main:app", "--port", "8122", "--host", "127.0.0.1"],
    cwd=REPO_ROOT,
    env=env_base,
    stdout=log_base,
    stderr=log_base
)

print("Waiting 3s for servers to initialize...")
time.sleep(3)

try:
    print("\n" + "#" * 80)
    print("RUNNING BENCHMARK AGAINST BASELINE (Port 8121)")
    print("#" * 80)
    cmd_baseline = [
        PYTHON_EXE, "scripts/loadtest.py",
        "--base-url", "http://127.0.0.1:8121",
        "--repeat", "5",
        "--db-path", DB_BASELINE
    ]
    subprocess.run(cmd_baseline, cwd=REPO_ROOT, check=True)

    print("\n" + "#" * 80)
    print("RUNNING BENCHMARK AGAINST BASE (Port 8122)")
    print("#" * 80)
    cmd_base = [
        PYTHON_EXE, "scripts/loadtest.py",
        "--base-url", "http://127.0.0.1:8122",
        "--repeat", "5",
        "--db-path", DB_BASE
    ]
    subprocess.run(cmd_base, cwd=REPO_ROOT, check=True)

finally:
    print("\nTerminating test servers...")
    proc_baseline.terminate()
    proc_base.terminate()
    try:
        proc_baseline.wait(timeout=3)
        proc_base.wait(timeout=3)
    except Exception:
        proc_baseline.kill()
        proc_base.kill()
    try:
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
    except Exception:
        pass
    print("Cleanup complete.")

import os
import sys
import tempfile
import time
import shutil

# Configure environment BEFORE importing database or main
temp_dir = tempfile.mkdtemp(prefix="opsdesk_deadlock_test_")
db_path = os.path.join(temp_dir, "test_deadlock.db")

os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["DB_POOL_SIZE"] = "1"
os.environ["DB_MAX_OVERFLOW"] = "0"
os.environ["DB_POOL_TIMEOUT"] = "3"
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000000"

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Seed the temporary database
from backend.app.database import engine, Base, SessionLocal
from backend.seed.seed_data import seed_database
Base.metadata.create_all(bind=engine)
with SessionLocal() as db:
    seed_database(db)

# Instrument engine with pool events logger
from scripts.diag.instrument_pool import instrument_engine_pool, nested_checkout_events
instrument_engine_pool(engine)

from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

AGENT_HEADERS = {
    "X-User-Id": "USR-101", # Aisha Khan (Agent)
    "Content-Type": "application/json"
}
LEAD_HEADERS = {
    "X-User-Id": "USR-104", # Elena Rostova (Lead)
    "Content-Type": "application/json"
}

endpoints_to_test = [
    ("GET", "/api/tickets?view=triage", None, AGENT_HEADERS),
    ("GET", "/api/tickets?view=my_queue", None, AGENT_HEADERS),
    ("GET", "/api/tickets?view=by_intent", None, AGENT_HEADERS),
    ("GET", "/api/tickets/TCK-1001", None, AGENT_HEADERS),
    ("POST", "/api/tickets", {
        "tboh_id": "TBOH-DEADLOCK-01",
        "title": "Deterministic Deadlock Verification Ticket",
        "description": "Checking for nested checkout pool exhaustion",
        "agency_id": "AGY-001",
        "intent": "refund",
        "priority": "high",
        "check_in_date": "2026-12-01T00:00:00Z",
        "lcd_date": "2026-11-25T00:00:00Z"
    }, AGENT_HEADERS),
    ("POST", "/api/tickets/TCK-1001/assign", {"agent_id": "USR-102"}, AGENT_HEADERS),
    ("POST", "/api/tickets/TCK-1001/status", {"status": "in_progress", "version": 1}, AGENT_HEADERS),
    ("POST", "/api/tickets/TCK-1001/escalate", {"reason": "Deterministic deadlock check", "version": 2}, AGENT_HEADERS),
    ("POST", "/api/tickets/TCK-1001/transfer", {"target_agent_id": "USR-101", "reason": "Workload balance", "version": 3}, AGENT_HEADERS),
    ("POST", "/api/tickets/TCK-1001/messages", {"message_type": "public", "content": "Test message for deadlock check"}, AGENT_HEADERS),
    ("POST", "/api/tickets/TCK-1001/side-threads", {
        "supplier_name": "Hotel Partner",
        "subject": "Supplier side thread inquiry",
        "recipients": "partner@travelsupplier.internal",
        "initial_message": "Checking room availability"
    }, AGENT_HEADERS),
    ("POST", "/api/tickets/TCK-1001/link-suggestion", {"bug_link": "https://jira.internal/browse/BUG-999"}, AGENT_HEADERS),
    ("GET", "/api/insights/themes", None, LEAD_HEADERS),
]

print("=" * 110)
print(f"DETERMINISTIC DEADLOCK / NESTED CHECKOUT TEST")
print(f"Config: DB_POOL_SIZE={os.getenv('DB_POOL_SIZE')}, DB_MAX_OVERFLOW={os.getenv('DB_MAX_OVERFLOW')}, DB_POOL_TIMEOUT={os.getenv('DB_POOL_TIMEOUT')}s")
print(f"Database: {db_path}")
print("=" * 110)
print(f"{'Endpoint':<45} | {'Method':<6} | {'Status':<6} | {'Latency (ms)':<12} | {'NESTED_CHECKOUT?'}")
print("-" * 110)

table_rows = []
nested_found_any = False

for method, url, payload, headers in endpoints_to_test:
    start_nested_count = len(nested_checkout_events)
    t0 = time.perf_counter()
    if method == "GET":
        resp = client.get(url, headers=headers)
    elif method == "POST":
        resp = client.post(url, headers=headers, json=payload)
    t1 = time.perf_counter()
    latency_ms = (t1 - t0) * 1000

    new_nested = len(nested_checkout_events) - start_nested_count
    nested_str = "YES" if new_nested > 0 else "NO"
    if new_nested > 0:
        nested_found_any = True

    row_str = f"{url:<45} | {method:<6} | {resp.status_code:<6} | {latency_ms:>10.2f} ms | {nested_str}"
    print(row_str)
    table_rows.append(row_str)

print("=" * 110)

out_file = os.path.join(REPO_ROOT, "docs", "perf_runs", "step1c_deadlock_table.txt")
with open(out_file, "w", encoding="utf-8") as f:
    f.write(f"DETERMINISTIC DEADLOCK / NESTED CHECKOUT TEST\n")
    f.write(f"Config: DB_POOL_SIZE=1, DB_MAX_OVERFLOW=0, DB_POOL_TIMEOUT=3s\n\n")
    f.write(f"{'Endpoint':<45} | {'Method':<6} | {'Status':<6} | {'Latency (ms)':<12} | {'NESTED_CHECKOUT?'}\n")
    f.write("-" * 110 + "\n")
    for r in table_rows:
        f.write(r + "\n")
    f.write("=" * 110 + "\n")
    if nested_found_any:
        f.write(f"CONCLUSION: NESTED_CHECKOUT detected! Total events: {len(nested_checkout_events)}\n")
        for ev in nested_checkout_events:
            f.write(f"Stack:\n{ev['stack']}\n")
    else:
        f.write("CONCLUSION: nested checkout NAHI mila (hypothesis reject)\n")

print(f"Results written to: {out_file}")
if nested_found_any:
    print(f"CONCLUSION: NESTED_CHECKOUT detected! Total events: {len(nested_checkout_events)}")
else:
    print("CONCLUSION: nested checkout NAHI mila (hypothesis reject)")

# Cleanup
client.close()
try:
    shutil.rmtree(temp_dir)
except Exception:
    pass

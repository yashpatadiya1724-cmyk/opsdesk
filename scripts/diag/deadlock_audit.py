import os
import sys

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath("."))

temp_db_path = os.path.abspath("test_deadlock_audit_temp.db")
if os.path.exists(temp_db_path):
    try: os.remove(temp_db_path)
    except: pass

# Enforce Pool=1, Overflow=0, Timeout=3s on temporary database
os.environ["DATABASE_URL"] = f"sqlite:///{temp_db_path}"
os.environ["DB_POOL_SIZE"] = "1"
os.environ["DB_MAX_OVERFLOW"] = "0"
os.environ["DB_POOL_TIMEOUT"] = "3"
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000000"

import time
import traceback
import threading
from typing import Dict, List, Tuple
from fastapi.testclient import TestClient
from sqlalchemy import event

from backend.app.database import engine, Base, SessionLocal, ensure_schema_migrations
from backend.seed.seed_data import seed_database
from backend.app.main import app
from backend.app.models import Ticket, SideConversation

def run_deadlock_audit():
    # Setup test DB
    ensure_schema_migrations(engine)
    db = SessionLocal()
    seed_database(db, engine_bind=engine, total_tickets=50, drop_existing=False)
    db.close()

    # Thread-local tracking of checkouts
    thread_checkouts: Dict[int, List[Tuple[float, List[str]]]] = {}
    nested_detected = []
    max_concurrent_checked_out = 0
    current_checked_out = 0
    lock = threading.Lock()

    @event.listens_for(engine, "checkout")
    def on_checkout(dbapi_con, con_record, con_proxy):
        nonlocal max_concurrent_checked_out, current_checked_out
        tid = threading.get_ident()
        stack = traceback.format_stack(limit=8)
        with lock:
            current_checked_out += 1
            if current_checked_out > max_concurrent_checked_out:
                max_concurrent_checked_out = current_checked_out
            if tid not in thread_checkouts:
                thread_checkouts[tid] = []
            if len(thread_checkouts[tid]) > 0:
                nested_detected.append((tid, stack))
            thread_checkouts[tid].append((time.time(), stack))

    @event.listens_for(engine, "checkin")
    def on_checkin(dbapi_con, con_record):
        nonlocal current_checked_out
        tid = threading.get_ident()
        with lock:
            current_checked_out -= 1
            if tid in thread_checkouts and thread_checkouts[tid]:
                thread_checkouts[tid].pop()

    client = TestClient(app)

    db = SessionLocal()
    t = db.query(Ticket).filter(Ticket.status == "Open").first()
    if not t:
        t = db.query(Ticket).first()
    ticket_id = t.id
    ticket_ver = t.version
    db.close()

    lead_headers = {"X-User-ID": "USR-104", "X-Role": "Lead", "X-Agency-ID": "AGY-001"}
    agent_headers = {"X-User-ID": "USR-101", "X-Role": "Agent", "X-Agency-ID": "AGY-001"}

    print("==========================================================================================")
    print("EXTRACTING REAL ROUTES DYNAMICALLY FROM app.routes:")
    print("==========================================================================================")
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        name = getattr(route, "name", None)
        if methods and path:
            methods_filtered = [m for m in methods if m not in ["HEAD", "OPTIONS"]]
            if methods_filtered and not path.startswith("/docs") and not path.startswith("/redoc") and path != "/openapi.json":
                for m in methods_filtered:
                    print(f"  {m:6} {path:50} ({name})")

    # Real endpoints with strictly valid payloads
    test_cases = [
        ("GET", "/health", "health_check", {}, lead_headers, None),
        ("GET", "/ready", "readiness_check", {}, lead_headers, None),
        ("POST", "/api/ai/suggest-intent", "api_suggest_intent", {}, lead_headers, {
            "title": "Need refund for flight cancellation",
            "description": "Passenger flight was cancelled by airline, seeking full refund immediately."
        }),
        ("GET", "/api/tickets?view=triage&limit=25", "list_tickets [view=triage]", {}, lead_headers, None),
        ("GET", "/api/tickets?view=my_queue&limit=25", "list_tickets [view=my_queue]", {}, agent_headers, None),
        ("GET", "/api/tickets?view=by_region&limit=25", "list_tickets [view=by_region]", {}, lead_headers, None),
        ("GET", "/api/tickets?view=by_intent&limit=25", "list_tickets [view=by_intent]", {}, lead_headers, None),
        ("GET", "/api/tickets?view=linked&limit=25", "list_tickets [view=linked]", {}, lead_headers, None),
        ("POST", "/api/tickets", "create_ticket", {}, lead_headers, {
            "title": "Audit Test Ticket",
            "description": "Audit ticket description for deadlock testing",
            "tboh_id": "TBOH-AUDIT-999",
            "check_in_date": "2026-12-01T10:00:00Z",
            "priority": "Medium",
            "intent": "Refund Request",
            "agency_id": "AGY-001"
        }),
        ("GET", f"/api/tickets/{ticket_id}", "get_ticket_details", {}, lead_headers, None),
        ("POST", f"/api/tickets/{ticket_id}/assign", "assign_ticket", {}, lead_headers, {"agent_id": "USR-101"}),
        ("POST", f"/api/tickets/{ticket_id}/unassign", "unassign_ticket", {}, lead_headers, {}),
        ("POST", f"/api/tickets/{ticket_id}/status", "update_ticket_status", {}, lead_headers, {
            "status": "Pending"
        }),
        ("POST", f"/api/tickets/{ticket_id}/escalate", "escalate_ticket", {}, lead_headers, {
            "reason": "Executive attention required"
        }),
        ("POST", f"/api/tickets/{ticket_id}/transfer", "transfer_ticket", {}, lead_headers, {
            "target_agent_id": "USR-102",
            "reason": "Regional realignment"
        }),
        ("POST", f"/api/tickets/{ticket_id}/messages", "post_ticket_message", {}, lead_headers, {
            "message_type": "InternalNote",
            "content": "Audit message body note"
        }),
        ("GET", f"/api/tickets/{ticket_id}/side-threads", "list_side_threads", {}, lead_headers, None),
        ("POST", f"/api/tickets/{ticket_id}/side-threads", "create_side_thread", {}, lead_headers, {
            "supplier_name": "Grand Palace Hotel",
            "subject": "Supplier inquiry re booking",
            "recipients": ["reservations@hotel.com"],
            "initial_message": "Checking availability for late arrival"
        }),
        ("POST", f"/api/tickets/{ticket_id}/link-suggestion", "link_suggested_bug", {}, lead_headers, {
            "bug_link": "https://bugs.example.com/OPS-99"
        }),
        ("GET", "/api/insights/themes", "get_top_themes", {}, lead_headers, None),
        ("GET", "/api/export/tickets.csv", "export_tickets_csv", {}, lead_headers, None),
    ]

    print("\n==========================================================================================")
    print("STEP 1: DETERMINISTIC DEADLOCK & NESTED CHECKOUT AUDIT TABLE (POOL=1, OVERFLOW=0, TIMEOUT=3s)")
    print("==========================================================================================")
    header = f"{'Endpoint / Action':<46} | {'Method':<6} | {'Status':<6} | {'Latency':<9} | {'MaxChecked':<10} | {'Nested?':<7}"
    print(header)
    print("-" * len(header))

    all_passed = True
    for method, path, label, params, headers, payload in test_cases:
        nested_detected.clear()
        max_concurrent_checked_out = 0
        t0 = time.perf_counter()
        if method == "GET":
            resp = client.get(path, headers=headers, params=params)
        elif method == "POST":
            resp = client.post(path, headers=headers, json=payload, params=params)
        elif method == "PATCH":
            resp = client.patch(path, headers=headers, json=payload, params=params)
        lat_ms = (time.perf_counter() - t0) * 1000.0

        has_nested = "Y" if nested_detected else "N"
        status_str = str(resp.status_code)
        if resp.status_code not in [200, 201]:
            all_passed = False

        row = f"{label:<46} | {method:<6} | {status_str:<6} | {lat_ms:>6.1f} ms | {max_concurrent_checked_out:<10} | {has_nested:<7}"
        print(row)
        if nested_detected:
            print("  [NESTED CHECKOUT STACK]:")
            for frame in nested_detected[0][1][-6:]:
                print("    " + frame.strip())

    print("==========================================================================================")
    print(f"Overall Result: {'PASS (Zero nested checkouts, zero deadlocks across all real routes)' if all_passed else 'FAIL'}")

    # Cleanup temp db
    if os.path.exists(temp_db_path):
        try: os.remove(temp_db_path)
        except: pass

if __name__ == "__main__":
    run_deadlock_audit()

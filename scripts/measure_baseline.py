import os
import sys
import tempfile
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.app.database import Base
from backend.app.models import Ticket, TicketLink, TicketMessage, TicketTheme, AuditLog, Agency, User
from backend.seed.seed_data import seed_database
from fastapi.testclient import TestClient

def run_explain_plans():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "explain.db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        seed_database(session, engine_bind=engine, total_tickets=50, drop_existing=False)
    finally:
        session.close()

    queries = [
        (
            "Triage View Query",
            "SELECT * FROM tickets WHERE status IN ('New', 'Open', 'Pending', 'Escalated') AND assigned_to IS NULL"
        ),
        (
            "My Queue View Query",
            "SELECT * FROM tickets WHERE assigned_to = 'USR-101' AND status IN ('New', 'Open', 'Pending', 'Escalated')"
        ),
        (
            "Linked View Query",
            "SELECT * FROM tickets WHERE id IN (SELECT ticket_id FROM ticket_links UNION SELECT linked_ticket_id FROM ticket_links)"
        ),
        (
            "Insights / Themes Query",
            """SELECT ticket_themes.theme, count(ticket_themes.id) AS count 
               FROM ticket_themes JOIN tickets ON ticket_themes.ticket_id = tickets.id 
               WHERE tickets.created_at >= '2026-01-01' 
               GROUP BY ticket_themes.theme ORDER BY count(ticket_themes.id) DESC"""
        ),
        (
            "Export CSV Query",
            "SELECT * FROM tickets ORDER BY tickets.created_at DESC"
        ),
        (
            "TBOH Lookup Query",
            "SELECT * FROM tickets WHERE tboh_id = 'TBOH-1001'"
        ),
        (
            "Audit Logs by Ticket Query",
            "SELECT * FROM audit_logs WHERE ticket_id = 'TCK-1001' ORDER BY created_at DESC"
        ),
        (
            "Messages by Ticket Query",
            "SELECT * FROM ticket_messages WHERE ticket_id = 'TCK-1001'"
        ),
    ]

    print("=" * 80)
    print("EXPLAIN QUERY PLAN RESULTS (SQLite 3)")
    print("=" * 80)

    scan_tables = []
    with engine.connect() as conn:
        for name, sql in queries:
            print(f"\n--- {name} ---")
            print(f"SQL: {sql.strip()}")
            plan_rows = conn.execute(text(f"EXPLAIN QUERY PLAN {sql}")).fetchall()
            has_scan = False
            for row in plan_rows:
                # row is (id, parent, notused, detail)
                detail = row[3] if len(row) > 3 else str(row)
                print(f"  PLAN: {detail}")
                if "SCAN TABLE" in detail or "SCAN" in detail:
                    has_scan = True
                    scan_tables.append((name, detail))
            if not has_scan:
                print("  INDEX USED (No full table scan)")

    print("\n" + "=" * 80)
    print("SUMMARY OF FULL TABLE SCANS (SCAN TABLE):")
    print("=" * 80)
    for q_name, detail in scan_tables:
        print(f"- {q_name}: {detail}")

    engine.dispose()
    try:
        os.remove(db_path)
        os.rmdir(temp_dir)
    except Exception:
        pass


def run_statement_counts():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "stmt_count.db")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    from backend.app.database import engine, Base, SessionLocal, get_db
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        seed_database(session, engine_bind=engine, total_tickets=100, drop_existing=False)
    finally:
        session.close()

    from backend.app.main import app
    client = TestClient(app)

    executed_queries = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        executed_queries.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)

    print("\n" + "=" * 80)
    print("SQL STATEMENT COUNT PROFILING VIA SQLALCHEMY EVENT LISTENERS")
    print("=" * 80)

    # 1. Profile GET /api/tickets?view=triage&limit=25
    executed_queries.clear()
    resp_list = client.get("/api/tickets?view=triage&limit=25", headers={"X-User-Id": "USR-101"})
    count_list = len(executed_queries)
    print(f"\n1. GET /api/tickets?view=triage&limit=25")
    print(f"   HTTP Status: {resp_list.status_code}")
    print(f"   Returned Tickets: {len(resp_list.json().get('tickets', []))}")
    print(f"   Total SQL Statements Executed: {count_list}")
    for idx, stmt in enumerate(executed_queries, 1):
        clean_stmt = " ".join(stmt.split())
        print(f"     [{idx}] {clean_stmt[:120]}...")

    # 2. Profile GET /api/tickets/TCK-1001
    executed_queries.clear()
    resp_detail = client.get("/api/tickets/TCK-1001", headers={"X-User-Id": "USR-101"})
    count_detail = len(executed_queries)
    print(f"\n2. GET /api/tickets/TCK-1001")
    print(f"   HTTP Status: {resp_detail.status_code}")
    print(f"   Total SQL Statements Executed: {count_detail}")
    for idx, stmt in enumerate(executed_queries, 1):
        clean_stmt = " ".join(stmt.split())
        print(f"     [{idx}] {clean_stmt[:120]}...")

    event.remove(engine, "before_cursor_execute", before_cursor_execute)
    engine.dispose()
    try:
        os.remove(db_path)
        os.rmdir(temp_dir)
    except Exception:
        pass


if __name__ == "__main__":
    run_explain_plans()
    run_statement_counts()

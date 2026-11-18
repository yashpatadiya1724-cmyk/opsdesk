import pytest
from sqlalchemy import event
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.database import engine

client = TestClient(app)

def test_sql_statement_counts():
    statements = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)

    try:
        # Measure statements for GET /api/tickets?view=triage&limit=25
        statements.clear()
        res_list = client.get("/api/tickets?view=triage&limit=25", headers={"X-User-Id": "USR-101"})
        assert res_list.status_code == 200
        list_statement_count = len(statements)

        # Measure statements for GET /api/tickets/{ticket_id}
        statements.clear()
        res_detail = client.get("/api/tickets/TCK-1001", headers={"X-User-Id": "USR-101"})
        assert res_detail.status_code == 200
        detail_statement_count = len(statements)

        print(f"\n[RAW_STATEMENT_COUNT] GET /api/tickets?view=triage&limit=25: {list_statement_count}")
        print(f"[RAW_STATEMENT_COUNT] GET /api/tickets/TCK-1001: {detail_statement_count}")

        # The counts should be bounded:
        # Auth lookup + query = 2 statements for list
        # Auth lookup + ticket + eager loads + links = bounded (not N+1 per message/side-thread)
        assert list_statement_count <= 3
        assert detail_statement_count <= 6

    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)

"""
Smoke test verifying frontend contracts against FastAPI backend endpoints.
Uses an isolated temporary SQLite database to ensure opsdesk.db is never touched.

Covers:
- GET /health
- OPTIONS /api/tickets (CORS preflight for http://localhost:3000)
- GET /api/tickets (view=triage, limit, offset)
- POST /api/ai/suggest-intent
- POST /api/tickets (create ticket with intent)
- GET /api/tickets/{id} (full detail including suggested_bug_link, messages, side_conversations)
- POST /api/tickets/{id}/link-suggestion
- GET /api/insights/themes (Lead and EscalationManager)
- GET /api/export/tickets.csv (Lead streaming CSV)
"""

import os
import sys
import tempfile
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from backend.app.database import get_db, Base
from backend.app.main import app
from backend.seed.seed_data import seed_database

def run_smoke():
    print("=== OpsDesk Frontend-Backend Contract Smoke Test ===")

    # Set up isolated temp DB
    temp_dir = tempfile.gettempdir()
    db_file = os.path.join(temp_dir, f"smoke_opsdesk_{uuid.uuid4().hex[:8]}.db")
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SmokeSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SmokeSession()
    seed_database(session, engine_bind=engine, total_tickets=50)
    session.close()

    def override_get_db():
        db = SmokeSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        # 1. Health check
        res = client.get("/health")
        assert res.status_code == 200, f"Health check failed: {res.text}"
        print("[PASS] 1. GET /health -> 200 OK")

        # 2. CORS Preflight & Header check for http://localhost:3000
        res = client.options(
            "/api/tickets",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-User-Id,Content-Type",
            },
        )
        assert res.status_code == 200, f"CORS OPTIONS failed: {res.status_code}"
        assert res.headers.get("access-control-allow-origin") == "http://localhost:3000"
        print("[PASS] 2. OPTIONS /api/tickets (CORS preflight) -> 200 with allow-origin http://localhost:3000")

        # 3. GET /api/tickets for Staff (triage queue)
        res = client.get("/api/tickets?view=triage&limit=10&offset=0", headers={"X-User-Id": "USR-101"})
        assert res.status_code == 200, f"Triage queue failed: {res.text}"
        data = res.json()
        assert "tickets" in data and "total" in data
        print(f"[PASS] 3. GET /api/tickets?view=triage -> 200 OK (returned {len(data['tickets'])} items, total: {data['total']})")

        # 4. Intent Auto-Suggest (AI proxy / rule engine)
        res = client.post(
            "/api/ai/suggest-intent",
            json={"title": "Flight Cancelled at midnight", "description": "Need full refund for PNR XYZ"},
            headers={"X-User-Id": "USR-101"},
        )
        assert res.status_code == 200, f"Suggest intent failed: {res.text}"
        intent_data = res.json()
        assert "intent" in intent_data and "source" in intent_data
        print(f"[PASS] 4. POST /api/ai/suggest-intent -> 200 OK (intent: {intent_data['intent']}, source: {intent_data['source']})")

        # 5. POST /api/tickets (Create Ticket)
        create_payload = {
            "title": "Smoke Test Traveler Check-in Issue",
            "description": "Guest unable to check in at kiosk due to name mismatch",
            "tboh_id": "TBOH-SMOKE-001",
            "priority": "High",
            "check_in_date": "2026-11-20T10:00:00Z",
            "intent": "Emergency Check-in Assist",
            "agency_id": "AGY-001",
        }
        res = client.post("/api/tickets", json=create_payload, headers={"X-User-Id": "USR-101"})
        assert res.status_code == 201, f"Ticket creation failed: {res.text}"
        created = res.json()
        ticket_id = created["id"]
        print(f"[PASS] 5. POST /api/tickets -> 201 Created (id: {ticket_id})")

        # 6. GET /api/tickets/{id} (Ticket Detail)
        res = client.get(f"/api/tickets/{ticket_id}", headers={"X-User-Id": "USR-101"})
        assert res.status_code == 200, f"Get ticket detail failed: {res.text}"
        detail = res.json()
        assert detail["id"] == ticket_id
        assert "suggested_bug_link" in detail
        assert "side_conversations" in detail
        assert "messages" in detail
        print(f"[PASS] 6. GET /api/tickets/{ticket_id} -> 200 OK (details verified)")

        # 7. POST /api/tickets/{id}/link-suggestion (Staff Bug Link)
        res = client.post(
            f"/api/tickets/{ticket_id}/link-suggestion",
            json={"bug_link": "https://jira.internal.example.com/browse/HOTEL-999"},
            headers={"X-User-Id": "USR-101"},
        )
        assert res.status_code == 200, f"Link suggestion failed: {res.text}"
        print(f"[PASS] 7. POST /api/tickets/{ticket_id}/link-suggestion -> 200 OK")

        # 8. GET /api/insights/themes (Lead & EscalationManager)
        res = client.get("/api/insights/themes?days=7", headers={"X-User-Id": "USR-104"})
        assert res.status_code == 200, f"Insights themes failed: {res.text}"
        insights = res.json()
        assert "themes" in insights
        assert "total_tagged_records" in insights
        print(f"[PASS] 8. GET /api/insights/themes -> 200 OK ({len(insights['themes'])} themes, total: {insights['total_tagged_records']})")

        # 9. GET /api/export/tickets.csv (Lead streaming CSV)
        res = client.get("/api/export/tickets.csv", headers={"X-User-Id": "USR-104"})
        assert res.status_code == 200, f"Export CSV failed: {res.text}"
        assert "text/csv" in res.headers.get("content-type", "")
        lines = res.text.strip().split("\n")
        print(f"[PASS] 9. GET /api/export/tickets.csv -> 200 OK (streamed {len(lines)} CSV rows, header: {lines[0][:50]}...)")

        print("\nALL 9 FRONTEND-BACKEND CONTRACT CHECKS PASSED PERFECTLY!")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
        if os.path.exists(db_file):
            try:
                os.remove(db_file)
            except OSError:
                pass

if __name__ == "__main__":
    run_smoke()

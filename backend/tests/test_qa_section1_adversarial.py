import uuid
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models import Ticket, AuditLog, TicketMessage
from backend.app import main as main_module
from backend.config.routing_config import DEFAULT_ESCALATION_MANAGER_ID


def test_adversarial_requester_lcd_emergency_bypass_injection(client: TestClient, db_session: Session):
    """
    Edge Case 1: Requester attempts to trigger Tier-1 bypass via LCD date.
    check_in_date is 48 hours away, lcd_date is 2.5 hours away, intent="Emergency Check-in Assist".
    Must route to regional agent with review-recommended routing reason, NOT to USR-103, and NOT Escalated.
    """
    with main_module._rate_limit_lock:
        main_module._rate_limit_records.clear()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    checkin_48h = now + timedelta(hours=48)
    lcd_2_5h = now + timedelta(hours=2.5)

    payload = {
        "title": "Emergency Check-in Assistance at Front Desk",
        "description": "Guest stranded at check-in counter, front desk unable to find voucher",
        "tboh_id": f"TBOH-ADV-{uuid.uuid4().hex[:6].upper()}",
        "priority": "Medium",
        "check_in_date": checkin_48h.isoformat(),
        "lcd_date": lcd_2_5h.isoformat(),
        "intent": "Emergency Check-in Assist"
    }

    resp = client.post("/api/tickets", json=payload, headers={"X-User-Id": "USR-201"})
    assert resp.status_code == 201
    data = resp.json()

    assert data["priority"] == "Medium"
    assert data["status"] in ["Open", "New"]
    assert data["status"] != "Escalated"
    assert data["assigned_to"] != DEFAULT_ESCALATION_MANAGER_ID
    assert "Tier-1 Emergency Bypass" not in (data["routing_reason"] or "")

    # Zero bypass audit logs or internal notes
    audit = db_session.query(AuditLog).filter(
        AuditLog.ticket_id == data["id"],
        AuditLog.action == "ticket.emergency_bypass"
    ).first()
    assert audit is None


def test_adversarial_requester_untrusted_intent_overwritten(client: TestClient):
    """
    Edge Case 2: Requester sends EMERGENCY_BYPASS_INTENT with non-emergency content.
    Server-side intent classifier must completely disregard client-supplied intent.
    """
    with main_module._rate_limit_lock:
        main_module._rate_limit_records.clear()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    payload = {
        "title": "Need voucher copy and ticket pdf",
        "description": "Please resend voucher PDF for our traveler itinerary",
        "tboh_id": f"TBOH-ADV-{uuid.uuid4().hex[:6].upper()}",
        "priority": "Low",
        "check_in_date": (now + timedelta(hours=2)).isoformat(),
        "intent": "Emergency Check-in Assist"
    }

    resp = client.post("/api/tickets", json=payload, headers={"X-User-Id": "USR-201"})
    assert resp.status_code == 201
    data = resp.json()

    assert data["intent"] != "Emergency Check-in Assist"
    assert data["intent"] == "Voucher Resend"


def test_adversarial_cross_agency_existence_leak_prevention(client: TestClient):
    """
    Edge Case 3: Foreign agency ticket query must return 404 identical to non-existent ticket.
    Staff members can view it (200), and Requester actions on own tickets get 403.
    """
    # 1. Foreign ticket GET returns 404
    foreign_resp = client.get("/api/tickets/TCK-1004", headers={"X-User-Id": "USR-202"})
    assert foreign_resp.status_code == 404
    assert foreign_resp.json() == {"detail": "Ticket not found"}

    # 2. Non-existent ticket GET returns identical 404
    fake_resp = client.get("/api/tickets/TCK-NONEXISTENT-FAKEXYZ", headers={"X-User-Id": "USR-202"})
    assert fake_resp.status_code == 404
    assert fake_resp.json() == foreign_resp.json()

    # 3. Staff member gets 200 on same ticket
    staff_resp = client.get("/api/tickets/TCK-1004", headers={"X-User-Id": "USR-101"})
    assert staff_resp.status_code == 200

    # 4. Requester on own ticket attempting internal note gets 403 Forbidden
    own_note_resp = client.post(
        "/api/tickets/TCK-1004/messages",
        json={"message_type": "InternalNote", "content": "Attempted internal note"},
        headers={"X-User-Id": "USR-201"}
    )
    assert own_note_resp.status_code == 403


def test_adversarial_rate_limit_user_isolation(client: TestClient):
    """
    Edge Case 4: Rate limit on User A does not block User B.
    429 response contains valid Retry-After header.
    """
    with main_module._rate_limit_lock:
        main_module._rate_limit_records.clear()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    checkin = now + timedelta(days=3)

    # Exhaust User A (USR-201) limit (10 tickets)
    for i in range(10):
        resp = client.post("/api/tickets", json={
            "title": f"User A Ticket {i}",
            "description": "Load test ticket",
            "tboh_id": f"TBOH-RLA-{i}-{uuid.uuid4().hex[:4].upper()}",
            "priority": "Low",
            "check_in_date": checkin.isoformat(),
        }, headers={"X-User-Id": "USR-201"})
        assert resp.status_code == 201

    # 11th request from User A gets 429
    blocked_resp = client.post("/api/tickets", json={
        "title": "User A 11th Ticket",
        "description": "Should be blocked",
        "tboh_id": f"TBOH-RLA-11-{uuid.uuid4().hex[:4].upper()}",
        "priority": "Low",
        "check_in_date": checkin.isoformat(),
    }, headers={"X-User-Id": "USR-201"})
    assert blocked_resp.status_code == 429
    assert blocked_resp.headers.get("retry-after") == "60"

    # User B (USR-202) from another agency is NOT blocked
    user_b_resp = client.post("/api/tickets", json={
        "title": "User B Ticket 1",
        "description": "User B should succeed",
        "tboh_id": f"TBOH-RLB-01-{uuid.uuid4().hex[:4].upper()}",
        "priority": "Low",
        "check_in_date": checkin.isoformat(),
    }, headers={"X-User-Id": "USR-202"})
    assert user_b_resp.status_code == 201

import os
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models import Ticket, User, Agency, AuditLog, TicketMessage
from backend.app import main as main_module
from backend.config.routing_config import DEFAULT_ESCALATION_MANAGER_ID


def test_requester_ticket_does_not_trigger_emergency_bypass(client: TestClient, db_session: Session):
    """
    SECTION 1.1 & 1.2:
    Only tickets created by internal staff (Agent, EscalationManager, Lead) may trigger Tier-1 Emergency Bypass.
    Tickets created by a Requester never auto-escalate or auto-assign to the escalation manager:
    - Keep requested priority (payload.priority)
    - Normal Tier-1 routing to regional agent (select_agent_tier1), not USR-103
    - Status is Open (or New), never Escalated
    - routing_reason = 'Requester ticket: near check-in, review recommended' when near check-in
    - No ticket.emergency_bypass audit log
    - No [Emergency Bypass] internal note
    """
    with main_module._rate_limit_lock:
        main_module._rate_limit_records.clear()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    checkin_3h = now + timedelta(hours=3)

    payload = {
        "title": "Emergency front desk check-in issue",
        "description": "Guest cannot check-in at front desk reception, booking not found",
        "tboh_id": f"TBOH-REQ-{uuid.uuid4().hex[:6].upper()}",
        "priority": "Medium",
        "check_in_date": checkin_3h.isoformat(),
        "intent": "Emergency Check-in Assist",
    }

    resp = client.post("/api/tickets", json=payload, headers={"X-User-Id": "USR-201"})
    assert resp.status_code == 201
    data = resp.json()

    # Requester ticket keeps requested priority and normal status
    assert data["priority"] == "Medium"
    assert data["status"] in ["Open", "New"]
    assert data["status"] != "Escalated"
    # Never assigned to escalation manager
    assert data["assigned_to"] != DEFAULT_ESCALATION_MANAGER_ID
    assert data["assigned_to"] is not None  # Assigned to regional desk agent
    assert data["routing_reason"] == "Requester ticket: near check-in, review recommended"

    ticket_id = data["id"]

    # Verify no emergency bypass audit log
    audit = db_session.query(AuditLog).filter(
        AuditLog.ticket_id == ticket_id,
        AuditLog.action == "ticket.emergency_bypass"
    ).first()
    assert audit is None

    # Verify no emergency bypass internal note
    note = db_session.query(TicketMessage).filter(
        TicketMessage.ticket_id == ticket_id,
        TicketMessage.message_type == "InternalNote"
    ).first()
    assert note is None


def test_staff_created_ticket_triggers_emergency_bypass(client: TestClient, db_session: Session):
    """
    SECTION 1.1:
    Staff-created tickets within 0 <= hours <= 4 with bypass intent trigger Tier-1 Emergency Bypass:
    - priority='Urgent'
    - status='Escalated'
    - assigned_to=DEFAULT_ESCALATION_MANAGER_ID (USR-103)
    - routing_reason contains 'Tier-1 Emergency Bypass'
    - Audit log ticket.emergency_bypass is emitted
    - Internal note is created
    """
    with main_module._rate_limit_lock:
        main_module._rate_limit_records.clear()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    checkin_3h = now + timedelta(hours=3)

    payload = {
        "title": "Emergency check-in assistance required",
        "description": "Traveler stranded at desk with check-in in 3 hours",
        "tboh_id": f"TBOH-STF-{uuid.uuid4().hex[:6].upper()}",
        "priority": "Low",
        "check_in_date": checkin_3h.isoformat(),
        "intent": "Emergency Check-in Assist",
        "agency_id": "AGY-001"
    }

    resp = client.post("/api/tickets", json=payload, headers={"X-User-Id": "USR-101"})
    assert resp.status_code == 201
    data = resp.json()

    assert data["priority"] == "Urgent"
    assert data["status"] == "Escalated"
    assert data["assigned_to"] == DEFAULT_ESCALATION_MANAGER_ID
    assert "Tier-1 Emergency Bypass" in data["routing_reason"]

    ticket_id = data["id"]

    # Verify audit log exists
    audit = db_session.query(AuditLog).filter(
        AuditLog.ticket_id == ticket_id,
        AuditLog.action == "ticket.emergency_bypass"
    ).first()
    assert audit is not None
    assert "Tier-1 Emergency Bypass" in audit.details

    # Verify internal note exists
    note = db_session.query(TicketMessage).filter(
        TicketMessage.ticket_id == ticket_id,
        TicketMessage.message_type == "InternalNote"
    ).first()
    assert note is not None
    assert "[Emergency Bypass]" in note.content


def test_requester_supplied_intent_ignored_and_classified_server_side(client: TestClient):
    """
    SECTION 1.2:
    The intent sent by a Requester in POST /api/tickets must be ignored;
    classify server-side with suggest_ticket_intent(payload.title, payload.description).
    """
    with main_module._rate_limit_lock:
        main_module._rate_limit_records.clear()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    checkin_3h = now + timedelta(hours=3)

    # Requester sends intent="Emergency Check-in Assist" with non-emergency content (e.g. bed preference)
    payload = {
        "title": "Need twin beds in hotel room",
        "description": "Please ensure twin bed configuration on high floor",
        "tboh_id": f"TBOH-REQ-{uuid.uuid4().hex[:6].upper()}",
        "priority": "Low",
        "check_in_date": checkin_3h.isoformat(),
        "intent": "Emergency Check-in Assist",  # Client tries to claim emergency intent
    }

    resp = client.post("/api/tickets", json=payload, headers={"X-User-Id": "USR-201"})
    assert resp.status_code == 201
    data = resp.json()

    # Client-supplied intent must have been IGNORED; classified server-side to Bedding / Room Preference
    assert data["intent"] != "Emergency Check-in Assist"
    assert data["intent"] == "Bedding / Room Preference"
    assert data["priority"] == "Low"
    assert data["status"] in ["Open", "New"]
    assert data["assigned_to"] != DEFAULT_ESCALATION_MANAGER_ID


def test_staff_supplied_intent_allowed(client: TestClient):
    """
    SECTION 1.2:
    Staff-supplied intent stays allowed (use payload.intent if provided).
    """
    with main_module._rate_limit_lock:
        main_module._rate_limit_records.clear()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    checkin_far = now + timedelta(days=10)

    payload = {
        "title": "General customer inquiry",
        "description": "Customer asked about details",
        "tboh_id": f"TBOH-STF-{uuid.uuid4().hex[:6].upper()}",
        "priority": "Medium",
        "check_in_date": checkin_far.isoformat(),
        "intent": "Cancellation Inconvenience",  # Explicit staff intent
        "agency_id": "AGY-001"
    }

    resp = client.post("/api/tickets", json=payload, headers={"X-User-Id": "USR-101"})
    assert resp.status_code == 201
    data = resp.json()

    # Staff-provided intent is preserved
    assert data["intent"] == "Cancellation Inconvenience"


def test_user_ticket_create_rate_limit_25_requests(client: TestClient):
    """
    SECTION 1.3:
    One Requester creating 25 tickets in a row gets 429 after the 10th
    and none is assigned to USR-103.
    Returns HTTP 429 with Retry-After header ('60') and detail:
    'Rate limit exceeded: too many tickets created'.
    """
    with main_module._rate_limit_lock:
        main_module._rate_limit_records.clear()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    checkin_3h = now + timedelta(hours=3)

    responses = []
    created_tickets = []

    for i in range(25):
        payload = {
            "title": f"Rate limit test request {i}",
            "description": f"Testing ticket creation rate limits under load {i}",
            "tboh_id": f"TBOH-RL-{i:03d}-{uuid.uuid4().hex[:4].upper()}",
            "priority": "Medium",
            "check_in_date": checkin_3h.isoformat(),
            "intent": "Emergency Check-in Assist"
        }
        resp = client.post("/api/tickets", json=payload, headers={"X-User-Id": "USR-201"})
        responses.append(resp)
        if resp.status_code == 201:
            created_tickets.append(resp.json())

    # Exactly 10 succeed
    assert len(created_tickets) == 10
    for resp in responses[:10]:
        assert resp.status_code == 201

    # Requests 11 through 25 are rate limited with 429
    for resp in responses[10:]:
        assert resp.status_code == 429
        assert resp.headers.get("retry-after") == "60"
        assert resp.json()["detail"] == "Rate limit exceeded: too many tickets created"

    # None of the created tickets is assigned to USR-103
    for t in created_tickets:
        assert t["assigned_to"] != DEFAULT_ESCALATION_MANAGER_ID


def test_agency_ticket_create_rate_limit(client: TestClient, monkeypatch):
    """
    SECTION 1.3:
    Agency rate limit env-configurable via RATE_LIMIT_TICKET_CREATE_AGENCY_PER_HOUR.
    When exceeded, returns HTTP 429 with Retry-After: 3600.
    """
    with main_module._rate_limit_lock:
        main_module._rate_limit_records.clear()

    monkeypatch.setenv("RATE_LIMIT_TICKET_CREATE_USER_PER_MINUTE", "100")
    monkeypatch.setenv("RATE_LIMIT_TICKET_CREATE_AGENCY_PER_HOUR", "3")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    checkin = now + timedelta(days=2)

    for i in range(3):
        payload = {
            "title": f"Agency rate limit test {i}",
            "description": f"Description for ticket {i}",
            "tboh_id": f"TBOH-AGY-RL-{i:03d}-{uuid.uuid4().hex[:4].upper()}",
            "priority": "Low",
            "check_in_date": checkin.isoformat(),
        }
        resp = client.post("/api/tickets", json=payload, headers={"X-User-Id": "USR-201"})
        assert resp.status_code == 201

    # 4th ticket from AGY-001 exceeds agency hourly rate limit
    payload_4 = {
        "title": "Agency rate limit test 4",
        "description": "Description for 4th ticket",
        "tboh_id": f"TBOH-AGY-RL-004-{uuid.uuid4().hex[:4].upper()}",
        "priority": "Low",
        "check_in_date": checkin.isoformat(),
    }
    resp_4 = client.post("/api/tickets", json=payload_4, headers={"X-User-Id": "USR-201"})
    assert resp_4.status_code == 429
    assert resp_4.headers.get("retry-after") == "3600"
    assert resp_4.json()["detail"] == "Rate limit exceeded: too many tickets created"


def test_requester_cross_agency_access_returns_404_no_existence_leak(client: TestClient):
    """
    SECTION 1.4:
    When a Requester asks for a ticket of another agency return 404 (no existence leak):
    - GET /api/tickets/{ticket_id}: if requester != agency -> 404 Ticket not found
    - POST /api/tickets/{ticket_id}/messages: if requester != agency -> 404 Ticket not found
    - Non-existent ticket returns identical 404
    - Role-denied staff actions (internal note on own ticket) still return 403
    """
    # TCK-1004 belongs to AGY-001. USR-202 belongs to AGY-002.
    # 1. GET other agency ticket -> 404
    get_resp = client.get("/api/tickets/TCK-1004", headers={"X-User-Id": "USR-202"})
    assert get_resp.status_code == 404
    assert get_resp.json()["detail"] == "Ticket not found"

    # 2. POST message to other agency ticket -> 404
    post_resp = client.post(
        "/api/tickets/TCK-1004/messages",
        json={"message_type": "PublicReply", "content": "Attempting cross-agency reply"},
        headers={"X-User-Id": "USR-202"}
    )
    assert post_resp.status_code == 404
    assert post_resp.json()["detail"] == "Ticket not found"

    # 3. Non-existent ticket returns identical 404 (zero existence leak)
    non_existent = client.get("/api/tickets/TCK-NONEXISTENT-9999", headers={"X-User-Id": "USR-202"})
    assert non_existent.status_code == 404
    assert non_existent.json() == get_resp.json()

    # 4. Requester on own ticket posting InternalNote receives 403 Forbidden
    own_ticket_note = client.post(
        "/api/tickets/TCK-1004/messages",
        json={"message_type": "InternalNote", "content": "Illegal internal note attempt"},
        headers={"X-User-Id": "USR-201"}  # USR-201 belongs to AGY-001 (same agency)
    )
    assert own_ticket_note.status_code == 403
    assert "Forbidden" in own_ticket_note.json()["detail"]

    # 5. Requester calling staff-only action endpoints still receives 403 Forbidden
    assert client.post("/api/tickets/TCK-1004/status", json={"status": "Pending"}, headers={"X-User-Id": "USR-201"}).status_code == 403
    assert client.post("/api/tickets/TCK-1004/assign", json={"agent_id": "USR-101"}, headers={"X-User-Id": "USR-201"}).status_code == 403
    assert client.post("/api/tickets/TCK-1004/unassign", headers={"X-User-Id": "USR-201"}).status_code == 403
    assert client.post("/api/tickets/TCK-1004/escalate", json={"reason": "Customer complaint"}, headers={"X-User-Id": "USR-201"}).status_code == 403
    assert client.get("/api/tickets/TCK-1004/side-threads", headers={"X-User-Id": "USR-201"}).status_code == 403

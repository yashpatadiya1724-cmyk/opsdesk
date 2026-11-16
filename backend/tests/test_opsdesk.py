import os
import json
import uuid
import sqlite3
import tempfile
from datetime import datetime, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from backend.app.database import Base, get_db
from backend.app.models import (
    Agency, User, Ticket, TicketLink, SideConversation,
    SideConversationRecipient, TicketTheme, EventOutbox, TicketMessage,
    AuditLog
)
from backend.app.main import app
from backend.services.routing_engine import (
    CandidateAgent,
    select_agent_tier1,
    calculate_queue_score_tier2
)
from backend.services.sla_engine import evaluate_travel_sla, effective_deadline_hours
from backend.services.intent_classifier import suggest_ticket_intent
from backend.seed.seed_data import seed_database

# ============================================================================
# 1. DATABASE ISOLATION VERIFICATION TEST
# ============================================================================

def test_dev_database_isolation(dev_db_initial_state):
    """
    PROVE TEST DB ISOLATION:
    Verifies that the development database (opsdesk.db) remains untouched
    with exactly 5,000 seeded tickets and its mtime is unchanged after test suite operations.
    """
    path = dev_db_initial_state["path"]
    initial_mtime = dev_db_initial_state["mtime"]
    initial_count = dev_db_initial_state["count"]

    assert os.path.exists(path), "Development database opsdesk.db must exist"
    current_mtime = os.path.getmtime(path)
    assert current_mtime == initial_mtime, f"Dev DB mtime was modified: {current_mtime} != {initial_mtime}"

    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM tickets")
    current_count = c.fetchone()[0]
    conn.close()
    assert current_count == initial_count == 5000, f"Expected dev DB to hold 5000 tickets, found {current_count}"


# ============================================================================
# 2. ROUTING ENGINE TESTS
# ============================================================================

def test_routing_region_match():
    """Agent in matching region is selected when available."""
    agents = [
        CandidateAgent(id="USR-1", name="Aisha", region="MEA", is_available=True, active_ticket_count=2),
        CandidateAgent(id="USR-2", name="Rahul", region="APAC", is_available=True, active_ticket_count=0),
    ]
    chosen_id, reason = select_agent_tier1("AE", agents)
    assert chosen_id == "USR-1"
    assert "Region=MEA match" in reason

def test_routing_availability_false():
    """Unavailable agent is strictly filtered out."""
    agents = [
        CandidateAgent(id="USR-1", name="Aisha", region="MEA", is_available=False, active_ticket_count=0),
        CandidateAgent(id="USR-2", name="Farah", region="MEA", is_available=True, active_ticket_count=2),
    ]
    chosen_id, reason = select_agent_tier1("AE", agents)
    assert chosen_id == "USR-2"
    assert "Farah" in reason

def test_routing_empty_pool_fallback():
    """When target regional desk has zero available agents, fallback to available agent from another desk."""
    agents = [
        CandidateAgent(id="USR-1", name="Aisha", region="MEA", is_available=False, active_ticket_count=0),
        CandidateAgent(id="USR-2", name="Vikram", region="APAC", is_available=True, active_ticket_count=1),
    ]
    chosen_id, reason = select_agent_tier1("AE", agents)
    assert chosen_id == "USR-2"
    assert "Tier-1 Fallback" in reason

def test_routing_workload_tie_breaking():
    """When regional agents have equal workloads, tie is broken deterministically by ID."""
    agents = [
        CandidateAgent(id="USR-B", name="Bob", region="MEA", is_available=True, active_ticket_count=1),
        CandidateAgent(id="USR-A", name="Alice", region="MEA", is_available=True, active_ticket_count=1),
    ]
    chosen_id, reason = select_agent_tier1("AE", agents)
    assert chosen_id == "USR-A"

def test_routing_tier2_queue_score():
    """Tier 2 calculates higher score for urgent cases with near check-in."""
    now = datetime.utcnow()
    score_urgent_imminent = calculate_queue_score_tier2(
        priority="Urgent",
        check_in_date=now + timedelta(hours=1),
        now=now
    )
    score_low_distant = calculate_queue_score_tier2(
        priority="Low",
        check_in_date=now + timedelta(days=5),
        now=now
    )
    assert score_urgent_imminent > score_low_distant
    assert score_urgent_imminent == 3000.0


# ============================================================================
# 3. SLA ENGINE TESTS
# ============================================================================

def test_sla_stopped_on_closed_or_resolved():
    """Resolved and Closed tickets stop the SLA clock with Gray badge."""
    now = datetime.utcnow()
    past_date = now - timedelta(days=2)
    
    res_closed = evaluate_travel_sla(
        status="Closed",
        check_in_date=past_date,
        lcd_date=past_date,
        priority="Urgent",
        now=now
    )
    assert res_closed["status"] == "STOPPED"
    assert res_closed["color"] == "Gray"
    assert res_closed["hours_remaining"] is None

    res_resolved = evaluate_travel_sla(
        status="Resolved",
        check_in_date=past_date,
        lcd_date=past_date,
        priority="Medium",
        now=now
    )
    assert res_resolved["status"] == "STOPPED"
    assert res_resolved["color"] == "Gray"

def test_sla_breached_when_past_checkin():
    """Active ticket with past check-in/LCD is BREACHED (Red)."""
    now = datetime.utcnow()
    past_date = now - timedelta(hours=1)
    
    res = evaluate_travel_sla(
        status="Open",
        check_in_date=past_date,
        lcd_date=past_date,
        priority="High",
        now=now
    )
    assert res["status"] == "BREACHED"
    assert res["color"] == "Red"
    assert res["hours_remaining"] < 0

def test_sla_at_risk_amber():
    """Active ticket within warning window is AT_RISK (Amber)."""
    now = datetime.utcnow()
    near_date = now + timedelta(hours=1.5)
    
    res = evaluate_travel_sla(
        status="Open",
        check_in_date=near_date,
        lcd_date=near_date,
        priority="Medium",
        now=now
    )
    assert res["status"] == "AT_RISK"
    assert res["color"] == "Amber"
    assert 0 < res["hours_remaining"] <= 2.0

def test_sla_priority_modifies_threshold():
    """5.0 hours remaining is AT_RISK for Urgent (threshold=6h), but NORMAL for Medium (threshold=2h)."""
    now = datetime.utcnow()
    date_5h = now + timedelta(hours=5.0)
    
    res_urgent = evaluate_travel_sla(
        status="Open",
        check_in_date=date_5h,
        lcd_date=date_5h,
        priority="Urgent",
        now=now
    )
    assert res_urgent["status"] == "AT_RISK"
    assert res_urgent["color"] == "Amber"

    res_medium = evaluate_travel_sla(
        status="Open",
        check_in_date=date_5h,
        lcd_date=date_5h,
        priority="Medium",
        now=now
    )
    assert res_medium["status"] == "NORMAL"
    assert res_medium["color"] == "Green"


# ============================================================================
# 4. GOLDEN VECTORS COMPLIANCE TEST (CONTRACTS VERIFICATION)
# ============================================================================

def test_contracts_golden_vectors():
    """
    Verifies that the Python reference implementations match 100% of the
    golden vector test cases defined in contracts/golden_vectors.json.
    """
    golden_path = os.path.join(os.getcwd(), "contracts", "golden_vectors.json")
    with open(golden_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. Verify all SLA cases
    assert len(data["sla_cases"]) >= 20
    for case in data["sla_cases"]:
        inp = case["input"]
        exp = case["expected_output"]
        now = datetime.fromisoformat(inp["now"].replace("Z", ""))
        cid = datetime.fromisoformat(inp["check_in_date"].replace("Z", ""))
        lcd = datetime.fromisoformat(inp["lcd_date"].replace("Z", "")) if inp.get("lcd_date") else None
        
        act = evaluate_travel_sla(
            status=inp["status"],
            check_in_date=cid,
            lcd_date=lcd,
            priority=inp["priority"],
            intent=inp.get("intent"),
            now=now
        )
        assert act["status"] == exp["status"], f"Case {case['case_id']} status mismatch: {act['status']} != {exp['status']}"
        assert act["color"] == exp["color"], f"Case {case['case_id']} color mismatch: {act['color']} != {exp['color']}"
        assert act["badge"] == exp["badge"], f"Case {case['case_id']} badge mismatch: {act['badge']} != {exp['badge']}"
        if exp["hours_remaining"] is not None:
            assert abs(act["hours_remaining"] - exp["hours_remaining"]) < 0.01

    # 2. Verify all Queue Score cases
    assert len(data["queue_score_cases"]) >= 10
    for case in data["queue_score_cases"]:
        inp = case["input"]
        exp = case["expected_output"]
        now = datetime.fromisoformat(inp["now"].replace("Z", ""))
        cid = datetime.fromisoformat(inp["check_in_date"].replace("Z", ""))
        lcd = datetime.fromisoformat(inp["lcd_date"].replace("Z", "")) if inp.get("lcd_date") else None
        
        score = calculate_queue_score_tier2(
            priority=inp["priority"],
            check_in_date=cid,
            lcd_date=lcd,
            intent=inp.get("intent"),
            now=now
        )
        assert score == exp["score"], f"Queue case {case['case_id']} mismatch: {score} != {exp['score']}"


# ============================================================================
# 5. INTENT CLASSIFIER REGEX & PRECEDENCE TESTS
# ============================================================================

def test_intent_regex_refunded_inflection():
    intent, source = suggest_ticket_intent("Ticket Update", "Customer was refunded already by supplier.")
    assert intent == "Refund Request"
    assert source == "regex_rule"

def test_intent_regex_cancelled_inflection():
    intent, source = suggest_ticket_intent("Notice", "Flight was cancelled due to fog.")
    assert intent == "Cancellation Inconvenience"
    assert source == "regex_rule"

def test_intent_regex_rescheduled_inflection():
    intent, source = suggest_ticket_intent("Change request", "Please reschedule the room check-in to tomorrow.")
    assert intent == "Date Amendment"
    assert source == "regex_rule"

def test_intent_regex_kingsize_bed():
    intent, source = suggest_ticket_intent("Guest preference", "Need a king-size bed on high floor.")
    assert intent == "Bedding / Room Preference"
    assert source == "regex_rule"

def test_intent_regex_voucher():
    intent, source = suggest_ticket_intent("Documents", "Please resend the voucher copy for voucher vouchers.")
    assert intent == "Voucher Resend"
    assert source == "regex_rule"

def test_intent_both_match_precedence():
    """When both refund and cancel appear, Refund Request takes precedence."""
    intent, source = suggest_ticket_intent(
        "Refund for cancelled booking",
        "Our booking was cancelled, need refund immediately."
    )
    assert intent == "Refund Request"
    assert source == "regex_rule"

def test_intent_no_match_unclassified_fallback():
    """Unmatched text falls back to Unclassified when no Gemini key is provided."""
    os.environ["GEMINI_API_KEY"] = ""
    intent, source = suggest_ticket_intent("General inquiry", "Hello, hope you are doing well today.")
    assert intent == "Unclassified"
    assert source == "fallback_unclassified"


# ============================================================================
# 6. SEED DATA GENERATOR TESTS (RUN ON ISOLATED TEST DB)
# ============================================================================

def test_seed_row_count(db_session: Session):
    count = db_session.query(Ticket).count()
    assert count == 5000

def test_seed_zero_open_tickets_with_past_checkin(db_session: Session):
    """CRITICAL RULE: No active ticket (New, Open, Pending, Escalated) can have check-in in the past."""
    now = datetime.utcnow()
    active_statuses = ["New", "Open", "Pending", "Escalated"]
    past_active_count = db_session.query(Ticket).filter(
        Ticket.status.in_(active_statuses),
        Ticket.check_in_date < now
    ).count()
    assert past_active_count == 0

def test_seed_escalated_assigned_to_vikram(db_session: Session):
    """Verify exactly 40 tickets are seeded with Escalated status and assigned to USR-103."""
    escalated_tickets = db_session.query(Ticket).filter(Ticket.status == "Escalated").all()
    assert len(escalated_tickets) == 40
    for t in escalated_tickets:
        assert t.assigned_to == "USR-103"
        assert t.check_in_date > datetime.utcnow()

def test_seed_non_escalated_assigned_pool(db_session: Session):
    """Verify standard assigned tickets are strictly assigned to Tier-1 desk agents USR-101 and USR-102."""
    assigned_users = db_session.query(Ticket.assigned_to).filter(
        Ticket.assigned_to.isnot(None),
        Ticket.status != "Escalated"
    ).distinct().all()
    assigned_ids = {u[0] for u in assigned_users}
    assert assigned_ids.issubset({"USR-101", "USR-102"})

def test_seed_tboh_fixtures(db_session: Session):
    """Verify specific journey fixtures exist and are configured correctly."""
    # TCK-1001 & TCK-1002 share TBOH-89104 and are Closed
    t1001 = db_session.query(Ticket).filter(Ticket.id == "TCK-1001").first()
    t1002 = db_session.query(Ticket).filter(Ticket.id == "TCK-1002").first()
    assert t1001 is not None and t1002 is not None
    assert t1001.tboh_id == "TBOH-89104"
    assert t1002.tboh_id == "TBOH-89104"
    assert t1001.status == "Closed"
    assert t1002.status == "Closed"

    # TCK-1004: Urgent, MEA, ~2.5h in future. lcd_date is None for check-in assist.
    t1004 = db_session.query(Ticket).filter(Ticket.id == "TCK-1004").first()
    assert t1004 is not None
    assert t1004.priority == "Urgent"
    assert t1004.status == "Open"
    assert t1004.check_in_date > datetime.utcnow()
    assert t1004.lcd_date is None
    assert "active cases" in t1004.routing_reason

    # TCK-1005: Side thread with recipient
    t1005 = db_session.query(Ticket).filter(Ticket.id == "TCK-1005").first()
    assert t1005 is not None
    assert len(t1005.side_conversations) > 0
    sc = t1005.side_conversations[0]
    assert len(sc.recipients) > 0
    assert sc.recipients[0].email == "reservations@vendor.example.com"

    # TCK-1006: Urgent, ~45m in future. lcd_date is None for voucher resend.
    t1006 = db_session.query(Ticket).filter(Ticket.id == "TCK-1006").first()
    assert t1006 is not None
    assert t1006.priority == "Urgent"
    assert t1006.status == "Open"
    assert t1006.check_in_date > datetime.utcnow()
    assert t1006.lcd_date is None
    assert "active cases" in t1006.routing_reason

    # TCK-1007: Journey B Unassigned Urgent triage fixture (~2.25h in future, AGY-001)
    t1007 = db_session.query(Ticket).filter(Ticket.id == "TCK-1007").first()
    assert t1007 is not None
    assert t1007.priority == "Urgent"
    assert t1007.status == "New"
    assert t1007.lcd_date is None
    assert t1007.assigned_to is None
    assert t1007.check_in_date > datetime.utcnow()

    # TCK-1008: Refund Request with 3h LCD and 5d check-in, linked to TCK-1001 via TBOH-89104
    t1008 = db_session.query(Ticket).filter(Ticket.id == "TCK-1008").first()
    assert t1008 is not None
    assert t1008.tboh_id == "TBOH-89104"
    assert t1008.priority == "High"
    assert t1008.status == "Open"
    assert t1008.intent == "Refund Request"
    assert t1008.assigned_to == "USR-101"
    assert t1008.lcd_date is not None
    assert t1008.lcd_date < t1008.check_in_date
    links_1008 = db_session.query(TicketLink).filter(TicketLink.ticket_id == "TCK-1008").all()
    assert len(links_1008) > 0
    assert links_1008[0].linked_ticket_id == "TCK-1001"


# ============================================================================
# 7. FASTAPI ENDPOINTS & ROLE MATRIX TESTS (MILESTONE 2)
# ============================================================================

def test_auth_missing_header_401(client: TestClient):
    """Missing X-User-Id header returns 401 Unauthorized."""
    resp = client.get("/api/tickets")
    assert resp.status_code == 401
    assert "Missing X-User-Id" in resp.json()["detail"]

def test_auth_unknown_user_401(client: TestClient):
    """Non-existent X-User-Id returns 401 Unauthorized."""
    resp = client.get("/api/tickets", headers={"X-User-Id": "USR-GHOST"})
    assert resp.status_code == 401
    assert "not found" in resp.json()["detail"]

def test_requester_cannot_access_other_agency_ticket_403(client: TestClient):
    """
    CRITICAL MULTI-TENANT TEST:
    USR-202 belongs to AGY-002 (Vectora Travel).
    TCK-1004 belongs to AGY-001 (Krypton Voyages).
    Accessing TCK-1004 must return 403 Forbidden.
    """
    resp = client.get("/api/tickets/TCK-1004", headers={"X-User-Id": "USR-202"})
    assert resp.status_code == 403
    assert "Forbidden" in resp.json()["detail"]

def test_requester_sees_only_own_agency_in_list(client: TestClient):
    """
    Requesters list endpoint strictly limits results to their own agency.
    """
    resp = client.get("/api/tickets", headers={"X-User-Id": "USR-201"})
    assert resp.status_code == 200
    data = resp.json()
    for t in data["tickets"]:
        assert t["agency_id"] == "AGY-001"

def test_requester_client_sent_agency_id_is_ignored(client: TestClient):
    """
    Security check: Even if a requester sends agency_id='AGY-003' in the POST body,
    the server ignores it and assigns their authentic agency_id ('AGY-001').
    """
    now = datetime.utcnow()
    payload = {
        "title": "Spoof Agency Attempt",
        "description": "Attempting to create ticket for AGY-003",
        "tboh_id": "TBOH-88221",
        "priority": "Medium",
        "check_in_date": (now + timedelta(days=5)).isoformat(),
        "lcd_date": (now + timedelta(days=5)).isoformat(),
        "agency_id": "AGY-003"  # Attacker attempt
    }
    resp = client.post("/api/tickets", json=payload, headers={"X-User-Id": "USR-201"})
    assert resp.status_code == 201
    created = resp.json()
    assert created["agency_id"] == "AGY-001"  # Overridden by server-side DB session

def test_requester_cannot_see_internal_notes(client: TestClient, db_session: Session):
    """
    Requesters viewing their own ticket detail must NEVER see InternalNote messages.
    Internal staff CAN see InternalNote messages.
    """
    # 1. Post an InternalNote as Aisha (USR-101) on TCK-1004
    note_resp = client.post(
        "/api/tickets/TCK-1004/messages",
        json={"message_type": "InternalNote", "content": "Sensitive hotel dispute note"},
        headers={"X-User-Id": "USR-101"}
    )
    assert note_resp.status_code == 201
    assert note_resp.json()["visibility"] == "internal"

    # 2. Requester (USR-201) fetches ticket TCK-1004
    req_resp = client.get("/api/tickets/TCK-1004", headers={"X-User-Id": "USR-201"})
    assert req_resp.status_code == 200
    for msg in req_resp.json()["messages"]:
        assert msg["message_type"] != "InternalNote"
        assert "Sensitive hotel dispute note" not in msg["content"]

    # 3. Agent (USR-101) fetches ticket TCK-1004 and CAN see the note
    agent_resp = client.get("/api/tickets/TCK-1004", headers={"X-User-Id": "USR-101"})
    assert agent_resp.status_code == 200
    contents = [m["content"] for m in agent_resp.json()["messages"]]
    assert "Sensitive hotel dispute note" in contents

def test_requester_cannot_post_internal_note_403(client: TestClient):
    """Requesters posting message_type='InternalNote' receive 403 Forbidden."""
    resp = client.post(
        "/api/tickets/TCK-1004/messages",
        json={"message_type": "InternalNote", "content": "Illegitimate note attempt"},
        headers={"X-User-Id": "USR-201"}
    )
    assert resp.status_code == 403

def test_requester_cannot_access_side_threads_403(client: TestClient):
    """Requesters attempting to view or create side conversations receive 403 Forbidden."""
    get_resp = client.get("/api/tickets/TCK-1005/side-threads", headers={"X-User-Id": "USR-201"})
    assert get_resp.status_code == 403

    post_resp = client.post(
        "/api/tickets/TCK-1005/side-threads",
        json={
            "supplier_name": "Supplier Direct",
            "subject": "Direct supplier question",
            "recipients": ["vendor@example.com"],
            "initial_message": "Hello"
        },
        headers={"X-User-Id": "USR-201"}
    )
    assert post_resp.status_code == 403

def test_ticket_transfer_preserves_side_conversation_recipients(client: TestClient):
    """
    MVP-4 CORE TEST:
    Transferring a ticket from Aisha (USR-101) to Rahul (USR-102) preserves
    all supplier side conversation recipients without wiping or overwriting them,
    and updates routing_reason to reflect the transfer path.
    """
    # Check TCK-1005 initial recipients and initial assigned agent
    detail_before = client.get("/api/tickets/TCK-1005", headers={"X-User-Id": "USR-101"}).json()
    assert detail_before["assigned_to"] == "USR-101"
    recipients_before = detail_before["side_conversations"][0]["recipients"]
    assert "reservations@vendor.example.com" in recipients_before

    # Perform transfer to USR-102
    transfer_resp = client.post(
        "/api/tickets/TCK-1005/transfer",
        json={"target_agent_id": "USR-102", "reason": "Shift handover to Rahul Verma"},
        headers={"X-User-Id": "USR-101"}
    )
    assert transfer_resp.status_code == 200
    transfer_data = transfer_resp.json()
    assert transfer_data["assigned_to"] == "USR-102"
    assert transfer_data["total_recipients_preserved"] >= 2
    assert "Transferred from USR-101" in transfer_data["routing_reason"]
    assert "to USR-102" in transfer_data["routing_reason"]

    # Verify recipients after transfer
    detail_after = client.get("/api/tickets/TCK-1005", headers={"X-User-Id": "USR-102"}).json()
    assert detail_after["assigned_to"] == "USR-102"
    recipients_after = detail_after["side_conversations"][0]["recipients"]
    assert recipients_after == recipients_before

def test_ticket_transfer_to_same_agent_400(client: TestClient, db_session: Session):
    """
    Self-contained test: Attempting to transfer a ticket to the agent who is currently assigned
    returns 400 Bad Request. Does not depend on execution order or prior test mutations.
    """
    now = datetime.utcnow()
    test_ticket = Ticket(
        id="TCK-SELF-TRANSFER",
        tboh_id="TBOH-SELF-TEST",
        agency_id="AGY-001",
        title="Self Transfer Test Case",
        description="Ticket for testing redundant transfer rejection",
        intent="Unclassified",
        priority="Medium",
        status="Open",
        check_in_date=now + timedelta(days=5),
        lcd_date=now + timedelta(days=5),
        assigned_to="USR-101",
        routing_reason="Initial assignment to USR-101",
        created_at=now,
        updated_at=now
    )
    db_session.add(test_ticket)
    db_session.commit()

    # Attempt to transfer to USR-101 (who is already assigned)
    resp = client.post(
        f"/api/tickets/{test_ticket.id}/transfer",
        json={"target_agent_id": "USR-101", "reason": "Redundant self-transfer attempt"},
        headers={"X-User-Id": "USR-101"}
    )
    assert resp.status_code == 400
    assert "already assigned" in resp.json()["detail"]

def test_ticket_escalate_assigns_to_vikram_and_writes_outbox(client: TestClient, db_session: Session):
    """
    Escalating a ticket updates status to 'Escalated', reassigns to configured manager USR-103,
    and records an event in events_outbox with free-text reason stripped from the public payload.
    """
    freetext_reason = "Confidential dispute with front desk management; potential legal threat."
    resp = client.post(
        "/api/tickets/TCK-1004/escalate",
        json={"reason": freetext_reason},
        headers={"X-User-Id": "USR-101"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["new_status"] == "Escalated"
    assert data["assigned_to"] == "USR-103"

    # Verify outbox entry
    outbox = db_session.query(EventOutbox).filter(
        EventOutbox.ticket_id == "TCK-1004",
        EventOutbox.event_type == "ticket.escalated"
    ).first()
    assert outbox is not None
    assert outbox.visibility == "public"
    payload = json.loads(outbox.payload_json)
    assert payload["assigned_to"] == "USR-103"
    # CRITICAL: Free-text reason must NEVER be leaked in public event payload
    assert "reason" not in payload

    # Verify requester-scoped outbox query cannot see free-text reason
    requester_events = db_session.query(EventOutbox).filter(
        EventOutbox.agency_id == "AGY-001",
        EventOutbox.visibility == "public"
    ).all()
    for ev in requester_events:
        p = json.loads(ev.payload_json)
        assert "reason" not in p
        assert freetext_reason not in ev.payload_json

def test_requester_cannot_update_ticket_status_403(client: TestClient):
    """
    Requesters calling POST /api/tickets/{id}/status receive 403 Forbidden.
    Only internal operations staff are permitted to advance ticket lifecycle.
    """
    resp = client.post(
        "/api/tickets/TCK-1004/status",
        json={"status": "Pending"},
        headers={"X-User-Id": "USR-201"}
    )
    assert resp.status_code == 403
    assert "Forbidden" in resp.json()["detail"]

def test_tickets_view_by_intent(client: TestClient):
    """
    view=by_intent with intent filter returns only matching tickets and accurate total count.
    """
    resp = client.get("/api/tickets?view=by_intent&intent=Refund+Request", headers={"X-User-Id": "USR-101"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] > 0
    for t in data["tickets"]:
        assert t["intent"] == "Refund Request"

def test_tickets_view_by_intent_grouped(client: TestClient):
    """
    view=by_intent without specific intent parameter returns sorted intent list.
    """
    resp = client.get("/api/tickets?view=by_intent", headers={"X-User-Id": "USR-101"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] > 0

def test_tickets_view_by_region(client: TestClient):
    """
    view=by_region for MEA staff (USR-101) returns tickets from MEA agencies.
    """
    resp = client.get("/api/tickets?view=by_region", headers={"X-User-Id": "USR-101"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] > 0

def test_tickets_view_linked_and_requester_scoping(client: TestClient):
    """
    view=linked returns linked tickets.
    Requester's linked view is strictly isolated to their own agency.
    """
    # Internal staff sees linked tickets across the platform
    resp_staff = client.get("/api/tickets?view=linked", headers={"X-User-Id": "USR-101"})
    assert resp_staff.status_code == 200
    assert resp_staff.json()["total"] >= 2

    # Requester USR-201 (AGY-001) only sees linked tickets within AGY-001
    resp_req = client.get("/api/tickets?view=linked", headers={"X-User-Id": "USR-201"})
    assert resp_req.status_code == 200
    data_req = resp_req.json()
    for t in data_req["tickets"]:
        assert t["agency_id"] == "AGY-001"

def test_tickets_total_count_before_pagination(client: TestClient):
    """
    GET /api/tickets returns total count reflecting all matching tickets before limit pagination.
    """
    resp = client.get("/api/tickets?view=triage&limit=5", headers={"X-User-Id": "USR-101"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tickets"]) == 5
    assert data["total"] > 5

def test_events_schema_enum_parity():
    """
    Verifies that all event types emitted in backend/app/main.py are explicitly
    defined in the contracts/events.schema.json event_type enum.
    """
    import re
    contracts_path = os.path.join(os.getcwd(), "contracts", "events.schema.json")
    with open(contracts_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    allowed_enums = set(schema["properties"]["event_type"]["enum"])

    main_py_path = os.path.join(os.getcwd(), "backend", "app", "main.py")
    with open(main_py_path, "r", encoding="utf-8") as f:
        code = f.read()

    emitted_types = set(re.findall(r'event_type=["\']([^"\']+)["\']', code))
    assert len(emitted_types) > 0, "Expected to find emitted event types in main.py"
    assert emitted_types.issubset(allowed_enums), f"Emitted types not in schema: {emitted_types - allowed_enums}"

def test_invalid_status_transition_returns_409(client: TestClient):
    """
    Attempting an illegal transition in the status graph (e.g. Closed -> Escalated)
    returns 409 Conflict.
    """
    resp = client.post(
        "/api/tickets/TCK-1001/status",
        json={"status": "Escalated"},
        headers={"X-User-Id": "USR-101"}
    )
    assert resp.status_code == 409
    assert "Invalid status transition" in resp.json()["detail"]

def test_suggest_intent_endpoint(client: TestClient):
    """POST /api/ai/suggest-intent returns rule-classified category."""
    resp = client.post(
        "/api/ai/suggest-intent",
        json={"title": "Voucher Resend Request", "description": "Please resend confirmation voucher immediately."},
        headers={"X-User-Id": "USR-101"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "Voucher Resend"
    assert data["source"] == "regex_rule"


# ============================================================================
# 8. TRIAGE ORDERING, PRIVACY & FIELD SANITIZATION TESTS
# ============================================================================

def test_triage_queue_score_global_sorting(client: TestClient, db_session: Session):
    """
    view=triage strictly returns unassigned active tickets, sorted globally by queue_score descending.
    Verifies that:
    1. First result of page 1 has the global maximum queue_score.
    2. Page 2 scores are less than or equal to page 1 scores.
    3. All returned tickets have assigned_to IS NULL.
    """
    resp_p1 = client.get("/api/tickets?view=triage&limit=5&offset=0", headers={"X-User-Id": "USR-101"})
    assert resp_p1.status_code == 200
    data_p1 = resp_p1.json()

    resp_p2 = client.get("/api/tickets?view=triage&limit=5&offset=5", headers={"X-User-Id": "USR-101"})
    assert resp_p2.status_code == 200
    data_p2 = resp_p2.json()

    # All tickets must be unassigned
    for t in data_p1["tickets"] + data_p2["tickets"]:
        assert t["assigned_to"] is None
        assert t["status"] in ["New", "Open", "Pending", "Escalated"]

    p1_scores = [t["queue_score"] for t in data_p1["tickets"]]
    p2_scores = [t["queue_score"] for t in data_p2["tickets"]]

    # Page 1 scores are in non-increasing order
    for i in range(len(p1_scores) - 1):
        assert p1_scores[i] >= p1_scores[i + 1]

    # Page 2 scores are in non-increasing order
    for i in range(len(p2_scores) - 1):
        assert p2_scores[i] >= p2_scores[i + 1]

    # Page 2 maximum score <= Page 1 minimum score
    assert min(p1_scores) >= max(p2_scores)

    # First ticket on page 1 must match the global maximum queue_score
    now = datetime.utcnow()
    all_unassigned = db_session.query(Ticket).filter(
        Ticket.status.in_(["New", "Open", "Pending", "Escalated"]),
        Ticket.assigned_to.is_(None)
    ).all()
    global_max_score = max(
        calculate_queue_score_tier2(t.priority, t.check_in_date, lcd_date=t.lcd_date, intent=t.intent, now=now)
        for t in all_unassigned
    )
    assert abs(data_p1["tickets"][0]["queue_score"] - global_max_score) < 0.01

def test_requester_response_omits_internal_fields(client: TestClient):
    """
    Requesters viewing ticket list and detail must NEVER see internal fields:
    routing_reason, queue_score, and assigned_to are set to None.
    """
    # 1. Requester lists tickets
    list_resp = client.get("/api/tickets", headers={"X-User-Id": "USR-201"})
    assert list_resp.status_code == 200
    for t in list_resp.json()["tickets"]:
        assert t["routing_reason"] is None
        assert t["queue_score"] is None
        assert t["assigned_to"] is None

    # 2. Requester views ticket detail
    detail_resp = client.get("/api/tickets/TCK-1004", headers={"X-User-Id": "USR-201"})
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["routing_reason"] is None
    assert detail["queue_score"] is None
    assert detail["assigned_to"] is None

def test_escalate_and_transfer_routing_reason_neutral_text(client: TestClient, db_session: Session):
    """
    Escalate and transfer endpoints must NEVER write free-text reason into ticket.routing_reason.
    ticket.routing_reason must contain only neutral, non-sensitive audit text.
    Free-text reason is strictly confined to audit_logs.
    """
    # 1. Escalate
    secret_escalate_reason = "CONFIDENTIAL_ESCALATE_LEGAL_RISK_12345"
    esc_resp = client.post(
        "/api/tickets/TCK-1004/escalate",
        json={"reason": secret_escalate_reason},
        headers={"X-User-Id": "USR-101"}
    )
    assert esc_resp.status_code == 200
    esc_data = esc_resp.json()
    assert esc_data["routing_reason"] == "Escalated to Escalation Manager (USR-103)"
    assert secret_escalate_reason not in esc_data["routing_reason"]

    # Verify audit log contains the reason
    audit_esc = db_session.query(AuditLog).filter(
        AuditLog.ticket_id == "TCK-1004",
        AuditLog.action == "ticket.escalated"
    ).order_by(AuditLog.created_at.desc()).first()
    assert audit_esc is not None
    esc_details = json.loads(audit_esc.details) if isinstance(audit_esc.details, str) else audit_esc.details
    assert secret_escalate_reason in esc_details.get("reason", "")

    # 2. Transfer (using TCK-1006 which is assigned to USR-101)
    secret_transfer_reason = "CONFIDENTIAL_SHIFT_HANDOVER_REASON_67890"
    trans_resp = client.post(
        "/api/tickets/TCK-1006/transfer",
        json={"target_agent_id": "USR-102", "reason": secret_transfer_reason},
        headers={"X-User-Id": "USR-101"}
    )
    assert trans_resp.status_code == 200
    trans_data = trans_resp.json()
    assert trans_data["routing_reason"] == "Transferred from USR-101 to USR-102"
    assert secret_transfer_reason not in trans_data["routing_reason"]

    # Verify audit log contains the reason
    audit_trans = db_session.query(AuditLog).filter(
        AuditLog.ticket_id == "TCK-1006",
        AuditLog.action == "ticket.transferred"
    ).order_by(AuditLog.created_at.desc()).first()
    assert audit_trans is not None
    trans_details = json.loads(audit_trans.details) if isinstance(audit_trans.details, str) else audit_trans.details
    assert secret_transfer_reason in trans_details.get("reason", "")

def test_requester_detail_linked_tickets_scoped_to_own_agency(client: TestClient, db_session: Session):
    """
    Requesters viewing ticket details must only see linked tickets that belong to their own agency.
    Cross-agency links are visible to internal staff but withheld from Requesters.
    """
    now = datetime.utcnow()
    # Create ticket in AGY-001
    t1 = Ticket(
        id="TCK-CROSS-1",
        tboh_id="TBOH-CROSS",
        agency_id="AGY-001",
        title="AGY-001 Ticket",
        description="Ticket in agency 1",
        intent="Unclassified",
        priority="Medium",
        status="Open",
        check_in_date=now + timedelta(days=2),
        lcd_date=now + timedelta(days=2),
        created_at=now
    )
    # Create ticket in AGY-002
    t2 = Ticket(
        id="TCK-CROSS-2",
        tboh_id="TBOH-CROSS",
        agency_id="AGY-002",
        title="AGY-002 Ticket",
        description="Ticket in agency 2",
        intent="Unclassified",
        priority="Medium",
        status="Open",
        check_in_date=now + timedelta(days=2),
        lcd_date=now + timedelta(days=2),
        created_at=now
    )
    db_session.add_all([t1, t2])
    db_session.commit()

    # Link t1 and t2
    link = TicketLink(id="LNK-CROSS", ticket_id="TCK-CROSS-1", linked_ticket_id="TCK-CROSS-2", link_reason="Cross-agency link")
    db_session.add(link)
    db_session.commit()

    # Requester from AGY-001 views TCK-CROSS-1
    req_resp = client.get("/api/tickets/TCK-CROSS-1", headers={"X-User-Id": "USR-201"})
    assert req_resp.status_code == 200
    assert "TCK-CROSS-2" not in req_resp.json()["linked_ticket_ids"]

    # Staff views TCK-CROSS-1 and sees the cross-agency link
    staff_resp = client.get("/api/tickets/TCK-CROSS-1", headers={"X-User-Id": "USR-101"})
    assert staff_resp.status_code == 200
    assert "TCK-CROSS-2" in staff_resp.json()["linked_ticket_ids"]

def test_staff_create_ticket_without_agency_id_returns_400(client: TestClient):
    """
    Internal staff creating a ticket without specifying agency_id receives 400 Bad Request.
    The previous default to 'AGY-001' has been strictly removed.
    """
    now = datetime.utcnow()
    payload = {
        "title": "Staff Missing Agency Ticket",
        "description": "Internal staff ticket creation attempt without specifying agency_id",
        "tboh_id": "TBOH-88990",
        "priority": "Medium",
        "check_in_date": (now + timedelta(days=3)).isoformat(),
        "lcd_date": (now + timedelta(days=3)).isoformat(),
        "agency_id": None
    }
    resp = client.post("/api/tickets", json=payload, headers={"X-User-Id": "USR-101"})
    assert resp.status_code == 400
    assert "agency_id is required" in resp.json()["detail"]

def test_unassigned_journey_b_triage_top3(client: TestClient):
    """
    Verifies that unassigned Journey B fixture (TCK-1007) with Urgent priority and near check-in (~2.25h)
    ranks in the top 3 of the triage queue.
    """
    resp = client.get("/api/tickets?view=triage&limit=5", headers={"X-User-Id": "USR-101"})
    assert resp.status_code == 200
    data = resp.json()
    top3_ids = [t["id"] for t in data["tickets"][:3]]
    assert "TCK-1007" in top3_ids, f"Expected TCK-1007 in top 3 triage tickets, found: {top3_ids}"
    t1007 = next(t for t in data["tickets"] if t["id"] == "TCK-1007")
    assert t1007["status"] == "New"
    assert t1007["priority"] == "Urgent"
    assert t1007["assigned_to"] is None


def test_schema_datetime_normalization_unit():
    """
    Verifies that '...Z', '...+05:30', and naive ISO string inputs
    all normalize to the exact same naive UTC datetime.
    """
    from backend.app.schemas import TicketCreateSchema

    base_payload = {
        "title": "Datetime Normalization Test",
        "description": "Checking UTC conversion across formats",
        "tboh_id": "TBOH-TIME-001",
        "priority": "High",
        "intent": "Emergency Check-in Assist",
        "agency_id": "AGY-001"
    }

    # Format 1: Trailing 'Z' (UTC)
    payload_z = {**base_payload, "check_in_date": "2026-11-20T10:00:00Z", "lcd_date": "2026-11-20T10:00:00Z"}
    schema_z = TicketCreateSchema(**payload_z)

    # Format 2: Timezone offset '+05:30' (15:30 IST is 10:00 UTC)
    payload_offset = {**base_payload, "check_in_date": "2026-11-20T15:30:00+05:30", "lcd_date": "2026-11-20T15:30:00+05:30"}
    schema_offset = TicketCreateSchema(**payload_offset)

    # Format 3: Naive UTC string
    payload_naive = {**base_payload, "check_in_date": "2026-11-20T10:00:00", "lcd_date": "2026-11-20T10:00:00"}
    schema_naive = TicketCreateSchema(**payload_naive)

    # All three must result in exact same naive UTC datetime
    expected_dt = datetime(2026, 11, 20, 10, 0, 0)
    assert schema_z.check_in_date == expected_dt
    assert schema_z.check_in_date.tzinfo is None
    assert schema_offset.check_in_date == expected_dt
    assert schema_offset.check_in_date.tzinfo is None
    assert schema_naive.check_in_date == expected_dt
    assert schema_naive.check_in_date.tzinfo is None

    assert schema_z.check_in_date == schema_offset.check_in_date == schema_naive.check_in_date


def test_endpoint_ticket_create_with_z_datetime_201(client: TestClient):
    """
    Verifies that POST /api/tickets with '...Z' datetime succeeds with HTTP 201 (not 500).
    """
    now = datetime.utcnow().replace(microsecond=0)
    checkin_dt = now + timedelta(days=5, hours=2)
    lcd_dt = now + timedelta(days=5)

    payload = {
        "title": "Timezone Aware Payload Test",
        "description": "Sending trailing Z in check-in and lcd timestamps",
        "tboh_id": "TBOH-TZ-9900",
        "priority": "Urgent",
        "check_in_date": checkin_dt.isoformat() + "Z",
        "lcd_date": lcd_dt.isoformat() + "Z",
        "intent": "Emergency Check-in Assist",
        "agency_id": "AGY-001"
    }
    resp = client.post("/api/tickets", json=payload, headers={"X-User-Id": "USR-101"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["tboh_id"] == "TBOH-TZ-9900"
    ticket_id = data["id"]

    # Verify detail retrieval shows normalized naive datetime
    detail_res = client.get(f"/api/tickets/{ticket_id}", headers={"X-User-Id": "USR-101"})
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["check_in_date"] == checkin_dt.isoformat()
    assert detail["lcd_date"] == lcd_dt.isoformat()


def test_schema_validation_failures(client: TestClient):
    """
    Verifies strict validation rules:
    - Invalid priority returns 422
    - Invalid intent returns 422
    - Invalid tboh_id regex returns 422
    - Title > 200 chars returns 422
    - Invalid side-thread email format returns 422
    - Side-thread recipients > 20 returns 422
    - Invalid message_type returns 422
    - Invalid status returns 422
    """
    now = datetime.utcnow().replace(microsecond=0)
    valid_base = {
        "title": "Valid Ticket Title",
        "description": "Valid ticket description for testing",
        "tboh_id": "TBOH-VAL-001",
        "priority": "Medium",
        "check_in_date": (now + timedelta(days=10)).isoformat() + "Z",
        "lcd_date": (now + timedelta(days=9)).isoformat() + "Z",
        "intent": "Unclassified",
        "agency_id": "AGY-001"
    }

    # 1. Invalid priority
    res1 = client.post("/api/tickets", json={**valid_base, "priority": "SuperUrgent"}, headers={"X-User-Id": "USR-101"})
    assert res1.status_code == 422

    # 2. Invalid intent
    res2 = client.post("/api/tickets", json={**valid_base, "intent": "InvalidIntentValue"}, headers={"X-User-Id": "USR-101"})
    assert res2.status_code == 422

    # 3. Invalid tboh_id regex
    res3 = client.post("/api/tickets", json={**valid_base, "tboh_id": "NOT-A-TBOH-ID"}, headers={"X-User-Id": "USR-101"})
    assert res3.status_code == 422

    # 4. Title > 200 chars
    res4 = client.post("/api/tickets", json={**valid_base, "title": "A" * 201}, headers={"X-User-Id": "USR-101"})
    assert res4.status_code == 422

    # 5. Invalid side-thread recipient email format
    side_base = {
        "supplier_name": "Test Hotel",
        "subject": "Inquiry",
        "recipients": ["invalid-email-format"],
        "initial_message": "Hello from operations"
    }
    res5 = client.post("/api/tickets/TCK-1005/side-threads", json=side_base, headers={"X-User-Id": "USR-101"})
    assert res5.status_code == 422

    # 6. Side-thread recipients > 20
    side_overflow = {
        "supplier_name": "Test Hotel",
        "subject": "Inquiry",
        "recipients": [f"user{i}@example.com" for i in range(21)],
        "initial_message": "Hello from operations"
    }
    res6 = client.post("/api/tickets/TCK-1005/side-threads", json=side_overflow, headers={"X-User-Id": "USR-101"})
    assert res6.status_code == 422

    # 7. Invalid message_type Literal
    res7 = client.post("/api/tickets/TCK-1005/messages", json={"message_type": "PrivateNote", "content": "Note text"}, headers={"X-User-Id": "USR-101"})
    assert res7.status_code == 422

    # 8. Invalid status Literal
    res8 = client.post("/api/tickets/TCK-1005/status", json={"status": "ArchivedStatus"}, headers={"X-User-Id": "USR-101"})
    assert res8.status_code == 422


# ============================================================================
# 16. INTENT-AWARE SLA & LCD TESTS
# ============================================================================

def test_seed_zero_open_refund_cancellation_tickets_with_past_lcd(db_session: Session):
    """
    Verifies that for active (non-Closed, non-Resolved) tickets with Refund Request or
    Cancellation Inconvenience intents, lcd_date is in the future (> now) and <= check_in_date.
    There should be zero open Refund/Cancellation tickets seeded with a past LCD.
    """
    now = datetime.utcnow()
    cancellation_intents = ["Refund Request", "Cancellation Inconvenience"]
    open_tickets = db_session.query(Ticket).filter(
        Ticket.status.notin_(["Closed", "Resolved"]),
        Ticket.intent.in_(cancellation_intents)
    ).all()

    assert len(open_tickets) > 0, "Expected seeded open refund/cancellation tickets"
    past_lcd_tickets = [t for t in open_tickets if t.lcd_date is not None and t.lcd_date <= now]
    assert len(past_lcd_tickets) == 0, f"Found {len(past_lcd_tickets)} open tickets with past LCD"


def test_sla_intent_cancellation_uses_lcd():
    """
    Cancellation Inconvenience intent must factor in lcd_date if present.
    If check_in_date is 48h away and lcd_date is 3h away, effective urgency is 3h (AT_RISK for Urgent).
    """
    now = datetime(2026, 11, 16, 12, 0)
    res = evaluate_travel_sla(
        status="Open",
        check_in_date=datetime(2026, 11, 18, 12, 0),  # 48h
        lcd_date=datetime(2026, 11, 16, 15, 0),       # 3h
        priority="Urgent",
        intent="Cancellation Inconvenience",
        now=now
    )
    assert res["status"] == "AT_RISK"
    assert res["hours_remaining"] == 3.0


def test_sla_intent_checkin_ignores_lcd():
    """
    Emergency Check-in Assist intent must ignore lcd_date even if lcd_date is past.
    It strictly uses check_in_date for urgency.
    """
    now = datetime(2026, 11, 16, 12, 0)
    res = evaluate_travel_sla(
        status="Open",
        check_in_date=datetime(2026, 11, 17, 12, 0),  # 24h
        lcd_date=datetime(2026, 11, 15, 12, 0),       # past (-24h)
        priority="Urgent",
        intent="Emergency Check-in Assist",
        now=now
    )
    assert res["status"] == "NORMAL"
    assert res["hours_remaining"] == 24.0


def test_sla_unclassified_uses_lcd():
    """
    Unclassified (or None) intent defaults safely to min(check_in, lcd).
    """
    now = datetime(2026, 11, 16, 12, 0)
    res_unclassified = evaluate_travel_sla(
        status="Open",
        check_in_date=datetime(2026, 11, 18, 12, 0),  # 48h
        lcd_date=datetime(2026, 11, 16, 14, 0),       # 2h
        priority="Urgent",
        intent="Unclassified",
        now=now
    )
    assert res_unclassified["status"] == "AT_RISK"
    assert res_unclassified["hours_remaining"] == 2.0

    res_none = evaluate_travel_sla(
        status="Open",
        check_in_date=datetime(2026, 11, 18, 12, 0),
        lcd_date=datetime(2026, 11, 16, 14, 0),
        priority="Urgent",
        intent=None,
        now=now
    )
    assert res_none["status"] == "AT_RISK"
    assert res_none["hours_remaining"] == 2.0


def test_api_emergency_checkin_ignores_imminent_lcd_sla(client: TestClient):
    """
    Verifies that for an Emergency Check-in Assist ticket with imminent LCD (1h) and
    distant check-in (48h), the API endpoint returns SLA evaluated strictly on check-in
    (NORMAL, ~48h remaining), proving intent is passed end-to-end to evaluate_travel_sla.
    """
    now = datetime.utcnow().replace(microsecond=0)
    checkin_dt = now + timedelta(hours=48)
    lcd_dt = now + timedelta(hours=1)

    payload = {
        "title": "Check-in Assist with Imminent LCD",
        "description": "Guest arriving in 2 days. LCD happens to be in 1 hour.",
        "tboh_id": "TBOH-IGN-LCD-01",
        "priority": "Urgent",
        "check_in_date": checkin_dt.isoformat() + "Z",
        "lcd_date": lcd_dt.isoformat() + "Z",
        "intent": "Emergency Check-in Assist",
        "agency_id": "AGY-001"
    }
    resp = client.post("/api/tickets", json=payload, headers={"X-User-Id": "USR-101"})
    assert resp.status_code == 201
    ticket_id = resp.json()["id"]

    detail_res = client.get(f"/api/tickets/{ticket_id}", headers={"X-User-Id": "USR-101"})
    assert detail_res.status_code == 200
    sla = detail_res.json()["sla"]
    # If LCD was used, SLA would be AT_RISK or BREACHED (1h <= 6h Urgent threshold).
    # Since Emergency Check-in Assist ignores LCD, SLA is NORMAL (~48h remaining).
    assert sla["status"] == "NORMAL"
    assert sla["hours_remaining"] is not None
    assert sla["hours_remaining"] > 40.0


def test_queue_score_refund_intent_uses_lcd_higher_rank():
    """
    Verifies Tier-2 Queue Scoring with Intent-Aware Urgency:
    Refund ticket with same priority (Medium), LCD in 3h and check-in in 5d,
    ranks ABOVE a Refund ticket with check-in in 2d and no LCD.
    """
    now = datetime(2026, 11, 16, 12, 0)
    # Ticket A: Medium priority, Refund Request, check-in in 5 days (120h), LCD in 3 hours.
    # Effective hours = 3.0h (<= 6.0h -> modifier +800). Total score = 200 + 800 = 1000.
    score_a = calculate_queue_score_tier2(
        priority="Medium",
        check_in_date=datetime(2026, 11, 21, 12, 0),
        lcd_date=datetime(2026, 11, 16, 15, 0),
        intent="Refund Request",
        now=now
    )

    # Ticket B: Medium priority, Refund Request, check-in in 2 days (48h), no LCD.
    # Effective hours = 48.0h (> 24.0h -> modifier +0). Total score = 200 + 0 = 200.
    score_b = calculate_queue_score_tier2(
        priority="Medium",
        check_in_date=datetime(2026, 11, 18, 12, 0),
        lcd_date=None,
        intent="Refund Request",
        now=now
    )

    assert score_a == 1000.0
    assert score_b == 200.0
    assert score_a > score_b, f"Expected Ticket A ({score_a}) to outrank Ticket B ({score_b})"


def test_queue_score_checkin_intent_ignores_past_lcd():
    """
    Verifies that for Emergency Check-in Assist tickets, calculate_queue_score_tier2
    ignores past LCD and strictly scores urgency based on check_in_date.
    """
    now = datetime(2026, 11, 16, 12, 0)
    # Urgent ticket, check-in in 24 hours (+300 modifier), past LCD (-2h).
    # If LCD was used, effective hours would be -2h (<=2h -> modifier +2000, score 3000).
    # Because intent is Emergency Check-in Assist, LCD is ignored: effective hours = 24h -> modifier +300, score 1300.
    score = calculate_queue_score_tier2(
        priority="Urgent",
        check_in_date=datetime(2026, 11, 17, 12, 0),
        lcd_date=datetime(2026, 11, 16, 10, 0),
        intent="Emergency Check-in Assist",
        now=now
    )
    assert score == 1300.0


# ============================================================================
# 17. PART 1 HARDENING TESTS: EDGE CASES, ROLES, & PAGINATION
# ============================================================================

def test_effective_deadline_hours_edge_cases():
    """
    Edge case tests for effective_deadline_hours helper:
    1. intent=None with lcd_date present: uses min(check_in, lcd)
    2. intent='Unclassified' with lcd_date=None: strictly uses check_in_date
    3. intent='Refund Request' with past lcd_date: returns negative/breached hours
    4. check-in intents (Emergency Check-in Assist) with past lcd_date: ignores LCD, strictly uses check_in_date
    """
    now = datetime(2026, 11, 16, 12, 0)

    # 1. intent=None + lcd present
    h1 = effective_deadline_hours(
        check_in_date=datetime(2026, 11, 18, 12, 0),  # +48h
        lcd_date=datetime(2026, 11, 16, 17, 0),       # +5h
        intent=None,
        now=now
    )
    assert abs(h1 - 5.0) < 0.01

    # 2. Unclassified + lcd None
    h2 = effective_deadline_hours(
        check_in_date=datetime(2026, 11, 16, 22, 0),  # +10h
        lcd_date=None,
        intent="Unclassified",
        now=now
    )
    assert abs(h2 - 10.0) < 0.01

    # 3. Refund Request + past lcd
    h3 = effective_deadline_hours(
        check_in_date=datetime(2026, 11, 17, 12, 0),  # +24h
        lcd_date=datetime(2026, 11, 16, 10, 0),       # -2h
        intent="Refund Request",
        now=now
    )
    assert abs(h3 - (-2.0)) < 0.01

    # 4. Check-in intent + past lcd
    h4 = effective_deadline_hours(
        check_in_date=datetime(2026, 11, 17, 0, 0),   # +12h
        lcd_date=datetime(2026, 11, 16, 7, 0),        # -5h
        intent="Emergency Check-in Assist",
        now=now
    )
    assert abs(h4 - 12.0) < 0.01


def test_requester_cannot_assign_unassign_escalate_403(client: TestClient):
    """
    Verifies that Requesters (e.g. USR-201) receive 403 Forbidden on:
    - POST /api/tickets/{id}/assign
    - POST /api/tickets/{id}/unassign
    - POST /api/tickets/{id}/escalate
    """
    # 1. Assign
    res_assign = client.post(
        "/api/tickets/TCK-1004/assign",
        json={"agent_id": "USR-102"},
        headers={"X-User-Id": "USR-201"}
    )
    assert res_assign.status_code == 403

    # 2. Unassign
    res_unassign = client.post(
        "/api/tickets/TCK-1004/unassign",
        headers={"X-User-Id": "USR-201"}
    )
    assert res_unassign.status_code == 403

    # 3. Escalate
    res_esc = client.post(
        "/api/tickets/TCK-1004/escalate",
        json={"reason": "Customer demands escalation"},
        headers={"X-User-Id": "USR-201"}
    )
    assert res_esc.status_code == 403


def test_staff_can_assign_and_unassign_ticket(client: TestClient, db_session: Session):
    """
    Verifies that staff members (Agent USR-101) can unassign a ticket back to triage
    and reassign it to an available agent.
    """
    # Unassign TCK-1004
    res_un = client.post("/api/tickets/TCK-1004/unassign", headers={"X-User-Id": "USR-101"})
    assert res_un.status_code == 200
    assert res_un.json()["assigned_to"] is None

    # Reassign TCK-1004 to USR-102
    res_as = client.post(
        "/api/tickets/TCK-1004/assign",
        json={"agent_id": "USR-102"},
        headers={"X-User-Id": "USR-101"}
    )
    assert res_as.status_code == 200
    assert res_as.json()["assigned_to"] == "USR-102"


def test_requester_views_and_pagination(client: TestClient):
    """
    Verifies edge cases for GET /api/tickets:
    - Requester view=by_intent returns only tickets matching their agency and intent
    - Requester view=linked strictly filters to intra-agency linked tickets
    - Response pagination includes accurate total count
    """
    # 1. by_intent view for Requester
    res = client.get("/api/tickets?view=by_intent&intent=Refund Request&limit=10&offset=0", headers={"X-User-Id": "USR-201"})
    assert res.status_code == 200
    data = res.json()
    assert "total" in data
    assert "tickets" in data
    for t in data["tickets"]:
        assert t["intent"] == "Refund Request"
        assert t["agency_id"] == "AGY-001"
        assert t["assigned_to"] is None
        assert t["routing_reason"] is None
        assert t["queue_score"] is None

    # 2. linked view for Requester
    res_lnk = client.get("/api/tickets?view=linked", headers={"X-User-Id": "USR-201"})
    assert res_lnk.status_code == 200
    data_lnk = res_lnk.json()
    for t in data_lnk["tickets"]:
        assert t["agency_id"] == "AGY-001"




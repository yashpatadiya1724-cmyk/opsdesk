import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.config.routing_config import (
    AGENCY_TIER_MULTIPLIERS,
    EMERGENCY_BYPASS_HOURS,
    PRIORITY_SCORES,
    CHECKIN_URGENCY_MODIFIERS
)
from backend.services.routing_engine import calculate_queue_score_tier2
from backend.app.models import Ticket, Agency, AuditLog, TicketMessage, EventOutbox
from backend.app.database import ensure_schema_migrations
from sqlalchemy import or_


@pytest.fixture(autouse=True)
def cleanup_test_tickets(db_session: Session):
    yield
    test_tboh_prefixes = ["TBOH-EMERG-", "TBOH-NORM-", "TBOH-TIER-"]
    test_tickets = db_session.query(Ticket.id).filter(
        or_(*(Ticket.tboh_id.like(f"{p}%") for p in test_tboh_prefixes))
    ).all()
    test_ticket_ids = [t[0] for t in test_tickets]
    if test_ticket_ids:
        db_session.query(EventOutbox).filter(EventOutbox.ticket_id.in_(test_ticket_ids)).delete(synchronize_session=False)
        db_session.query(AuditLog).filter(AuditLog.ticket_id.in_(test_ticket_ids)).delete(synchronize_session=False)
        db_session.query(TicketMessage).filter(TicketMessage.ticket_id.in_(test_ticket_ids)).delete(synchronize_session=False)
        db_session.query(Ticket).filter(Ticket.id.in_(test_ticket_ids)).delete(synchronize_session=False)
        db_session.commit()


def test_emergency_bypass_triggers_at_3_9h(client: TestClient, db_session: Session):
    """
    Verifies that when a ticket has an effective deadline <= 4 hours (e.g. 3.9h),
    Tier-1 Emergency Bypass triggers:
    1. priority is forced to 'Urgent'
    2. status is forced to 'Escalated'
    3. routing_reason reflects Tier-1 Emergency Bypass with effective deadline
    4. AuditLog / TicketActivity / internal note is recorded
    """
    now = datetime.now(timezone.utc).replace(microsecond=0)
    checkin_3_9h = now + timedelta(hours=3, minutes=54)  # exactly 3.9 hours

    payload = {
        "title": "Imminent Departure Emergency Assistance",
        "description": "Traveler front-desk check-in issue with flight departing very soon",
        "tboh_id": "TBOH-EMERG-3900",
        "priority": "Low",  # Initially low; bypass MUST force it to Urgent
        "check_in_date": checkin_3_9h.isoformat(),
        "intent": "Bedding / Room Preference",
        "agency_id": "AGY-001"
    }

    resp = client.post("/api/tickets", json=payload, headers={"X-User-Id": "USR-101"})
    assert resp.status_code == 201
    data = resp.json()

    assert data["priority"] == "Urgent"
    assert data["status"] == "Escalated"
    assert "Tier-1 Emergency Bypass" in data["routing_reason"]
    assert f"<={EMERGENCY_BYPASS_HOURS}h" in data["routing_reason"].replace(" ", "")

    ticket_id = data["id"]

    # Verify detail endpoint reflects forced attributes
    detail_res = client.get(f"/api/tickets/{ticket_id}", headers={"X-User-Id": "USR-101"})
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["priority"] == "Urgent"
    assert detail["status"] == "Escalated"
    assert "Tier-1 Emergency Bypass" in detail["routing_reason"]

    # Verify audit log and internal system note
    audit = db_session.query(AuditLog).filter(
        AuditLog.ticket_id == ticket_id,
        AuditLog.action == "ticket.emergency_bypass"
    ).first()
    assert audit is not None
    assert "Tier-1 Emergency Bypass" in audit.details

    note = db_session.query(TicketMessage).filter(
        TicketMessage.ticket_id == ticket_id,
        TicketMessage.message_type == "InternalNote"
    ).first()
    assert note is not None
    assert "Emergency Bypass" in note.content


def test_emergency_bypass_triggers_via_lcd_date_at_3_9h(client: TestClient):
    """
    Verifies that for cancellation intents (e.g. Refund Request),
    an imminent LCD date at 3.9h also triggers Tier-1 Emergency Bypass
    even if check_in_date is days away.
    """
    now = datetime.now(timezone.utc).replace(microsecond=0)
    checkin_far = now + timedelta(days=10)
    lcd_3_9h = now + timedelta(hours=3, minutes=54)

    payload = {
        "title": "Refund Deadline Imminent Emergency",
        "description": "Last cancellation date expiring in 3.9 hours, needs urgent processing",
        "tboh_id": "TBOH-EMERG-LCD-3901",
        "priority": "Medium",
        "check_in_date": checkin_far.isoformat(),
        "lcd_date": lcd_3_9h.isoformat(),
        "intent": "Refund Request",
        "agency_id": "AGY-002"
    }

    resp = client.post("/api/tickets", json=payload, headers={"X-User-Id": "USR-101"})
    assert resp.status_code == 201
    data = resp.json()

    assert data["priority"] == "Urgent"
    assert data["status"] == "Escalated"
    assert "Tier-1 Emergency Bypass" in data["routing_reason"]


def test_emergency_bypass_does_not_trigger_at_4_1h(client: TestClient):
    """
    Verifies that when a ticket has an effective deadline > 4 hours (e.g. 4.1h),
    Tier-1 Emergency Bypass does NOT trigger:
    1. priority remains as requested (e.g. 'Medium' or 'Low')
    2. status remains normal ('Open' or 'New', NOT 'Escalated')
    3. routing_reason does not contain 'Tier-1 Emergency Bypass'
    """
    now = datetime.now(timezone.utc).replace(microsecond=0)
    checkin_4_1h = now + timedelta(hours=4, minutes=6)  # exactly 4.1 hours

    payload = {
        "title": "Standard Window Operational Inquiry",
        "description": "Check-in in 4.1 hours, outside emergency bypass window",
        "tboh_id": "TBOH-NORM-4100",
        "priority": "Medium",
        "check_in_date": checkin_4_1h.isoformat(),
        "intent": "Bedding / Room Preference",
        "agency_id": "AGY-001"
    }

    resp = client.post("/api/tickets", json=payload, headers={"X-User-Id": "USR-101"})
    assert resp.status_code == 201
    data = resp.json()

    assert data["priority"] == "Medium"
    assert data["status"] != "Escalated"
    assert "Tier-1 Emergency Bypass" not in (data.get("routing_reason") or "")

    ticket_id = data["id"]
    detail_res = client.get(f"/api/tickets/{ticket_id}", headers={"X-User-Id": "USR-101"})
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["priority"] == "Medium"
    assert detail["status"] != "Escalated"
    assert "Tier-1 Emergency Bypass" not in (detail.get("routing_reason") or "")


def test_tier_score_multiplier_ordering_unit():
    """
    Verifies Tier score multiplier ordering: platinum > gold > standard
    on otherwise identical ticket parameters.
    """
    now = datetime(2026, 11, 18, 12, 0)
    check_in = now + timedelta(hours=10)

    # Base score without agency tier (standard default multiplier 1.0)
    score_unspecified = calculate_queue_score_tier2(
        priority="Medium",
        check_in_date=check_in,
        now=now
    )
    score_standard = calculate_queue_score_tier2(
        priority="Medium",
        check_in_date=check_in,
        agency_tier="standard",
        now=now
    )
    score_gold = calculate_queue_score_tier2(
        priority="Medium",
        check_in_date=check_in,
        agency_tier="gold",
        now=now
    )
    score_platinum = calculate_queue_score_tier2(
        priority="Medium",
        check_in_date=check_in,
        agency_tier="platinum",
        now=now
    )

    # Multiplier ordering assertions
    assert score_platinum > score_gold > score_standard
    assert score_standard == score_unspecified
    assert score_platinum == pytest.approx(score_standard * 1.3)
    assert score_gold == pytest.approx(score_standard * 1.15)
    assert score_standard == pytest.approx(score_standard * 1.0)

    # Case insensitivity check
    score_plat_upper = calculate_queue_score_tier2(
        priority="Medium",
        check_in_date=check_in,
        agency_tier="PLATINUM",
        now=now
    )
    score_gold_mixed = calculate_queue_score_tier2(
        priority="Medium",
        check_in_date=check_in,
        agency_tier="Gold",
        now=now
    )
    assert score_plat_upper == score_platinum
    assert score_gold_mixed == score_gold


def test_tier_score_multiplier_in_api(client: TestClient):
    """
    Verifies that identical tickets created across platinum, gold, and standard agencies
    yield queue scores where platinum > gold > standard via the API endpoints.
    """
    now = datetime.now(timezone.utc).replace(microsecond=0)
    check_in_future = now + timedelta(hours=18)

    # AGY-001 is platinum (1.3x)
    resp_plat = client.post("/api/tickets", json={
        "title": "Agency Platinum Queue Test",
        "description": "Testing platinum tier multiplier",
        "tboh_id": "TBOH-TIER-PLAT-01",
        "priority": "Medium",
        "check_in_date": check_in_future.isoformat(),
        "intent": "Bedding / Room Preference",
        "agency_id": "AGY-001"
    }, headers={"X-User-Id": "USR-101"})
    assert resp_plat.status_code == 201
    ticket_plat_id = resp_plat.json()["id"]

    # AGY-002 is gold (1.15x)
    resp_gold = client.post("/api/tickets", json={
        "title": "Agency Gold Queue Test",
        "description": "Testing gold tier multiplier",
        "tboh_id": "TBOH-TIER-GOLD-01",
        "priority": "Medium",
        "check_in_date": check_in_future.isoformat(),
        "intent": "Bedding / Room Preference",
        "agency_id": "AGY-002"
    }, headers={"X-User-Id": "USR-101"})
    assert resp_gold.status_code == 201
    ticket_gold_id = resp_gold.json()["id"]

    # AGY-003 is standard (1.0x)
    resp_std = client.post("/api/tickets", json={
        "title": "Agency Standard Queue Test",
        "description": "Testing standard tier multiplier",
        "tboh_id": "TBOH-TIER-STD-01",
        "priority": "Medium",
        "check_in_date": check_in_future.isoformat(),
        "intent": "Bedding / Room Preference",
        "agency_id": "AGY-003"
    }, headers={"X-User-Id": "USR-101"})
    assert resp_std.status_code == 201
    ticket_std_id = resp_std.json()["id"]

    det_plat = client.get(f"/api/tickets/{ticket_plat_id}", headers={"X-User-Id": "USR-101"}).json()
    det_gold = client.get(f"/api/tickets/{ticket_gold_id}", headers={"X-User-Id": "USR-101"}).json()
    det_std = client.get(f"/api/tickets/{ticket_std_id}", headers={"X-User-Id": "USR-101"}).json()

    assert det_plat["queue_score"] > det_gold["queue_score"] > det_std["queue_score"]
    assert det_plat["queue_score"] == pytest.approx(det_std["queue_score"] * 1.3)
    assert det_gold["queue_score"] == pytest.approx(det_std["queue_score"] * 1.15)


def test_agency_tier_seed_and_migration(db_session: Session):
    """
    Verifies that demo agencies are seeded with explicit tiers:
    AGY-001 -> platinum
    AGY-002 -> gold
    AGY-003 -> standard
    And ensure_schema_migrations runs cleanly.
    """
    agy1 = db_session.query(Agency).filter(Agency.id == "AGY-001").first()
    agy2 = db_session.query(Agency).filter(Agency.id == "AGY-002").first()
    agy3 = db_session.query(Agency).filter(Agency.id == "AGY-003").first()

    assert agy1 is not None and agy1.tier == "platinum"
    assert agy2 is not None and agy2.tier == "gold"
    assert agy3 is not None and agy3.tier == "standard"

    # Verify migration function on active engine
    engine = db_session.get_bind()
    ensure_schema_migrations(engine)

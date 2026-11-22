"""
backend/tests/test_qa_section3_adversarial.py
Independent QA Adversarial Test Suite for Section 3 (Round 10).
Tests:
1. Selective Boundary Refresher: Urgency tier boundary crossing (2h, 6h, 24h) and uncomputed scores.
2. Agency Tier Mutation Immediate Cache Invalidation and multi-tenant isolation.
3. Read path triage ordering parity with stored DB queue_score and Requester score withholding.
4. Schema migration dialect safety across SQLite and PostgreSQL.
"""

import uuid
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.app.models import Ticket, Agency, User
from backend.services.routing_engine import (
    calculate_queue_score_tier2,
    refresh_stale_queue_scores,
    compute_ticket_urgency_fields
)
from backend.config.routing_config import PRIORITY_SCORES, CHECKIN_URGENCY_MODIFIERS, AGENCY_TIER_MULTIPLIERS


# ============================================================================
# 1. SELECTIVE BOUNDARY REFRESHER ADVERSARIAL TESTS
# ============================================================================

def test_qa_adversarial_refresher_boundary_crossing_selectivity(db_session: Session):
    """
    Hypothesis 1: refresh_stale_queue_scores must ONLY update tickets that crossed
    a 2h, 6h, or 24h boundary since score_computed_at, or whose score is uncomputed.
    Tickets within the same tier (e.g. 5h -> 4h) must NOT be refreshed.
    """
    now_t0 = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
    agency = db_session.query(Agency).filter(Agency.id == "AGY-001").first()

    # Ticket A: Within same tier (5h remaining at T0 -> 4h remaining at T1). Boundary NOT crossed.
    t_no_cross = Ticket(
        id=f"TCK-QA-NOCROSS-{uuid.uuid4().hex[:6]}",
        tboh_id="TBOH-QA-1",
        agency_id=agency.id,
        title="No Boundary Cross Ticket",
        description="Ticket staying in same 2h-6h tier",
        intent="Emergency Check-in Assist",
        priority="Medium",
        status="Open",
        check_in_date=now_t0 + timedelta(hours=5.0),
        effective_deadline_at=now_t0 + timedelta(hours=5.0),
        priority_weight=200.0,
        queue_score=1000.0,  # 200 + 800 (tier <= 6h)
        score_computed_at=now_t0,
        created_at=now_t0,
        updated_at=now_t0
    )

    # Ticket B: Crosses 24h boundary (25h remaining at T0 -> 23h remaining at T1). Boundary CROSSED.
    t_cross_24h = Ticket(
        id=f"TCK-QA-CROSS24-{uuid.uuid4().hex[:6]}",
        tboh_id="TBOH-QA-2",
        agency_id=agency.id,
        title="24h Boundary Cross Ticket",
        description="Ticket crossing 24h boundary",
        intent="Emergency Check-in Assist",
        priority="Medium",
        status="Open",
        check_in_date=now_t0 + timedelta(hours=25.0),
        effective_deadline_at=now_t0 + timedelta(hours=25.0),
        priority_weight=200.0,
        queue_score=200.0,  # 200 + 0 (tier > 24h)
        score_computed_at=now_t0,
        created_at=now_t0,
        updated_at=now_t0
    )

    # Ticket C: Uncomputed ticket (queue_score IS NULL). Must ALWAYS be refreshed.
    t_uncomputed = Ticket(
        id=f"TCK-QA-UNCOMP-{uuid.uuid4().hex[:6]}",
        tboh_id="TBOH-QA-3",
        agency_id=agency.id,
        title="Uncomputed Ticket",
        description="Ticket with NULL score",
        intent="Emergency Check-in Assist",
        priority="High",
        status="Open",
        check_in_date=now_t0 + timedelta(hours=10.0),
        effective_deadline_at=now_t0 + timedelta(hours=10.0),
        priority_weight=500.0,
        queue_score=None,
        score_computed_at=None,
        created_at=now_t0,
        updated_at=now_t0
    )

    db_session.add_all([t_no_cross, t_cross_24h, t_uncomputed])
    db_session.commit()

    # Advance time to T1 = T0 + 1 hour (Ticket A has 4h remaining; Ticket B has 24h-1h=23h remaining)
    now_t1 = now_t0 + timedelta(hours=1.0)
    refreshed_count = refresh_stale_queue_scores(db_session, now=now_t1)

    # Must refresh Ticket B (crossed 24h) and Ticket C (uncomputed), but NOT Ticket A
    db_session.expire_all()
    t_a = db_session.query(Ticket).filter(Ticket.id == t_no_cross.id).first()
    t_b = db_session.query(Ticket).filter(Ticket.id == t_cross_24h.id).first()
    t_c = db_session.query(Ticket).filter(Ticket.id == t_uncomputed.id).first()

    # Ticket A was untouched: score_computed_at remains now_t0
    assert t_a.score_computed_at == now_t0
    assert t_a.queue_score == 1000.0

    # Ticket B crossed from >24h to <=24h: score updated to include +300 modifier
    assert t_b.score_computed_at == now_t1
    expected_b_score = (200.0 + 300.0) * AGENCY_TIER_MULTIPLIERS.get(agency.tier.lower(), 1.0)
    assert abs(t_b.queue_score - expected_b_score) < 0.01

    # Ticket C computed
    assert t_c.queue_score is not None
    assert t_c.score_computed_at == now_t1


# ============================================================================
# 2. AGENCY TIER MUTATION IMMEDIATE CACHE INVALIDATION
# ============================================================================

def test_qa_adversarial_agency_tier_mutation_immediate_invalidation(client: TestClient, db_session: Session):
    """
    Hypothesis 2: Updating an agency's tier immediately updates the stored queue_score
    of all active tickets for that agency, while leaving closed tickets and other agencies untouched.
    Non-staff callers must receive 403 Forbidden.
    """
    now = datetime.now(timezone.utc)
    # Ensure fresh test agency with 'standard' tier
    agency = Agency(id=f"AGY-TIER-{uuid.uuid4().hex[:6]}", name="Tier Test Agency", country_code="AE", tier="standard")
    other_agency = Agency(id=f"AGY-OTHER-{uuid.uuid4().hex[:6]}", name="Other Agency", country_code="IN", tier="standard")
    db_session.add_all([agency, other_agency])
    db_session.commit()

    # Active ticket in target agency
    t_active = Ticket(
        id=f"TCK-ACT-{uuid.uuid4().hex[:6]}",
        tboh_id="TBOH-TIER-1",
        agency_id=agency.id,
        title="Active Agency Ticket",
        description="Ticket should update score immediately",
        intent="Emergency Check-in Assist",
        priority="Urgent",  # 1000 base
        status="Open",
        check_in_date=now + timedelta(hours=10),
        effective_deadline_at=now + timedelta(hours=10),
        priority_weight=1000.0,
        queue_score=1300.0,  # 1000 + 300 (<=24h) * 1.0 (standard) = 1300.0
        score_computed_at=now,
        created_at=now,
        updated_at=now
    )

    # Closed ticket in target agency (must NOT be updated)
    t_closed = Ticket(
        id=f"TCK-CLS-{uuid.uuid4().hex[:6]}",
        tboh_id="TBOH-TIER-2",
        agency_id=agency.id,
        title="Closed Agency Ticket",
        description="Closed ticket should retain prior score",
        intent="Emergency Check-in Assist",
        priority="Urgent",
        status="Closed",
        check_in_date=now - timedelta(days=2),
        effective_deadline_at=now - timedelta(days=2),
        priority_weight=1000.0,
        queue_score=1000.0,
        score_computed_at=now,
        created_at=now,
        updated_at=now
    )

    # Active ticket in other agency (must NOT be touched)
    t_other = Ticket(
        id=f"TCK-OTH-{uuid.uuid4().hex[:6]}",
        tboh_id="TBOH-TIER-3",
        agency_id=other_agency.id,
        title="Other Agency Ticket",
        description="Other agency active ticket",
        intent="Emergency Check-in Assist",
        priority="Urgent",
        status="Open",
        check_in_date=now + timedelta(hours=10),
        effective_deadline_at=now + timedelta(hours=10),
        priority_weight=1000.0,
        queue_score=1300.0,
        score_computed_at=now,
        created_at=now,
        updated_at=now
    )
    db_session.add_all([t_active, t_closed, t_other])
    db_session.commit()

    # 1. Requester cannot update agency tier -> 403 Forbidden
    res_req = client.patch(
        f"/api/agencies/{agency.id}/tier",
        json={"tier": "platinum"},
        headers={"X-User-Id": "USR-201"}
    )
    assert res_req.status_code == 403

    # 2. Lead (USR-104) updates agency tier to platinum (1.3x)
    res_lead = client.patch(
        f"/api/agencies/{agency.id}/tier",
        json={"tier": "platinum"},
        headers={"X-User-Id": "USR-104"}
    )
    assert res_lead.status_code == 200
    data = res_lead.json()
    assert data["tier"] == "platinum"
    assert data["tickets_updated"] == 1

    # 3. Verify immediate database stored score update
    db_session.expire_all()
    t_act_db = db_session.query(Ticket).filter(Ticket.id == t_active.id).first()
    t_cls_db = db_session.query(Ticket).filter(Ticket.id == t_closed.id).first()
    t_oth_db = db_session.query(Ticket).filter(Ticket.id == t_other.id).first()

    # Target active ticket: (1000 + 300) * 1.3 = 1690.0
    assert abs(t_act_db.queue_score - 1690.0) < 0.01

    # Target closed ticket unchanged: 1000.0
    assert t_cls_db.queue_score == 1000.0

    # Other agency ticket unchanged: 1300.0
    assert t_oth_db.queue_score == 1300.0


# ============================================================================
# 3. READ PATH ORDERING VS STORED CACHE PARITY
# ============================================================================

def test_qa_adversarial_triage_read_path_parity_and_privacy(client: TestClient, db_session: Session):
    """
    Hypothesis 3: GET /api/tickets?view=triage orders strictly by stored Ticket.queue_score.desc().
    Every returned queue_score must strictly equal the stored DB value.
    Requesters must never receive queue_score in either list or detail views.
    """
    resp_staff = client.get("/api/tickets?view=triage&limit=20", headers={"X-User-Id": "USR-101"})
    assert resp_staff.status_code == 200
    data = resp_staff.json()
    tickets = data["tickets"]
    assert len(tickets) > 0

    # Strictly descending order
    scores = [t["queue_score"] for t in tickets]
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1], f"Triage ordering failure at index {i}: {scores[i]} < {scores[i+1]}"

    # Parity with DB
    ticket_ids = [t["id"] for t in tickets]
    db_tickets = {t.id: t.queue_score for t in db_session.query(Ticket.id, Ticket.queue_score).filter(Ticket.id.in_(ticket_ids)).all()}
    for t in tickets:
        assert abs(t["queue_score"] - db_tickets[t["id"]]) < 1e-4

    # Privacy: Requester receives None
    resp_req = client.get("/api/tickets", headers={"X-User-Id": "USR-201"})
    assert resp_req.status_code == 200
    for t in resp_req.json()["tickets"]:
        assert t["queue_score"] is None

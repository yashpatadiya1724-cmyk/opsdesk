import os
from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from backend.app.models import Ticket, Agency


def test_orm_insert_without_score_defaults_and_orders_correctly(db_session: Session, client: TestClient):
    """
    ADDENDUM A3: Asserts that inserting a Ticket directly via the ORM without an explicit queue_score
    does not leave queue_score as NULL, and preserves correct triage order (high scores before low scores).
    """
    now = datetime.now(timezone.utc)
    future = now + timedelta(days=2)

    # Clean existing test records if any
    db_session.query(Ticket).filter(Ticket.id.in_(["TCK-QA-LOW", "TCK-QA-HIGH"])).delete(synchronize_session=False)
    db_session.commit()

    agency = db_session.query(Agency).filter_by(id="AGY-QA-TEST").first()
    if not agency:
        agency = Agency(id="AGY-QA-TEST", name="QA Test Agency", country_code="AE", tier="gold")
        db_session.add(agency)
        db_session.commit()

    # Insert two tickets via ORM WITHOUT providing queue_score
    t_low = Ticket(
        id="TCK-QA-LOW",
        agency_id="AGY-QA-TEST",
        tboh_id="TBOH-QA-1",
        title="QA Low Priority",
        description="Low priority without score",
        priority="Low",
        priority_weight=50.0,
        status="Open",
        intent="General Inquiry",
        check_in_date=future,
        effective_deadline_at=future,
        created_at=now,
        updated_at=now,
    )
    t_high = Ticket(
        id="TCK-QA-HIGH",
        agency_id="AGY-QA-TEST",
        tboh_id="TBOH-QA-2",
        title="QA High Priority",
        description="High priority without score",
        priority="High",
        priority_weight=500.0,
        status="Open",
        intent="General Inquiry",
        check_in_date=future,
        effective_deadline_at=future,
        created_at=now,
        updated_at=now,
    )
    db_session.add_all([t_low, t_high])
    db_session.commit()

    db_session.refresh(t_low)
    db_session.refresh(t_high)

    assert t_low.queue_score is not None, "queue_score must NOT be None when inserted without explicit score"
    assert t_high.queue_score is not None, "queue_score must NOT be None when inserted without explicit score"

    # Query triage via API
    resp = client.get("/api/tickets?view=triage&search=TBOH-QA", headers={"X-User-Id": "USR-101"})
    assert resp.status_code == 200
    items = resp.json().get("tickets", [])
    item_ids = [item["id"] for item in items if item["id"] in ["TCK-QA-LOW", "TCK-QA-HIGH"]]

    assert item_ids == ["TCK-QA-HIGH", "TCK-QA-LOW"], f"High score ticket must rank before low score ticket! Got: {item_ids}"


def test_row_with_score_zero_never_ranks_above_higher_scores(db_session: Session, client: TestClient):
    """
    ADDENDUM A3: Asserts that a row with score 0.0 never ranks above rows with higher scores (e.g. 500.0).
    """
    now = datetime.now(timezone.utc)
    future = now + timedelta(days=2)

    db_session.query(Ticket).filter(Ticket.id.in_(["TCK-QA-ZERO", "TCK-QA-POS"])).delete(synchronize_session=False)
    db_session.commit()

    agency = db_session.query(Agency).filter_by(id="AGY-QA-TEST").first()
    if not agency:
        agency = Agency(id="AGY-QA-TEST", name="QA Test Agency", country_code="AE", tier="gold")
        db_session.add(agency)
        db_session.commit()

    t_zero = Ticket(
        id="TCK-QA-ZERO",
        agency_id="AGY-QA-TEST",
        tboh_id="TBOH-QA-Z",
        title="QA Zero Score",
        description="Zero score",
        priority="Low",
        priority_weight=50.0,
        queue_score=0.0,
        status="Open",
        intent="General Inquiry",
        check_in_date=future,
        effective_deadline_at=future,
        created_at=now,
        updated_at=now,
    )
    t_pos = Ticket(
        id="TCK-QA-POS",
        agency_id="AGY-QA-TEST",
        tboh_id="TBOH-QA-P",
        title="QA Pos Score",
        description="Positive score",
        priority="High",
        priority_weight=500.0,
        queue_score=500.0,
        status="Open",
        intent="General Inquiry",
        check_in_date=future,
        effective_deadline_at=future,
        created_at=now,
        updated_at=now,
    )
    db_session.add_all([t_zero, t_pos])
    db_session.commit()

    resp = client.get("/api/tickets?view=triage&search=TBOH-QA", headers={"X-User-Id": "USR-101"})
    assert resp.status_code == 200
    items = resp.json().get("tickets", [])
    item_ids = [item["id"] for item in items if item["id"] in ["TCK-QA-ZERO", "TCK-QA-POS"]]

    assert item_ids == ["TCK-QA-POS", "TCK-QA-ZERO"], f"Score 0 must never rank above score 500! Got: {item_ids}"

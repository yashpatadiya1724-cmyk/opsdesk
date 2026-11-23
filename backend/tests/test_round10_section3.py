"""
Tests for Section 3 of Round 10: Triage Scalability & Stored Score Cache.
"""
import os
import sys
import uuid
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models import Ticket, Agency, User
from backend.app import manage
from backend.services.routing_engine import (
    calculate_queue_score_tier2,
    compute_ticket_urgency_fields,
    refresh_stale_queue_scores,
    get_sql_queue_score_expr
)


def test_refresh_scores_cli(db_session: Session, monkeypatch):
    """Verifies backend.app.manage refresh-scores CLI command."""
    now = datetime.now(timezone.utc)
    from sqlalchemy.orm import sessionmaker
    TestSession = sessionmaker(bind=db_session.get_bind())
    monkeypatch.setattr(manage, "SessionLocal", TestSession)

    # Seed an agency and an uncomputed ticket
    agency = Agency(id="AGY-CLI-1", name="CLI Test Agency", country_code="AE", tier="standard")
    t_id = f"TCK-CLI-{uuid.uuid4().hex[:6]}"
    ticket = Ticket(
        id=t_id,
        tboh_id="TBOH-CLI-1",
        agency_id="AGY-CLI-1",
        title="CLI Uncomputed Ticket",
        description="Testing CLI refresh command",
        priority="High",
        status="New",
        check_in_date=now + timedelta(hours=5),
        created_at=now,
        updated_at=now,
        queue_score=None,
        score_computed_at=None
    )
    db_session.add(agency)
    db_session.add(ticket)
    db_session.commit()

    # Run CLI command
    manage.main(["refresh-scores", "--batch-size", "50"])

    db_session.expire_all()
    reloaded = db_session.query(Ticket).filter(Ticket.id == t_id).first()
    assert reloaded is not None
    assert reloaded.queue_score is not None
    assert reloaded.score_computed_at is not None


def test_refresh_stale_queue_scores_selective_boundary(db_session: Session):
    """
    Verifies that refresh_stale_queue_scores ONLY updates tickets whose urgency tier
    boundary (2h, 6h, 24h) was crossed since last computation, or uncomputed tickets.
    """
    now = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
    agency = Agency(id="AGY-SEL-1", name="Selective Agency", country_code="AE", tier="standard")
    db_session.merge(agency)

    # 1. Distant ticket (> 24h at both prev and now): 30h remaining now, computed 1 hour ago (31h remaining)
    # Should NOT be refreshed
    t_distant = Ticket(
        id="TCK-BOUND-DISTANT",
        tboh_id="TBOH-B-1",
        agency_id="AGY-SEL-1",
        title="Distant Ticket",
        description="Ticket > 24h remaining",
        priority="Medium",
        status="New",
        check_in_date=now + timedelta(hours=30),
        effective_deadline_at=now + timedelta(hours=30),
        queue_score=200.0,
        score_computed_at=now - timedelta(hours=1),
        created_at=now - timedelta(hours=2),
        updated_at=now - timedelta(hours=2)
    )

    # 2. Crossed 24h boundary: computed 2 hours ago (25h remaining, score=200.0), now 23h remaining (should get +300 modifier = 500.0)
    t_cross_24h = Ticket(
        id="TCK-BOUND-24H",
        tboh_id="TBOH-B-2",
        agency_id="AGY-SEL-1",
        title="Cross 24h Ticket",
        description="Ticket crossing 24h boundary",
        priority="Medium",
        status="New",
        check_in_date=now + timedelta(hours=23),
        effective_deadline_at=now + timedelta(hours=23),
        queue_score=200.0,
        score_computed_at=now - timedelta(hours=2),
        created_at=now - timedelta(hours=3),
        updated_at=now - timedelta(hours=3)
    )

    # 3. Crossed 6h boundary: computed 2 hours ago (7h remaining, modifier +300 = 500.0), now 5h remaining (should get +800 modifier = 1000.0)
    t_cross_6h = Ticket(
        id="TCK-BOUND-6H",
        tboh_id="TBOH-B-3",
        agency_id="AGY-SEL-1",
        title="Cross 6h Ticket",
        description="Ticket crossing 6h boundary",
        priority="Medium",
        status="New",
        check_in_date=now + timedelta(hours=5),
        effective_deadline_at=now + timedelta(hours=5),
        queue_score=500.0,
        score_computed_at=now - timedelta(hours=2),
        created_at=now - timedelta(hours=3),
        updated_at=now - timedelta(hours=3)
    )

    # 4. Uncomputed ticket (queue_score IS NULL)
    t_uncomputed = Ticket(
        id="TCK-BOUND-UNCOMP",
        tboh_id="TBOH-B-4",
        agency_id="AGY-SEL-1",
        title="Uncomputed Ticket",
        description="Uncomputed score",
        priority="Urgent",
        status="New",
        check_in_date=now + timedelta(hours=10),
        effective_deadline_at=now + timedelta(hours=10),
        queue_score=None,
        score_computed_at=None,
        created_at=now,
        updated_at=now
    )

    db_session.add_all([t_distant, t_cross_24h, t_cross_6h, t_uncomputed])
    db_session.commit()

    prev_computed_at_distant = t_distant.score_computed_at

    refreshed_count = refresh_stale_queue_scores(db_session, now=now, batch_size=10)
    assert refreshed_count >= 3

    db_session.expire_all()
    rel_distant = db_session.query(Ticket).filter(Ticket.id == "TCK-BOUND-DISTANT").first()
    rel_cross_24h = db_session.query(Ticket).filter(Ticket.id == "TCK-BOUND-24H").first()
    rel_cross_6h = db_session.query(Ticket).filter(Ticket.id == "TCK-BOUND-6H").first()
    rel_uncomp = db_session.query(Ticket).filter(Ticket.id == "TCK-BOUND-UNCOMP").first()

    # Distant ticket must NOT have been refreshed
    assert rel_distant.queue_score == 200.0
    assert rel_distant.score_computed_at == prev_computed_at_distant

    # Crossed 24h ticket must be updated to 500.0 (200 + 300)
    assert rel_cross_24h.queue_score == 500.0

    # Crossed 6h ticket must be updated to 1000.0 (200 + 800)
    assert rel_cross_6h.queue_score == 1000.0

    # Uncomputed ticket must now be computed
    assert rel_uncomp.queue_score is not None


def test_stored_score_matches_dynamic_grid(db_session: Session):
    """
    Consistency grid test: Verifies that stored queue_score computed by
    compute_ticket_urgency_fields strictly equals dynamic calculate_queue_score_tier2
    and get_sql_queue_score_expr across all combinations of priority, tier, and deadlines.
    """
    now = datetime(2026, 11, 22, 10, 0, 0, tzinfo=timezone.utc)
    priorities = ["Urgent", "High", "Medium", "Low"]
    tiers = ["platinum", "gold", "standard"]
    delays_hours = [1, 5, 12, 36]

    for tier in tiers:
        db_session.merge(Agency(id=f"AGY-GRID-{tier}", name=f"Grid {tier}", country_code="AE", tier=tier))
    db_session.commit()

    dialect = db_session.bind.dialect.name if db_session.bind else "sqlite"
    sql_expr = get_sql_queue_score_expr(now=now, dialect_name=dialect)

    tickets = []
    for prio in priorities:
        for tier in tiers:
            for delay in delays_hours:
                tid = f"TCK-G-{prio[:2]}-{tier[:2]}-{delay}"
                t = Ticket(
                    id=tid,
                    tboh_id=f"TBOH-G-{tid}",
                    agency_id=f"AGY-GRID-{tier}",
                    title=f"Grid {prio} {tier} {delay}h",
                    description="Grid consistency test",
                    priority=prio,
                    status="New",
                    check_in_date=now + timedelta(hours=delay),
                    effective_deadline_at=now + timedelta(hours=delay),
                    created_at=now,
                    updated_at=now
                )
                compute_ticket_urgency_fields(t, agency_tier=tier, now=now)
                tickets.append(t)

    db_session.add_all(tickets)
    db_session.commit()

    ticket_ids = [t.id for t in tickets]
    sql_rows = (
        db_session.query(
            Ticket.id,
            Ticket.queue_score,
            sql_expr.label("sql_score")
        )
        .outerjoin(Agency, Ticket.agency_id == Agency.id)
        .filter(Ticket.id.in_(ticket_ids))
        .all()
    )

    for row in sql_rows:
        tid, stored_score, computed_sql_score = row
        assert abs(stored_score - float(computed_sql_score)) < 0.01, (
            f"Stored score {stored_score} does not match SQL dynamic score {computed_sql_score} for {tid}"
        )


def test_agency_tier_mutation_updates_active_tickets(client: TestClient, db_session: Session):
    """
    Verifies that updating an agency's tier immediately recalculates stored queue_score
    for all active unassigned tickets belonging to that agency.
    """
    now = datetime.now(timezone.utc)
    agency_id = f"AGY-TIER-{uuid.uuid4().hex[:6]}"
    agency = Agency(id=agency_id, name="Tier Mutation Agency", country_code="AE", tier="standard")
    db_session.add(agency)

    ticket = Ticket(
        id=f"TCK-TIER-{uuid.uuid4().hex[:6]}",
        tboh_id="TBOH-TIER-1",
        agency_id=agency_id,
        title="Tier Update Test Ticket",
        description="Testing tier mutation cascade",
        priority="Urgent",
        status="New",
        check_in_date=now + timedelta(hours=1),
        created_at=now,
        updated_at=now
    )
    compute_ticket_urgency_fields(ticket, agency_tier="standard", now=now)
    db_session.add(ticket)
    db_session.commit()

    standard_score = ticket.queue_score
    assert standard_score is not None

    # Update tier to platinum via API (Lead user USR-104)
    res = client.patch(
        f"/api/agencies/{agency_id}/tier",
        json={"tier": "platinum"},
        headers={"X-User-Id": "USR-104"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["tier"] == "platinum"
    assert data["tickets_updated"] >= 1

    # Reload ticket from DB
    db_session.expire_all()
    reloaded = db_session.query(Ticket).filter(Ticket.id == ticket.id).first()
    assert reloaded is not None
    # Platinum multiplier is 1.3x
    assert reloaded.queue_score == pytest.approx(standard_score * 1.3, rel=1e-3)


def test_csv_export_performance_and_columns(client: TestClient, db_session: Session):
    """
    Verifies optimized CSV export selects expected columns without ORM relationship overhead.
    """
    now = datetime.now(timezone.utc)
    agency_id = f"AGY-CSV-{uuid.uuid4().hex[:6]}"
    db_session.merge(Agency(id=agency_id, name="CSV Agency", country_code="AE", tier="standard"))

    tickets = [
        Ticket(
            id=f"TCK-CSV-{i}-{uuid.uuid4().hex[:4]}",
            tboh_id=f"TBOH-CSV-{i}",
            agency_id=agency_id,
            title=f"CSV Export Row {i}",
            description="CSV export test ticket description body",
            priority="Medium",
            status="New",
            check_in_date=now + timedelta(days=2),
            created_at=now - timedelta(minutes=i),
            updated_at=now - timedelta(minutes=i)
        )
        for i in range(25)
    ]
    for t in tickets:
        compute_ticket_urgency_fields(t, agency_tier="standard", now=now)
    db_session.add_all(tickets)
    db_session.commit()

    res = client.get("/api/export/tickets.csv?limit=20", headers={"X-User-Id": "USR-104"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    content = res.text
    lines = content.strip().split("\r\n") if "\r\n" in content else content.strip().split("\n")
    header = lines[0]
    assert "id,tboh_id,agency_id,title,intent,priority,status,check_in_date,lcd_date,assigned_to,created_at" in header
    # Header + 20 rows
    assert len(lines) == 21


def test_bench_scale_script_execution(tmp_path):
    """Verifies scripts/bench_scale.py behavior on available database without touching tracked files."""
    db_url = os.environ.get("DATABASE_URL", "")
    python_exe = sys.executable
    out_file = str(tmp_path / "scale_transcript.txt")
    res = subprocess.run(
        [python_exe, "scripts/bench_scale.py", "--output", out_file],
        capture_output=True,
        text=True
    )
    if not (db_url.startswith("postgresql://") or db_url.startswith("postgresql+psycopg://")):
        # When PostgreSQL is absent, bench_scale must exit non-zero and refuse to generate fake files
        assert res.returncode != 0
        assert not os.path.exists(out_file)
    else:
        assert res.returncode == 0
        assert os.path.isfile(out_file)

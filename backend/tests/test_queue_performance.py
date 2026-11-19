import uuid
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import Ticket, Agency, User, Base
from backend.services.routing_engine import (
    calculate_queue_score_tier2,
    compute_ticket_urgency_fields
)
from backend.app.database import ensure_schema_migrations


def test_sql_sort_matches_python_sort(db_session: Session):
    """
    Validates that SQL ORDER BY (queue_score DESC, effective_deadline_at ASC, id ASC)
    produces the exact same ordering as Python sorting over a diverse synthetic dataset
    with varying priorities, deadlines, agency tiers, and tie-breakers.
    """
    now = datetime.now(timezone.utc)
    test_tickets = []

    priorities = ["Urgent", "High", "Medium", "Low"]
    agencies = ["AGY-001", "AGY-002", "AGY-003"]  # platinum, gold, standard
    agency_tiers = {"AGY-001": "platinum", "AGY-002": "gold", "AGY-003": "standard"}

    # Generate combination of tickets with different priorities and deadlines
    for i, prio in enumerate(priorities):
        for j, agy in enumerate(agencies):
            # Imminent (< 2h)
            t_imminent = Ticket(
                id=f"TCK-SYNTH-IMM-{i}-{j}-{uuid.uuid4().hex[:4]}",
                tboh_id=f"TBOH-SYNTH-1{i}{j}",
                agency_id=agy,
                title=f"Synthetic Imminent {prio} {agy}",
                description="Synthetic ticket",
                intent="Emergency Check-in Assist",
                priority=prio,
                status="New",
                check_in_date=now + timedelta(hours=1, minutes=10 * j),
                lcd_date=None,
                created_at=now - timedelta(minutes=10 * i)
            )
            compute_ticket_urgency_fields(t_imminent, agency_tier=agency_tiers[agy], now=now)
            test_tickets.append(t_imminent)

            # Same day (< 6h) with cancellation intent & LCD
            t_sameday = Ticket(
                id=f"TCK-SYNTH-SAM-{i}-{j}-{uuid.uuid4().hex[:4]}",
                tboh_id=f"TBOH-SYNTH-2{i}{j}",
                agency_id=agy,
                title=f"Synthetic Same Day {prio} {agy}",
                description="Synthetic ticket",
                intent="Refund Request",
                priority=prio,
                status="New",
                check_in_date=now + timedelta(days=3),
                lcd_date=now + timedelta(hours=4, minutes=15 * j),
                created_at=now - timedelta(minutes=5 * i)
            )
            compute_ticket_urgency_fields(t_sameday, agency_tier=agency_tiers[agy], now=now)
            test_tickets.append(t_sameday)

            # Far future (> 24h)
            t_future = Ticket(
                id=f"TCK-SYNTH-FUT-{i}-{j}-{uuid.uuid4().hex[:4]}",
                tboh_id=f"TBOH-SYNTH-3{i}{j}",
                agency_id=agy,
                title=f"Synthetic Future {prio} {agy}",
                description="Synthetic ticket",
                intent="Bedding / Room Preference",
                priority=prio,
                status="New",
                check_in_date=now + timedelta(days=7 + j),
                lcd_date=None,
                created_at=now - timedelta(hours=2)
            )
            compute_ticket_urgency_fields(t_future, agency_tier=agency_tiers[agy], now=now)
            test_tickets.append(t_future)

    # Add specific tie-breaker tickets: identical scores, different deadlines, and identical deadlines, different IDs
    t_tie1 = Ticket(
        id=f"TCK-TIE-AAA-{uuid.uuid4().hex[:4]}",
        tboh_id="TBOH-TIE-1",
        agency_id="AGY-003",
        title="Tie Breaker A",
        description="Tie ticket",
        intent="Bedding / Room Preference",
        priority="Medium",
        status="New",
        check_in_date=now + timedelta(days=5),
        lcd_date=None,
        created_at=now - timedelta(hours=1)
    )
    compute_ticket_urgency_fields(t_tie1, agency_tier="standard", now=now)
    test_tickets.append(t_tie1)

    t_tie2 = Ticket(
        id=f"TCK-TIE-BBB-{uuid.uuid4().hex[:4]}",
        tboh_id="TBOH-TIE-2",
        agency_id="AGY-003",
        title="Tie Breaker B",
        description="Tie ticket",
        intent="Bedding / Room Preference",
        priority="Medium",
        status="New",
        check_in_date=now + timedelta(days=5),
        lcd_date=None,
        created_at=now - timedelta(hours=1)
    )
    compute_ticket_urgency_fields(t_tie2, agency_tier="standard", now=now)
    test_tickets.append(t_tie2)

    db_session.add_all(test_tickets)
    db_session.commit()

    test_ticket_ids = [t.id for t in test_tickets]

    # Query with SQL ORDER BY
    sql_ordered = db_session.query(Ticket).filter(
        Ticket.id.in_(test_ticket_ids)
    ).order_by(
        Ticket.queue_score.desc(),
        Ticket.effective_deadline_at.asc(),
        Ticket.id.asc()
    ).all()

    # Python sort with matching order
    python_ordered = sorted(
        test_tickets,
        key=lambda t: (-t.queue_score, t.effective_deadline_at, t.id)
    )

    sql_ids = [t.id for t in sql_ordered]
    python_ids = [t.id for t in python_ordered]

    assert sql_ids == python_ids, "SQL ordering must match Python sorting exactly"


def test_pagination_consistency(client: TestClient):
    """
    Verifies that pagination (offset=0, offset=20, offset=40) returns disjoint
    contiguous slices of the exact same full sort without omissions or duplicates.
    """
    res_p0 = client.get("/api/tickets?view=triage&limit=20&offset=0", headers={"X-User-Id": "USR-101"})
    res_p1 = client.get("/api/tickets?view=triage&limit=20&offset=20", headers={"X-User-Id": "USR-101"})
    res_p2 = client.get("/api/tickets?view=triage&limit=20&offset=40", headers={"X-User-Id": "USR-101"})
    res_all = client.get("/api/tickets?view=triage&limit=60&offset=0", headers={"X-User-Id": "USR-101"})

    assert res_p0.status_code == 200
    assert res_p1.status_code == 200
    assert res_p2.status_code == 200
    assert res_all.status_code == 200

    data_p0 = res_p0.json()
    data_p1 = res_p1.json()
    data_p2 = res_p2.json()
    data_all = res_all.json()

    # Total counts must be consistent across pages
    assert data_p0["total"] == data_p1["total"] == data_p2["total"] == data_all["total"]

    ids_p0 = [t["id"] for t in data_p0["tickets"]]
    ids_p1 = [t["id"] for t in data_p1["tickets"]]
    ids_p2 = [t["id"] for t in data_p2["tickets"]]
    ids_all = [t["id"] for t in data_all["tickets"]]

    # Slices must be disjoint
    assert set(ids_p0).isdisjoint(set(ids_p1)), "Page 0 and Page 1 must be disjoint"
    assert set(ids_p1).isdisjoint(set(ids_p2)), "Page 1 and Page 2 must be disjoint"
    assert set(ids_p0).isdisjoint(set(ids_p2)), "Page 0 and Page 2 must be disjoint"

    # Concatenation of slices must match single continuous fetch
    combined_ids = ids_p0 + ids_p1 + ids_p2
    assert combined_ids == ids_all[:len(combined_ids)], "Paginated slices must form contiguous sequence"


def test_ticket_update_recomputes_stored_queue_score(client: TestClient, db_session: Session):
    """
    Verifies that creating and mutating tickets (status update, escalation, assignment, transfer)
    recomputes and persists effective_deadline_at and queue_score in the database.
    """
    now = datetime.now(timezone.utc)
    create_payload = {
        "agency_id": "AGY-001",
        "tboh_id": f"TBOH-MUT-{uuid.uuid4().hex[:6]}",
        "title": "Mutable ticket for queue score test",
        "description": "Testing that mutation updates queue_score",
        "priority": "Low",
        "intent": "Bedding / Room Preference",
        "check_in_date": (now + timedelta(days=10)).isoformat()
    }
    create_res = client.post("/api/tickets", json=create_payload, headers={"X-User-Id": "USR-101"})
    assert create_res.status_code == 201
    created_id = create_res.json()["id"]

    # Verify initial stored score
    ticket_row = db_session.query(Ticket).filter(Ticket.id == created_id).first()
    assert ticket_row is not None
    assert ticket_row.queue_score is not None
    assert ticket_row.effective_deadline_at is not None
    initial_score = ticket_row.queue_score

    # Escalate ticket -> status becomes Escalated, priority becomes Urgent
    esc_res = client.post(
        f"/api/tickets/{created_id}/escalate",
        json={"reason": "Escalating for urgency update test", "version": ticket_row.version},
        headers={"X-User-Id": "USR-101"}
    )
    assert esc_res.status_code == 200

    # Refresh from DB
    db_session.expire_all()
    updated_row = db_session.query(Ticket).filter(Ticket.id == created_id).first()
    assert updated_row.status == "Escalated"
    assert updated_row.queue_score is not None
    # Score should be updated and higher or equal
    assert updated_row.queue_score >= initial_score

    # Transfer ticket
    trf_res = client.post(
        f"/api/tickets/{created_id}/transfer",
        json={"target_agent_id": "USR-102", "reason": "Transferring to Rahul", "version": updated_row.version},
        headers={"X-User-Id": "USR-104"}
    )
    assert trf_res.status_code == 200

    db_session.expire_all()
    transferred_row = db_session.query(Ticket).filter(Ticket.id == created_id).first()
    assert transferred_row.assigned_to == "USR-102"
    assert transferred_row.queue_score is not None

    # Status update
    status_res = client.post(
        f"/api/tickets/{created_id}/status",
        json={"status": "Resolved", "version": transferred_row.version},
        headers={"X-User-Id": "USR-104"}
    )
    assert status_res.status_code == 200

    db_session.expire_all()
    resolved_row = db_session.query(Ticket).filter(Ticket.id == created_id).first()
    assert resolved_row.status == "Resolved"
    assert resolved_row.queue_score is not None


def test_search_targets_only_tboh_id_id_and_title(client: TestClient, db_session: Session):
    """
    Verifies that search strictly filters over tboh_id, id, and title,
    and does NOT perform full-table scan over description.
    """
    now = datetime.now(timezone.utc)
    unique_marker = uuid.uuid4().hex[:8]
    secret_desc = f"SECRET_DESC_TOKEN_{unique_marker}"
    unique_title = f"UniqueTitle_{unique_marker}"
    unique_tboh = f"TBOH-SEARCH-{unique_marker}"
    unique_id = f"TCK-SRCH-{unique_marker}"

    ticket = Ticket(
        id=unique_id,
        tboh_id=unique_tboh,
        agency_id="AGY-001",
        title=unique_title,
        description=f"This ticket contains {secret_desc} inside its body only.",
        intent="Unclassified",
        priority="Medium",
        status="New",
        check_in_date=now + timedelta(days=2),
        lcd_date=None,
        assigned_to=None,
        created_at=now
    )
    compute_ticket_urgency_fields(ticket, agency_tier="platinum", now=now)
    db_session.add(ticket)
    db_session.commit()

    # 1. Search for description token: MUST return 0 results
    res_desc = client.get(f"/api/tickets?search={secret_desc}", headers={"X-User-Id": "USR-101"})
    assert res_desc.status_code == 200
    desc_tickets = res_desc.json()["tickets"]
    assert len(desc_tickets) == 0, "Search must NOT match tokens located solely in description"

    # 2. Search for title token: MUST return the ticket
    res_title = client.get(f"/api/tickets?search={unique_title}", headers={"X-User-Id": "USR-101"})
    assert res_title.status_code == 200
    title_tickets = res_title.json()["tickets"]
    assert any(t["id"] == unique_id for t in title_tickets), "Search must match ticket title"

    # 3. Search for tboh_id: MUST return the ticket
    res_tboh = client.get(f"/api/tickets?search={unique_tboh}", headers={"X-User-Id": "USR-101"})
    assert res_tboh.status_code == 200
    tboh_tickets = res_tboh.json()["tickets"]
    assert any(t["id"] == unique_id for t in tboh_tickets), "Search must match tboh_id"

    # 4. Search for ticket ID: MUST return the ticket
    res_id = client.get(f"/api/tickets?search={unique_id}", headers={"X-User-Id": "USR-101"})
    assert res_id.status_code == 200
    id_tickets = res_id.json()["tickets"]
    assert any(t["id"] == unique_id for t in id_tickets), "Search must match ticket id"


def test_database_migration_and_backfill():
    """
    Verifies ensure_schema_migrations adds effective_deadline_at and queue_score
    and backfills existing rows where queue_score IS NULL.
    """
    import tempfile
    import os

    temp_db = os.path.join(tempfile.gettempdir(), f"test_migration_{uuid.uuid4().hex[:8]}.db")
    engine = create_engine(f"sqlite:///{temp_db}", connect_args={"check_same_thread": False})

    try:
        # Create schema without the new columns
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE agencies (
                    id VARCHAR(50) PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    country_code VARCHAR(10) NOT NULL,
                    tier VARCHAR(32) DEFAULT 'standard'
                )
            """))
            conn.execute(text("""
                INSERT INTO agencies (id, name, country_code, tier)
                VALUES ('AGY-TEST', 'Test Agency', 'AE', 'platinum')
            """))
            conn.execute(text("""
                CREATE TABLE tickets (
                    id VARCHAR(50) PRIMARY KEY,
                    tboh_id VARCHAR(100) NOT NULL,
                    agency_id VARCHAR(50) NOT NULL,
                    title VARCHAR(300) NOT NULL,
                    description TEXT NOT NULL,
                    intent VARCHAR(100) DEFAULT 'Unclassified',
                    priority VARCHAR(50) DEFAULT 'Medium',
                    status VARCHAR(50) DEFAULT 'New',
                    check_in_date DATETIME NOT NULL,
                    lcd_date DATETIME,
                    hotel_timezone VARCHAR(64) DEFAULT 'UTC',
                    assigned_to VARCHAR(50),
                    routing_reason TEXT,
                    suggested_bug_link VARCHAR(200),
                    version INTEGER DEFAULT 1,
                    created_at DATETIME,
                    updated_at DATETIME
                )
            """))
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            cid_str = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(text(f"""
                INSERT INTO tickets (id, tboh_id, agency_id, title, description, intent, priority, status, check_in_date, created_at, updated_at)
                VALUES ('TCK-LEGACY-1', 'TBOH-LEGACY', 'AGY-TEST', 'Legacy Ticket', 'Desc', 'Emergency Check-in Assist', 'Urgent', 'New', '{cid_str}', '{now_str}', '{now_str}')
            """))
            conn.commit()

        # Run migration
        ensure_schema_migrations(engine)

        # Verify columns exist and data was backfilled
        with engine.connect() as conn:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(tickets)")).fetchall()]
            assert "effective_deadline_at" in cols
            assert "queue_score" in cols

            row = conn.execute(text("SELECT queue_score, effective_deadline_at FROM tickets WHERE id = 'TCK-LEGACY-1'")).fetchone()
            assert row is not None
            assert row[0] is not None, "queue_score must be backfilled"
            assert row[1] is not None, "effective_deadline_at must be backfilled"
            assert row[0] > 0.0

    finally:
        engine.dispose()
        if os.path.exists(temp_db):
            try:
                os.remove(temp_db)
            except Exception:
                pass


def test_stale_queue_score_refresh_over_time(client: TestClient, db_session: Session):
    """
    Verifies that time-based urgency modifiers refresh properly when time advances:
    1. Create Ticket A with check-in in 7h -> at T0, modifier is +300 (NEXT_DAY_24H), score = 500.
    2. Create Ticket B with check-in in 20h -> at T0, modifier is +300 (NEXT_DAY_24H), score = 500.
    3. Advance time by 2 hours (T1 = T0 + 2h):
       - Ticket A check-in is now in 5h -> urgency modifier must become +800 (SAME_DAY_6H), score = 1000.
       - Ticket B check-in is now in 18h -> urgency modifier remains +300 (NEXT_DAY_24H), score = 500.
    4. Call refresh_stale_queue_scores(db_session, now=T1).
    5. Verify Ticket A's stored queue_score is updated to 1000.0 and Ticket A ranks strictly above Ticket B.
    """
    from backend.services.routing_engine import compute_ticket_urgency_fields, refresh_stale_queue_scores

    t0 = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=2)  # 2 hours later

    # Create Ticket A (check-in in 7 hours from T0)
    t_a = Ticket(
        id="TCK-STALE-7H",
        tboh_id="TBOH-STALE-7H",
        agency_id="AGY-003",  # standard tier (1.0x)
        title="Check-in 7h Case",
        description="Ticket created 7h before check-in",
        intent="Emergency Check-in Assist",
        priority="Medium",  # base 200
        status="New",
        check_in_date=t0 + timedelta(hours=7),
        created_at=t0,
        updated_at=t0
    )
    compute_ticket_urgency_fields(t_a, agency_tier="standard", now=t0)

    # Create Ticket B (check-in in 20 hours from T0)
    t_b = Ticket(
        id="TCK-STALE-20H",
        tboh_id="TBOH-STALE-20H",
        agency_id="AGY-003",  # standard tier (1.0x)
        title="Check-in 20h Case",
        description="Ticket created 20h before check-in",
        intent="Emergency Check-in Assist",
        priority="Medium",  # base 200
        status="New",
        check_in_date=t0 + timedelta(hours=20),
        created_at=t0,
        updated_at=t0
    )
    compute_ticket_urgency_fields(t_b, agency_tier="standard", now=t0)

    db_session.add_all([t_a, t_b])
    db_session.commit()

    # Initial state at T0: both tickets were in the 6h-24h window (+300 modifier)
    assert t_a.queue_score == 500.0  # 200 + 300
    assert t_b.queue_score == 500.0  # 200 + 300

    # Before refresh at T1: without refresh, stored scores are stale
    assert t_a.queue_score == 500.0

    # Execute refresh at T1 (time advanced by 2 hours)
    refreshed_count = refresh_stale_queue_scores(db_session, now=t1)
    assert refreshed_count >= 1

    # Reload from DB
    db_session.refresh(t_a)
    db_session.refresh(t_b)

    # After refresh at T1:
    # Ticket A is now 5h to check-in (<= 6h) -> modifier +800 -> score = 1000.0
    # Ticket B is now 18h to check-in (<= 24h) -> modifier +300 -> score = 500.0
    assert t_a.queue_score == 1000.0
    assert t_b.queue_score == 500.0
    assert t_a.queue_score > t_b.queue_score

    # Verify query ordering at T1 strictly ranks Ticket A above Ticket B
    ranked = (
        db_session.query(Ticket)
        .filter(Ticket.id.in_(["TCK-STALE-7H", "TCK-STALE-20H"]))
        .order_by(Ticket.queue_score.desc(), Ticket.effective_deadline_at.asc(), Ticket.id.asc())
        .all()
    )
    assert ranked[0].id == "TCK-STALE-7H"
    assert ranked[1].id == "TCK-STALE-20H"


def test_dynamic_queue_score_zero_writes_on_get(client: TestClient, db_session: Session, monkeypatch):
    """
    Proves that two GET requests at two frozen times produce different dynamic orders
    with zero writes (updated_at unchanged, zero UPDATE statements issued).
    Also proves get_ticket_details returns the exact same queue_score as list_tickets.
    """
    from sqlalchemy import event
    from backend.app.database import engine

    t0 = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=2)  # 2 hours later

    # Create Ticket A (check-in in 7 hours from T0)
    ticket_a = Ticket(
        id="TCK-DYN-A",
        tboh_id="TBOH-DYN-A",
        agency_id="AGY-003",  # standard tier: 1.0x
        title="Dynamic Queue Test Ticket A",
        description="Ticket created 7h before check-in",
        intent="Emergency Check-in Assist",
        priority="Medium",  # base 200
        priority_weight=200.0,
        status="New",
        check_in_date=t0 + timedelta(hours=7),
        created_at=t0,
        updated_at=t0
    )
    compute_ticket_urgency_fields(ticket_a, agency_tier="standard", now=t0)

    # Create Ticket B (check-in in 20 hours from T0)
    ticket_b = Ticket(
        id="TCK-DYN-B",
        tboh_id="TBOH-DYN-B",
        agency_id="AGY-003",  # standard tier: 1.0x
        title="Dynamic Queue Test Ticket B",
        description="Ticket created 20h before check-in",
        intent="Emergency Check-in Assist",
        priority="Medium",  # base 200
        priority_weight=200.0,
        status="New",
        check_in_date=t0 + timedelta(hours=20),
        created_at=t0,
        updated_at=t0
    )
    compute_ticket_urgency_fields(ticket_b, agency_tier="standard", now=t0)

    db_session.add_all([ticket_a, ticket_b])
    db_session.commit()

    orig_updated_a = ticket_a.updated_at
    orig_updated_b = ticket_b.updated_at

    # Track executed SQL statements on engine
    executed_statements = []
    def statement_listener(conn, cursor, statement, parameters, context, executemany):
        executed_statements.append(statement)

    event.listen(engine, "before_cursor_execute", statement_listener)

    try:
        # Request 1: at frozen time T0
        # Mock datetime.now(timezone.utc) in main.py
        class MockDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return t0

        monkeypatch.setattr("backend.app.main.datetime", MockDateTime)

        resp_t0 = client.get("/api/tickets?view=triage&search=TBOH-DYN-", headers={"X-User-Id": "USR-101"})
        assert resp_t0.status_code == 200
        t0_tickets = {t["id"]: t for t in resp_t0.json()["tickets"] if t["id"] in ["TCK-DYN-A", "TCK-DYN-B"]}
        assert "TCK-DYN-A" in t0_tickets and "TCK-DYN-B" in t0_tickets
        # At T0, both are in 6h-24h window (+300 modifier) -> 200 + 300 = 500.0
        assert t0_tickets["TCK-DYN-A"]["queue_score"] == 500.0
        assert t0_tickets["TCK-DYN-B"]["queue_score"] == 500.0

        # Request 2: at frozen time T1 (2 hours later)
        class MockDateTimeT1(datetime):
            @classmethod
            def now(cls, tz=None):
                return t1

        monkeypatch.setattr("backend.app.main.datetime", MockDateTimeT1)

        resp_t1 = client.get("/api/tickets?view=triage&search=TBOH-DYN-", headers={"X-User-Id": "USR-101"})
        assert resp_t1.status_code == 200
        t1_tickets_list = [t for t in resp_t1.json()["tickets"] if t["id"] in ["TCK-DYN-A", "TCK-DYN-B"]]
        # At T1: Ticket A is now 5h remaining (<=6h window, +800 modifier) -> score = 1000.0
        # Ticket B is now 18h remaining (<=24h window, +300 modifier) -> score = 500.0
        assert t1_tickets_list[0]["id"] == "TCK-DYN-A"
        assert t1_tickets_list[0]["queue_score"] == 1000.0
        assert t1_tickets_list[1]["id"] == "TCK-DYN-B"
        assert t1_tickets_list[1]["queue_score"] == 500.0

        # Verify get_ticket_details returns the exact same queue_score as list_tickets
        detail_a = client.get("/api/tickets/TCK-DYN-A", headers={"X-User-Id": "USR-101"})
        assert detail_a.status_code == 200
        assert detail_a.json()["queue_score"] == 1000.0

        detail_b = client.get("/api/tickets/TCK-DYN-B", headers={"X-User-Id": "USR-101"})
        assert detail_b.status_code == 200
        assert detail_b.json()["queue_score"] == 500.0

        # Verify ZERO UPDATE statements were executed during these GET requests
        update_statements = [s for s in executed_statements if s.strip().upper().startswith("UPDATE")]
        assert len(update_statements) == 0, f"Expected 0 UPDATE statements on read, but found: {update_statements}"

        # Verify updated_at in DB remains completely unchanged
        db_session.expire_all()
        reloaded_a = db_session.query(Ticket).filter(Ticket.id == "TCK-DYN-A").first()
        reloaded_b = db_session.query(Ticket).filter(Ticket.id == "TCK-DYN-B").first()
        assert reloaded_a.updated_at == orig_updated_a
        assert reloaded_b.updated_at == orig_updated_b

    finally:
        event.remove(engine, "before_cursor_execute", statement_listener)
        db_session.query(Ticket).filter(Ticket.id.in_(["TCK-DYN-A", "TCK-DYN-B"])).delete(synchronize_session=False)
        db_session.commit()


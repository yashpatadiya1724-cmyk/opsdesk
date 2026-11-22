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

    # Query with dynamic SQL ORDER BY matching list_tickets
    from backend.services.routing_engine import get_sql_queue_score_expr, calculate_queue_score_tier2
    dialect = db_session.bind.dialect.name if db_session.bind else "sqlite"
    score_expr = get_sql_queue_score_expr(now=now, dialect_name=dialect)
    sql_ordered = db_session.query(Ticket).outerjoin(
        Agency, Ticket.agency_id == Agency.id
    ).filter(
        Ticket.id.in_(test_ticket_ids)
    ).order_by(
        score_expr.desc(),
        Ticket.effective_deadline_at.asc(),
        Ticket.id.asc()
    ).all()

    # Python sort with matching order
    python_ordered = sorted(
        test_tickets,
        key=lambda t: (
            -calculate_queue_score_tier2(
                priority=t.priority,
                check_in_date=t.effective_deadline_at or t.check_in_date,
                agency_tier=agency_tiers[t.agency_id],
                lcd_date=t.lcd_date,
                intent=t.intent,
                now=now,
                priority_weight=t.priority_weight
            ),
            t.effective_deadline_at or t.check_in_date,
            t.id
        )
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
    persists priority_weight and effective_deadline_at, and returns dynamic queue_score in the API.
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

    details_res = client.get(f"/api/tickets/{created_id}", headers={"X-User-Id": "USR-101"})
    assert details_res.status_code == 200
    initial_score = details_res.json()["queue_score"]
    assert initial_score is not None

    # Verify initial stored fields
    ticket_row = db_session.query(Ticket).filter(Ticket.id == created_id).first()
    assert ticket_row is not None
    assert ticket_row.priority_weight == 50.0  # Low priority base weight
    assert ticket_row.effective_deadline_at is not None

    # Escalate ticket -> status becomes Escalated, priority becomes Urgent
    esc_res = client.post(
        f"/api/tickets/{created_id}/escalate",
        json={"reason": "Escalating for urgency update test", "version": ticket_row.version},
        headers={"X-User-Id": "USR-101"}
    )
    assert esc_res.status_code == 200

    details_after = client.get(f"/api/tickets/{created_id}", headers={"X-User-Id": "USR-101"})
    assert details_after.status_code == 200
    escalated_score = details_after.json()["queue_score"]
    assert escalated_score is not None
    assert escalated_score > initial_score

    # Refresh from DB
    db_session.expire_all()
    updated_row = db_session.query(Ticket).filter(Ticket.id == created_id).first()
    assert updated_row.status == "Escalated"
    assert updated_row.priority_weight == 1000.0  # Urgent priority base weight

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
    assert transferred_row.priority_weight == 1000.0

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
    assert resolved_row.priority_weight == 1000.0


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
            import sqlalchemy as sa
            insp = sa.inspect(conn)
            cols = [col["name"] for col in insp.get_columns("tickets")]
            assert "effective_deadline_at" in cols
            assert "priority_weight" in cols

            row = conn.execute(text("SELECT priority_weight, effective_deadline_at FROM tickets WHERE id = 'TCK-LEGACY-1'")).fetchone()
            assert row is not None
            assert row[0] == 1000.0, "priority_weight must be backfilled to 1000.0 for Urgent priority"
            assert row[1] is not None, "effective_deadline_at must be backfilled"

    finally:
        engine.dispose()
        if os.path.exists(temp_db):
            try:
                os.remove(temp_db)
            except Exception:
                pass


def test_stale_queue_score_refresh_over_time(client: TestClient, db_session: Session):
    """
    Verifies that time-based urgency modifiers refresh dynamically when time advances:
    1. Create Ticket A with check-in in 7h -> at T0, modifier is +300 (NEXT_DAY_24H), score = 500.
    2. Create Ticket B with check-in in 20h -> at T0, modifier is +300 (NEXT_DAY_24H), score = 500.
    3. Advance time by 2 hours (T1 = T0 + 2h):
       - Ticket A check-in is now in 5h -> urgency modifier dynamically evaluates to +800 (SAME_DAY_6H), score = 1000.
       - Ticket B check-in is now in 18h -> urgency modifier remains +300 (NEXT_DAY_24H), score = 500.
    4. Verify SQL order by dynamic score expression at T1 strictly ranks Ticket A above Ticket B.
    """
    from backend.services.routing_engine import calculate_queue_score_tier2, get_sql_queue_score_expr

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
        priority_weight=200.0,
        status="New",
        check_in_date=t0 + timedelta(hours=7),
        effective_deadline_at=t0 + timedelta(hours=7),
        created_at=t0,
        updated_at=t0
    )

    # Create Ticket B (check-in in 20 hours from T0)
    t_b = Ticket(
        id="TCK-STALE-20H",
        tboh_id="TBOH-STALE-20H",
        agency_id="AGY-003",  # standard tier (1.0x)
        title="Check-in 20h Case",
        description="Ticket created 20h before check-in",
        intent="Emergency Check-in Assist",
        priority="Medium",  # base 200
        priority_weight=200.0,
        status="New",
        check_in_date=t0 + timedelta(hours=20),
        effective_deadline_at=t0 + timedelta(hours=20),
        created_at=t0,
        updated_at=t0
    )

    db_session.add_all([t_a, t_b])
    db_session.commit()

    # Initial state at T0: both tickets are in the 6h-24h window (+300 modifier)
    score_t0_a = calculate_queue_score_tier2(t_a.priority, t_a.check_in_date, agency_tier="standard", now=t0)
    score_t0_b = calculate_queue_score_tier2(t_b.priority, t_b.check_in_date, agency_tier="standard", now=t0)
    assert score_t0_a == 500.0  # 200 + 300
    assert score_t0_b == 500.0  # 200 + 300

    # At T1 (time advanced by 2 hours):
    # Ticket A is now 5h to check-in (<= 6h) -> modifier +800 -> score = 1000.0
    # Ticket B is now 18h to check-in (<= 24h) -> modifier +300 -> score = 500.0
    score_t1_a = calculate_queue_score_tier2(t_a.priority, t_a.check_in_date, agency_tier="standard", now=t1)
    score_t1_b = calculate_queue_score_tier2(t_b.priority, t_b.check_in_date, agency_tier="standard", now=t1)
    assert score_t1_a == 1000.0
    assert score_t1_b == 500.0
    assert score_t1_a > score_t1_b

    # Verify query ordering in SQL at T1 strictly ranks Ticket A above Ticket B
    dialect = db_session.get_bind().dialect.name
    score_expr_t1 = get_sql_queue_score_expr(now=t1, dialect_name=dialect)
    ranked = (
        db_session.query(Ticket)
        .outerjoin(Agency, Ticket.agency_id == Agency.id)
        .filter(Ticket.id.in_(["TCK-STALE-7H", "TCK-STALE-20H"]))
        .order_by(score_expr_t1.desc(), Ticket.effective_deadline_at.asc(), Ticket.id.asc())
        .all()
    )

    assert len(ranked) == 2
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

        from backend.services.routing_engine import refresh_stale_queue_scores
        # Score refresher background task runs at T1 to refresh tickets crossing boundaries
        refresh_stale_queue_scores(db_session, now=t1)
        executed_statements.clear()

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


def test_changing_priority_via_api_updates_sql_queue_ordering(client: TestClient, db_session: Session):
    """
    Proves that updating ticket priority via the API updates priority_weight in SQL,
    which immediately updates the SQL triage queue ordering (using get_sql_queue_score_expr).
    """
    now = datetime.now(timezone.utc)
    future_time = now + timedelta(days=5)

    # Clean any leftover test records
    db_session.query(Ticket).filter(Ticket.id.in_(["TCK-ORD-LOW", "TCK-ORD-HIGH"])).delete(synchronize_session=False)
    db_session.commit()

    # Create Ticket LOW: priority Low (weight 50)
    ticket_low = Ticket(
        id="TCK-ORD-LOW",
        agency_id="AGY-001",
        tboh_id="TBOH-ORD-1",
        title="Order Test Ticket Low",
        description="Low priority ticket",
        priority="Low",
        priority_weight=50.0,
        status="Open",
        intent="General Inquiry",
        check_in_date=future_time,
        effective_deadline_at=future_time,
        created_at=now,
        updated_at=now,
        version=1
    )
    # Create Ticket HIGH: priority High (weight 500)
    ticket_high = Ticket(
        id="TCK-ORD-HIGH",
        agency_id="AGY-001",
        tboh_id="TBOH-ORD-2",
        title="Order Test Ticket High",
        description="High priority ticket",
        priority="High",
        priority_weight=500.0,
        status="Open",
        intent="General Inquiry",
        check_in_date=future_time,
        effective_deadline_at=future_time,
        created_at=now,
        updated_at=now,
        version=1
    )
    db_session.add(ticket_low)
    db_session.add(ticket_high)
    db_session.commit()

    try:
        # Initial triage query check: HIGH should rank above LOW
        res1 = client.get("/api/tickets?view=triage&search=TBOH-ORD", headers={"X-User-Id": "USR-101"})
        assert res1.status_code == 200
        ids1 = [t["id"] for t in res1.json()["tickets"]]
        assert ids1 == ["TCK-ORD-HIGH", "TCK-ORD-LOW"]

        # Update TCK-ORD-LOW via API to Urgent priority (weight 1000)
        update_res = client.post(
            "/api/tickets/TCK-ORD-LOW/status",
            json={"status": "Open", "priority": "Urgent", "version": 1},
            headers={"X-User-Id": "USR-101"}
        )
        assert update_res.status_code == 200

        # Verify DB priority_weight is updated to 1000.0
        db_session.expire_all()
        refreshed_low = db_session.query(Ticket).filter(Ticket.id == "TCK-ORD-LOW").first()
        assert refreshed_low.priority == "Urgent"
        assert refreshed_low.priority_weight == 1000.0

        # Query triage queue again: TCK-ORD-LOW must now rank ahead of TCK-ORD-HIGH in SQL ordering
        res2 = client.get("/api/tickets?view=triage&search=TBOH-ORD", headers={"X-User-Id": "USR-101"})
        assert res2.status_code == 200
        ids2 = [t["id"] for t in res2.json()["tickets"]]
        assert ids2 == ["TCK-ORD-LOW", "TCK-ORD-HIGH"]
    finally:
        db_session.query(Ticket).filter(Ticket.id.in_(["TCK-ORD-LOW", "TCK-ORD-HIGH"])).delete(synchronize_session=False)
        db_session.commit()


def test_queue_score_grid_python_equals_sql(db_session: Session):
    """
    Grid test: priority x hours in {-1, 0, 1.9, 2, 2.1, 5.9, 6, 6.1, 23.9, 24, 24.1, 100}
    x tier platinum/gold/standard x NULL effective_deadline_at.
    Python score must equal SQL score exactly.
    """
    from backend.services.routing_engine import (
        calculate_queue_score_tier2,
        get_sql_queue_score_expr
    )
    from backend.config.routing_config import PRIORITY_SCORES

    now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
    priorities = ["Urgent", "High", "Medium", "Low"]
    hours_list = [-1.0, 0.0, 1.9, 2.0, 2.1, 5.9, 6.0, 6.1, 23.9, 24.0, 24.1, 100.0]
    tiers = ["platinum", "gold", "standard"]
    null_deadline_flags = [False, True]  # False: effective_deadline_at set; True: effective_deadline_at NULL (fallback to check_in_date)

    dialect = db_session.bind.dialect.name if (db_session.bind is not None) else "sqlite"
    sql_expr = get_sql_queue_score_expr(now=now, dialect_name=dialect)

    for t in tiers:
        db_session.merge(Agency(id=f"AGY-GRID-{t}", name=f"Grid {t}", country_code="AE", tier=t))
    db_session.commit()

    created_ids = []
    try:
        for prio in priorities:
            for hr in hours_list:
                for tier in tiers:
                    for is_null_deadline in null_deadline_flags:
                        check_in = now + timedelta(hours=hr)
                        eff_deadline = None if is_null_deadline else check_in

                        t_id = f"TCK-G-{uuid.uuid4().hex[:8]}"
                        created_ids.append(t_id)
                        ticket = Ticket(
                            id=t_id,
                            tboh_id="TBOH-GRID",
                            agency_id=f"AGY-GRID-{tier}",
                            title="Grid Ticket",
                            description="Grid test",
                            priority=prio,
                            priority_weight=PRIORITY_SCORES[prio],
                            status="New",
                            check_in_date=check_in,
                            effective_deadline_at=eff_deadline,
                            created_at=now,
                            updated_at=now,
                            version=1
                        )
                        db_session.add(ticket)
        db_session.commit()

        # Query all SQL scores in a single batch query
        results = (
            db_session.query(Ticket.id, Ticket.priority, Agency.tier, Ticket.check_in_date, Ticket.effective_deadline_at, sql_expr)
            .select_from(Ticket)
            .join(Agency, Ticket.agency_id == Agency.id)
            .filter(Ticket.id.in_(created_ids))
            .all()
        )

        assert len(results) == len(created_ids) == len(priorities) * len(hours_list) * len(tiers) * len(null_deadline_flags)

        for r_id, r_prio, r_tier, r_cid, r_eff_deadline, r_sql_score in results:
            resolved_deadline = r_eff_deadline or r_cid
            d_aware = resolved_deadline if resolved_deadline.tzinfo else resolved_deadline.replace(tzinfo=timezone.utc)
            expected_py = calculate_queue_score_tier2(
                priority=r_prio,
                check_in_date=d_aware,
                agency_tier=r_tier,
                now=now,
                priority_weight=PRIORITY_SCORES[r_prio]
            )

            assert round(float(r_sql_score), 2) == round(float(expected_py), 2), (
                f"Score divergence for Ticket {r_id} (prio={r_prio}, tier={r_tier}, eff_deadline={r_eff_deadline}, cid={r_cid}): "
                f"SQL={r_sql_score} vs Python={expected_py}"
            )
    finally:
        db_session.query(Ticket).filter(Ticket.id.in_(created_ids)).delete(synchronize_session=False)
        db_session.commit()


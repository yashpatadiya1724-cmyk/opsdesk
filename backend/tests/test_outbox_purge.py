import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.database import Base
from backend.app.models import EventOutbox
from scripts.outbox_worker import OutboxWorker

def test_outbox_retention_purge():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    old_time = now_utc - timedelta(days=45)
    recent_time = now_utc - timedelta(days=10)

    # 1. Old delivered event (should be purged)
    e_old_delivered = EventOutbox(
        id="evt-old-del",
        event_type="ticket.created",
        ticket_id="TCK-1",
        agency_id="AGY-001",
        visibility="public",
        payload_json="{}",
        status="delivered",
        delivered_at=old_time,
        created_at=old_time
    )

    # 2. Recent delivered event (should be preserved)
    e_recent_delivered = EventOutbox(
        id="evt-rec-del",
        event_type="ticket.assigned",
        ticket_id="TCK-2",
        agency_id="AGY-001",
        visibility="public",
        payload_json="{}",
        status="delivered",
        delivered_at=recent_time,
        created_at=recent_time
    )

    # 3. Old dead-letter event (must NEVER be purged, preserved for auditability)
    e_old_dlq = EventOutbox(
        id="evt-old-dlq",
        event_type="ticket.status_changed",
        ticket_id="TCK-3",
        agency_id="AGY-001",
        visibility="public",
        payload_json="{}",
        status="dead_letter",
        retry_count=5,
        last_error="External endpoint timeout",
        created_at=old_time
    )

    # 4. Undelivered pending event (must NEVER be purged)
    e_pending = EventOutbox(
        id="evt-pending",
        event_type="ticket.escalated",
        ticket_id="TCK-4",
        agency_id="AGY-001",
        visibility="public",
        payload_json="{}",
        status="pending",
        created_at=old_time
    )

    db.add_all([e_old_delivered, e_recent_delivered, e_old_dlq, e_pending])
    db.commit()

    worker = OutboxWorker(db_factory=session_factory)
    purged_count = worker.purge_delivered_retention(retention_days=30)

    assert purged_count == 1

    remaining = db.query(EventOutbox).all()
    remaining_ids = {r.id for r in remaining}

    assert "evt-old-del" not in remaining_ids
    assert "evt-rec-del" in remaining_ids
    assert "evt-old-dlq" in remaining_ids
    assert "evt-pending" in remaining_ids

    db.close()

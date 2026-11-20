import os
import tempfile
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models import Base, Agency, Ticket, EventOutbox
from backend.app.events import emit_outbox_event
from backend.app.database import ensure_schema_migrations
from scripts.outbox_worker import OutboxWorker


@pytest.fixture
def temp_db():
    temp_fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(temp_fd)
    db_url = f"sqlite:///{temp_path}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)
    Session = sessionmaker(bind=engine)

    # Seed minimal agency and ticket
    session = Session()
    agency = Agency(id="ag_demo_1", name="Demo Agency", country_code="IN", tier="Standard")
    session.add(agency)
    session.commit()

    ticket = Ticket(
        id="TCK-OUTBOX-001",
        tboh_id="TBOH-9999",
        title="Outbox Test Ticket",
        description="Testing outbox worker dispatch",
        priority="Medium",
        status="New",
        check_in_date=datetime.now(timezone.utc),
        agency_id="ag_demo_1"
    )
    session.add(ticket)
    session.commit()
    session.close()

    yield Session, temp_path

    try:
        os.remove(temp_path)
    except Exception:
        pass


def test_outbox_worker_successful_delivery(temp_db):
    Session, _ = temp_db
    session = Session()

    event = emit_outbox_event(
        db=session,
        event_type="ticket.created",
        ticket_id="TCK-OUTBOX-001",
        agency_id="ag_demo_1",
        visibility="public",
        payload={"action": "created", "ticket_id": "TCK-OUTBOX-001"}
    )
    session.commit()
    event_id = event.id
    session.close()

    worker = OutboxWorker(db_factory=Session, max_retries=3, batch_size=10)
    stats = worker.process_batch()

    assert stats["processed"] == 1
    assert stats["delivered"] == 1
    assert stats["retried"] == 0
    assert stats["dead_letter"] == 0

    session2 = Session()
    refreshed = session2.query(EventOutbox).filter_by(id=event_id).first()
    assert refreshed is not None
    assert refreshed.status == "delivered"
    assert refreshed.delivered_at is not None
    assert refreshed.retry_count == 0
    assert refreshed.last_error is None
    session2.close()


def test_outbox_worker_retry_mechanism(temp_db):
    Session, _ = temp_db
    session = Session()

    event = emit_outbox_event(
        db=session,
        event_type="ticket.status_changed",
        ticket_id="TCK-OUTBOX-001",
        agency_id="ag_demo_1",
        visibility="internal",
        payload={"action": "escalated"}
    )
    session.commit()
    event_id = event.id
    session.close()

    def failing_dispatcher(evt):
        raise ConnectionResetError("Remote webhook refused connection")

    worker = OutboxWorker(db_factory=Session, max_retries=3, batch_size=10)
    stats = worker.process_batch(dispatch_fn=failing_dispatcher)

    assert stats["processed"] == 1
    assert stats["delivered"] == 0
    assert stats["retried"] == 1
    assert stats["dead_letter"] == 0

    session2 = Session()
    refreshed = session2.query(EventOutbox).filter_by(id=event_id).first()
    assert refreshed is not None
    assert refreshed.status == "retry"
    assert refreshed.delivered_at is None
    assert refreshed.retry_count == 1
    assert "Remote webhook refused connection" in refreshed.last_error
    session2.close()


def test_outbox_worker_dead_letter_queue(temp_db):
    Session, _ = temp_db
    session = Session()

    event = emit_outbox_event(
        db=session,
        event_type="ticket.assigned",
        ticket_id="TCK-OUTBOX-001",
        agency_id="ag_demo_1",
        visibility="public",
        payload={"action": "assigned"}
    )
    session.commit()
    event_id = event.id
    session.close()

    def permanently_failing_dispatcher(evt):
        raise TimeoutError("Upstream webhook timed out repeatedly")

    worker = OutboxWorker(db_factory=Session, max_retries=2, batch_size=10)

    # First attempt: triggers retry 1
    stats1 = worker.process_batch(dispatch_fn=permanently_failing_dispatcher)
    assert stats1["retried"] == 1
    assert stats1["dead_letter"] == 0

    # Second attempt: reaches max_retries (2) -> transitions to dead_letter
    stats2 = worker.process_batch(dispatch_fn=permanently_failing_dispatcher)
    assert stats2["retried"] == 0
    assert stats2["dead_letter"] == 1

    session2 = Session()
    refreshed = session2.query(EventOutbox).filter_by(id=event_id).first()
    assert refreshed is not None
    assert refreshed.status == "dead_letter"
    assert refreshed.delivered_at is None
    assert refreshed.retry_count == 2
    assert "Upstream webhook timed out repeatedly" in refreshed.last_error
    session2.close()

    # Third attempt: should NOT process dead-lettered event again
    stats3 = worker.process_batch(dispatch_fn=permanently_failing_dispatcher)
    assert stats3["processed"] == 0

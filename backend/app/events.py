import uuid
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from backend.app.models import EventOutbox, AuditLog

def emit_outbox_event(
    db: Session,
    event_type: str,
    ticket_id: str,
    agency_id: str,
    visibility: str,
    payload: dict
) -> EventOutbox:
    """
    Atomically enqueues an event into the events_outbox table.
    Visibility must be 'public' (accessible to agency requesters) or 'internal' (staff only).
    """
    event = EventOutbox(
        id=f"EVT-{uuid.uuid4().hex[:12].upper()}",
        event_type=event_type,
        ticket_id=ticket_id,
        agency_id=agency_id,
        visibility=visibility,
        payload_json=json.dumps(payload, default=str),
        created_at=datetime.now(timezone.utc)
    )
    db.add(event)
    return event

def record_audit_log(
    db: Session,
    ticket_id: str,
    actor_id: str,
    action: str,
    details: dict
) -> AuditLog:
    """
    Atomically records an action in the audit_logs table.
    """
    audit = AuditLog(
        id=f"AUD-{uuid.uuid4().hex[:12].upper()}",
        ticket_id=ticket_id,
        actor_id=actor_id,
        action=action,
        details=json.dumps(details, default=str),
        created_at=datetime.now(timezone.utc)
    )
    db.add(audit)
    return audit

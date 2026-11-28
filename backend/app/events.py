import uuid
import json
import asyncio
from datetime import datetime, timezone
from typing import Set, Dict, Any, Optional
from sqlalchemy.orm import Session
from backend.app.models import EventOutbox, AuditLog


class Subscriber:
    """Represents an active SSE client listener with tenant context."""
    def __init__(self, user_id: str, agency_id: Optional[str], role: str):
        self.user_id = user_id
        self.agency_id = agency_id
        self.role = role
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=100)


class EventBroadcaster:
    """
    Lightweight, thread-safe in-memory event broadcaster for Server-Sent Events (SSE).
    Provides real-time pub-sub across all worker tasks with strict multi-tenant isolation.
    """
    def __init__(self):
        self._subscribers: Set[Subscriber] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self, user_id: str, agency_id: Optional[str], role: str) -> Subscriber:
        sub = Subscriber(user_id=user_id, agency_id=agency_id, role=role)
        async with self._lock:
            self._subscribers.add(sub)
        return sub

    async def unsubscribe(self, sub: Subscriber):
        async with self._lock:
            self._subscribers.discard(sub)

    @property
    def active_subscribers_count(self) -> int:
        return len(self._subscribers)

    def broadcast_sync(
        self,
        event_type: str,
        ticket_id: str,
        agency_id: str,
        visibility: str,
        payload: dict
    ):
        """Thread-safe dispatch from sync SQLAlchemy session code into the event loop."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast(event_type, ticket_id, agency_id, visibility, payload))
        except RuntimeError:
            # No active event loop (e.g. offline migrations or CLI seeds)
            pass

    async def broadcast(
        self,
        event_type: str,
        ticket_id: str,
        agency_id: str,
        visibility: str,
        payload: dict
    ):
        event_data = {
            "event": event_type,
            "ticket_id": ticket_id,
            "agency_id": agency_id,
            "visibility": visibility,
            "data": payload,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        async with self._lock:
            subscribers_snapshot = list(self._subscribers)

        for sub in subscribers_snapshot:
            # Multi-tenant isolation:
            # Requesters must NEVER receive internal notes or other agencies' ticket events
            if sub.role == "Requester":
                if visibility == "internal" or (sub.agency_id and sub.agency_id != agency_id):
                    continue

            # Queue full protection: drop oldest if client is too slow
            if sub.queue.full():
                try:
                    sub.queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                sub.queue.put_nowait(event_data)
            except asyncio.QueueFull:
                pass


_global_broadcaster = EventBroadcaster()


def get_broadcaster() -> EventBroadcaster:
    """Returns the singleton EventBroadcaster instance."""
    return _global_broadcaster


def emit_outbox_event(
    db: Session,
    event_type: str,
    ticket_id: str,
    agency_id: str,
    visibility: str,
    payload: dict
) -> EventOutbox:
    """
    Atomically enqueues an event into the events_outbox table and
    broadcasts to live SSE subscribers.
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

    # Real-time event broadcasting
    get_broadcaster().broadcast_sync(
        event_type=event_type,
        ticket_id=ticket_id,
        agency_id=agency_id,
        visibility=visibility,
        payload=payload
    )

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

from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime as _DateTime, ForeignKey, Text, Integer, Index, TypeDecorator, Float, event
from sqlalchemy.orm import relationship
from backend.app.database import Base

def utcnow():
    return datetime.now(timezone.utc)

class UTCDateTime(TypeDecorator):
    """
    SQLAlchemy TypeDecorator that guarantees timezone-aware UTC datetime objects.
    - On write: converts to UTC, stores as UTC (naive for SQLite to avoid dialect comparison issues).
    - On read: converts from SQLite/PostgreSQL to timezone-aware UTC datetime (tzinfo=timezone.utc).
    """
    impl = _DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, str):
                value = datetime.fromisoformat(value)
            if value.tzinfo is not None:
                value = value.astimezone(timezone.utc)
                if dialect.name == "sqlite":
                    return value.replace(tzinfo=None)
                return value
            return value
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return value

DateTime = UTCDateTime

class Agency(Base):
    __tablename__ = "agencies"

    id = Column(String(50), primary_key=True)
    name = Column(String(200), nullable=False)
    country_code = Column(String(10), nullable=False)
    tier = Column(String(32), nullable=False, default="standard", server_default="standard")

    users = relationship("User", back_populates="agency")
    tickets = relationship("Ticket", back_populates="agency")


class User(Base):
    __tablename__ = "users"

    id = Column(String(50), primary_key=True)
    name = Column(String(200), nullable=False)
    email = Column(String(200), nullable=False, unique=True)
    role = Column(String(50), nullable=False)  # 'Requester', 'Agent', 'EscalationManager', 'Lead'
    region = Column(String(50), nullable=False)  # 'MEA', 'APAC', 'EUR'
    is_available = Column(Boolean, default=True)
    agency_id = Column(String(50), ForeignKey("agencies.id", ondelete="SET NULL"), nullable=True)
    hashed_password = Column(String(255), nullable=True)

    agency = relationship("Agency", back_populates="users")
    assigned_tickets = relationship("Ticket", back_populates="assignee", foreign_keys="Ticket.assigned_to")


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(String(50), primary_key=True)
    tboh_id = Column(String(100), nullable=False, index=True)
    agency_id = Column(String(50), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(300), nullable=False)
    description = Column(Text, nullable=False)
    intent = Column(String(100), nullable=False, default="Unclassified", index=True)
    priority = Column(String(50), nullable=False, default="Medium")  # 'Low', 'Medium', 'High', 'Urgent'
    status = Column(String(50), nullable=False, default="New", index=True)        # 'New', 'Open', 'Pending', 'Escalated', 'Resolved', 'Closed'
    check_in_date = Column(DateTime, nullable=False, index=True)
    lcd_date = Column(DateTime, nullable=True)
    effective_deadline_at = Column(DateTime, nullable=True, index=True)
    priority_weight = Column(Float, nullable=False, default=200.0, server_default="200.0")
    hotel_timezone = Column(String(64), nullable=False, default="UTC", server_default="UTC")
    assigned_to = Column(String(50), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    routing_reason = Column(Text, nullable=True)
    suggested_bug_link = Column(String(200), nullable=True)
    queue_score = Column(Float, nullable=False, default=0.0, server_default="0.0", index=True)
    score_computed_at = Column(DateTime, nullable=True)
    version = Column(Integer, default=1, nullable=False)  # Optimistic concurrency lock control
    created_at = Column(DateTime, default=utcnow, index=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_tickets_status_assigned", "status", "assigned_to"),
        Index("ix_tickets_assigned_status", "assigned_to", "status"),
        Index("ix_tickets_agency_status", "agency_id", "status"),
    )

    agency = relationship("Agency", back_populates="tickets")
    assignee = relationship("User", back_populates="assigned_tickets", foreign_keys=[assigned_to])
    messages = relationship("TicketMessage", back_populates="ticket", cascade="all, delete-orphan")
    themes = relationship("TicketTheme", back_populates="ticket", cascade="all, delete-orphan")
    side_conversations = relationship("SideConversation", back_populates="ticket", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="ticket", cascade="all, delete-orphan")
    outbox_events = relationship("EventOutbox", back_populates="ticket", cascade="all, delete-orphan")


@event.listens_for(Ticket, "init")
def receive_ticket_init(target, args, kwargs):
    """Ensures queue_score is never None upon model instantiation."""
    if kwargs.get("queue_score") is None:
        pw = kwargs.get("priority_weight", 200.0)
        target.queue_score = float(pw) if pw is not None else 0.0


@event.listens_for(Ticket, "before_insert")
def set_ticket_queue_score_before_insert(mapper, connection, target):
    """Guarantees queue_score is not None before inserting into SQL."""
    if target.queue_score is None:
        target.queue_score = float(target.priority_weight) if target.priority_weight is not None else 0.0


class EventOutbox(Base):
    __tablename__ = "events_outbox"

    id = Column(String(50), primary_key=True)
    event_type = Column(String(100), nullable=False, index=True)
    ticket_id = Column(String(50), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    agency_id = Column(String(50), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True)
    visibility = Column(String(20), nullable=False)  # 'public' or 'internal'
    payload_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow, index=True)
    delivered_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="pending", nullable=False, index=True)
    retry_count = Column(Integer, default=0, nullable=False)
    last_error = Column(Text, nullable=True)

    ticket = relationship("Ticket", back_populates="outbox_events")
    agency = relationship("Agency")


class TicketLink(Base):
    __tablename__ = "ticket_links"

    id = Column(String(50), primary_key=True)
    ticket_id = Column(String(50), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    linked_ticket_id = Column(String(50), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    link_reason = Column(String(200), nullable=False)


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id = Column(String(50), primary_key=True)
    ticket_id = Column(String(50), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id = Column(String(50), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    message_type = Column(String(50), nullable=False)  # 'PublicReply', 'InternalNote'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)

    ticket = relationship("Ticket", back_populates="messages")
    sender = relationship("User")


class SideConversation(Base):
    __tablename__ = "side_conversations"

    id = Column(String(50), primary_key=True)
    ticket_id = Column(String(50), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_name = Column(String(200), nullable=False)
    subject = Column(String(300), nullable=False)
    created_by = Column(String(50), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    ticket = relationship("Ticket", back_populates="side_conversations")
    creator = relationship("User")
    recipients = relationship("SideConversationRecipient", back_populates="side_conversation", cascade="all, delete-orphan")
    messages = relationship("SideConversationMessage", back_populates="side_conversation", cascade="all, delete-orphan")


class SideConversationRecipient(Base):
    __tablename__ = "side_conversation_recipients"

    id = Column(String(50), primary_key=True)
    side_conversation_id = Column(String(50), ForeignKey("side_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(200), nullable=False)

    side_conversation = relationship("SideConversation", back_populates="recipients")


class SideConversationMessage(Base):
    __tablename__ = "side_conversation_messages"

    id = Column(String(50), primary_key=True)
    side_conversation_id = Column(String(50), ForeignKey("side_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_email = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)

    side_conversation = relationship("SideConversation", back_populates="messages")


class TicketTheme(Base):
    __tablename__ = "ticket_themes"

    id = Column(String(50), primary_key=True)
    ticket_id = Column(String(50), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    theme = Column(String(100), nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow, index=True)

    ticket = relationship("Ticket", back_populates="themes")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(50), primary_key=True)
    ticket_id = Column(String(50), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = Column(String(50), nullable=False)
    action = Column(String(100), nullable=False)
    details = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)

    ticket = relationship("Ticket", back_populates="audit_logs")


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id = Column(String(128), primary_key=True)  # user_id:idempotency_key
    user_id = Column(String(50), nullable=False, index=True)
    key = Column(String(100), nullable=False, index=True)
    ticket_id = Column(String(50), nullable=False)
    request_hash = Column(String(64), nullable=True)  # SHA-256 hex digest of payload for conflict detection
    response_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow, index=True)

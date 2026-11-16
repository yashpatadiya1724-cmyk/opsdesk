from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from backend.app.database import Base

class Agency(Base):
    __tablename__ = "agencies"

    id = Column(String(50), primary_key=True)
    name = Column(String(200), nullable=False)
    country_code = Column(String(10), nullable=False)
    tier = Column(String(50), default="Standard")

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

    agency = relationship("Agency", back_populates="users")
    assigned_tickets = relationship("Ticket", back_populates="assignee", foreign_keys="Ticket.assigned_to")


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(String(50), primary_key=True)
    tboh_id = Column(String(100), nullable=False, index=True)
    agency_id = Column(String(50), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(300), nullable=False)
    description = Column(Text, nullable=False)
    intent = Column(String(100), nullable=False, default="Unclassified")
    priority = Column(String(50), nullable=False, default="Medium")  # 'Low', 'Medium', 'High', 'Urgent'
    status = Column(String(50), nullable=False, default="New")        # 'New', 'Open', 'Pending', 'Escalated', 'Resolved', 'Closed'
    check_in_date = Column(DateTime, nullable=False, index=True)
    lcd_date = Column(DateTime, nullable=True)
    assigned_to = Column(String(50), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    routing_reason = Column(Text, nullable=True)
    suggested_bug_link = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    agency = relationship("Agency", back_populates="tickets")
    assignee = relationship("User", back_populates="assigned_tickets", foreign_keys=[assigned_to])
    messages = relationship("TicketMessage", back_populates="ticket", cascade="all, delete-orphan")
    themes = relationship("TicketTheme", back_populates="ticket", cascade="all, delete-orphan")
    side_conversations = relationship("SideConversation", back_populates="ticket", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="ticket", cascade="all, delete-orphan")
    outbox_events = relationship("EventOutbox", back_populates="ticket", cascade="all, delete-orphan")


class EventOutbox(Base):
    __tablename__ = "events_outbox"

    id = Column(String(50), primary_key=True)
    event_type = Column(String(100), nullable=False, index=True)
    ticket_id = Column(String(50), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    agency_id = Column(String(50), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True)
    visibility = Column(String(20), nullable=False)  # 'public' or 'internal'
    payload_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    delivered_at = Column(DateTime, nullable=True)

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
    created_at = Column(DateTime, default=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="messages")
    sender = relationship("User")


class SideConversation(Base):
    __tablename__ = "side_conversations"

    id = Column(String(50), primary_key=True)
    ticket_id = Column(String(50), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_name = Column(String(200), nullable=False)
    subject = Column(String(300), nullable=False)
    created_by = Column(String(50), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)

    side_conversation = relationship("SideConversation", back_populates="messages")


class TicketTheme(Base):
    __tablename__ = "ticket_themes"

    id = Column(String(50), primary_key=True)
    ticket_id = Column(String(50), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    theme = Column(String(100), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    ticket = relationship("Ticket", back_populates="themes")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(50), primary_key=True)
    ticket_id = Column(String(50), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = Column(String(50), nullable=False)
    action = Column(String(100), nullable=False)
    details = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="audit_logs")

"""baseline schema

Revision ID: 0001_baseline_schema
Revises:
Create Date: 2026-11-19

"""
from typing import Sequence, Union
import sqlalchemy as sa

try:
    from alembic import op
except ImportError:
    op = None

# revision identifiers, used by Alembic.
revision: str = '0001_baseline_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. agencies
    op.create_table(
        'agencies',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('country_code', sa.String(length=10), nullable=False),
        sa.Column('tier', sa.String(length=32), server_default='standard', nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # 2. users
    op.create_table(
        'users',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('email', sa.String(length=200), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False),
        sa.Column('region', sa.String(length=50), nullable=False),
        sa.Column('is_available', sa.Boolean(), server_default=sa.text('1'), nullable=True),
        sa.Column('agency_id', sa.String(length=50), nullable=True),
        sa.Column('hashed_password', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['agency_id'], ['agencies.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )

    # 3. tickets
    op.create_table(
        'tickets',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('tboh_id', sa.String(length=100), nullable=False),
        sa.Column('agency_id', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('intent', sa.String(length=100), server_default='Unclassified', nullable=False),
        sa.Column('priority', sa.String(length=50), server_default='Medium', nullable=False),
        sa.Column('status', sa.String(length=50), server_default='New', nullable=False),
        sa.Column('check_in_date', sa.DateTime(), nullable=False),
        sa.Column('lcd_date', sa.DateTime(), nullable=True),
        sa.Column('effective_deadline_at', sa.DateTime(), nullable=True),
        sa.Column('queue_score', sa.Float(), nullable=True),
        sa.Column('hotel_timezone', sa.String(length=64), server_default='UTC', nullable=False),
        sa.Column('assigned_to', sa.String(length=50), nullable=True),
        sa.Column('routing_reason', sa.Text(), nullable=True),
        sa.Column('suggested_bug_link', sa.String(length=200), nullable=True),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['agency_id'], ['agencies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tickets_tboh_id', 'tickets', ['tboh_id'], unique=False)
    op.create_index('ix_tickets_agency_id', 'tickets', ['agency_id'], unique=False)
    op.create_index('ix_tickets_intent', 'tickets', ['intent'], unique=False)
    op.create_index('ix_tickets_status', 'tickets', ['status'], unique=False)
    op.create_index('ix_tickets_check_in_date', 'tickets', ['check_in_date'], unique=False)
    op.create_index('ix_tickets_effective_deadline_at', 'tickets', ['effective_deadline_at'], unique=False)
    op.create_index('ix_tickets_queue_score', 'tickets', ['queue_score'], unique=False)
    op.create_index('ix_tickets_assigned_to', 'tickets', ['assigned_to'], unique=False)
    op.create_index('ix_tickets_created_at', 'tickets', ['created_at'], unique=False)
    op.create_index('ix_tickets_status_assigned', 'tickets', ['status', 'assigned_to'], unique=False)
    op.create_index('ix_tickets_assigned_status', 'tickets', ['assigned_to', 'status'], unique=False)
    op.create_index('ix_tickets_agency_status', 'tickets', ['agency_id', 'status'], unique=False)

    # 4. events_outbox
    op.create_table(
        'events_outbox',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('ticket_id', sa.String(length=50), nullable=False),
        sa.Column('agency_id', sa.String(length=50), nullable=False),
        sa.Column('visibility', sa.String(length=20), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
        sa.Column('retry_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['agency_id'], ['agencies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_events_outbox_agency_id', 'events_outbox', ['agency_id'], unique=False)
    op.create_index('ix_events_outbox_created_at', 'events_outbox', ['created_at'], unique=False)
    op.create_index('ix_events_outbox_event_type', 'events_outbox', ['event_type'], unique=False)
    op.create_index('ix_events_outbox_status', 'events_outbox', ['status'], unique=False)
    op.create_index('ix_events_outbox_ticket_id', 'events_outbox', ['ticket_id'], unique=False)

    # 5. ticket_links
    op.create_table(
        'ticket_links',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('ticket_id', sa.String(length=50), nullable=False),
        sa.Column('linked_ticket_id', sa.String(length=50), nullable=False),
        sa.Column('link_reason', sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(['linked_ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ticket_links_linked_ticket_id', 'ticket_links', ['linked_ticket_id'], unique=False)
    op.create_index('ix_ticket_links_ticket_id', 'ticket_links', ['ticket_id'], unique=False)

    # 6. ticket_messages
    op.create_table(
        'ticket_messages',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('ticket_id', sa.String(length=50), nullable=False),
        sa.Column('sender_id', sa.String(length=50), nullable=True),
        sa.Column('message_type', sa.String(length=50), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['sender_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ticket_messages_ticket_id', 'ticket_messages', ['ticket_id'], unique=False)

    # 7. side_conversations
    op.create_table(
        'side_conversations',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('ticket_id', sa.String(length=50), nullable=False),
        sa.Column('supplier_name', sa.String(length=200), nullable=False),
        sa.Column('subject', sa.String(length=300), nullable=False),
        sa.Column('created_by', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_side_conversations_ticket_id', 'side_conversations', ['ticket_id'], unique=False)

    # 8. side_conversation_recipients
    op.create_table(
        'side_conversation_recipients',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('side_conversation_id', sa.String(length=50), nullable=False),
        sa.Column('email', sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(['side_conversation_id'], ['side_conversations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_side_conversation_recipients_side_conversation_id', 'side_conversation_recipients', ['side_conversation_id'], unique=False)

    # 9. side_conversation_messages
    op.create_table(
        'side_conversation_messages',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('side_conversation_id', sa.String(length=50), nullable=False),
        sa.Column('sender_email', sa.String(length=200), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['side_conversation_id'], ['side_conversations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_side_conversation_messages_side_conversation_id', 'side_conversation_messages', ['side_conversation_id'], unique=False)

    # 10. ticket_themes
    op.create_table(
        'ticket_themes',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('ticket_id', sa.String(length=50), nullable=False),
        sa.Column('theme', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ticket_themes_created_at', 'ticket_themes', ['created_at'], unique=False)
    op.create_index('ix_ticket_themes_theme', 'ticket_themes', ['theme'], unique=False)
    op.create_index('ix_ticket_themes_ticket_id', 'ticket_themes', ['ticket_id'], unique=False)

    # 11. audit_logs
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('ticket_id', sa.String(length=50), nullable=False),
        sa.Column('actor_id', sa.String(length=50), nullable=False),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('details', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_logs_ticket_id', 'audit_logs', ['ticket_id'], unique=False)

    # 12. idempotency_records
    op.create_table(
        'idempotency_records',
        sa.Column('id', sa.String(length=128), nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('ticket_id', sa.String(length=50), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=True),
        sa.Column('response_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_idempotency_records_created_at', 'idempotency_records', ['created_at'], unique=False)
    op.create_index('ix_idempotency_records_key', 'idempotency_records', ['key'], unique=False)
    op.create_index('ix_idempotency_records_user_id', 'idempotency_records', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_table('idempotency_records')
    op.drop_table('audit_logs')
    op.drop_table('ticket_themes')
    op.drop_table('side_conversation_messages')
    op.drop_table('side_conversation_recipients')
    op.drop_table('side_conversations')
    op.drop_table('ticket_messages')
    op.drop_table('ticket_links')
    op.drop_table('events_outbox')
    op.drop_table('tickets')
    op.drop_table('users')
    op.drop_table('agencies')

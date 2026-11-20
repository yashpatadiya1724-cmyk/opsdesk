"""tz aware priority weight

Revision ID: 0002_tz_aware_priority_weight
Revises: 0001_baseline_schema
Create Date: 2026-11-19

"""
from typing import Sequence, Union
import sqlalchemy as sa

try:
    from alembic import op
except ImportError:
    op = None

# revision identifiers, used by Alembic.
revision: str = '0002_tz_aware_priority_weight'
down_revision: Union[str, None] = '0001_baseline_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind and bind.dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))

    # 1. Add hashed_password to users
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(
            sa.Column('hashed_password', sa.String(length=255), nullable=True)
        )

    # 2. Add hardening columns to tickets
    with op.batch_alter_table('tickets') as batch_op:
        batch_op.add_column(
            sa.Column('effective_deadline_at', sa.DateTime(timezone=False), nullable=True)
        )
        batch_op.add_column(
            sa.Column('hotel_timezone', sa.String(length=64), server_default='UTC', nullable=False)
        )
        batch_op.add_column(
            sa.Column('priority_weight', sa.Float(), server_default='200.0', nullable=False)
        )
        batch_op.create_index('ix_tickets_effective_deadline_at', ['effective_deadline_at'], unique=False)

    # 3. Backfills
    # (a) Backfill priority_weight from priority using routing_config weights
    op.execute(
        sa.text(
            "UPDATE tickets SET priority_weight = CASE "
            "WHEN priority = 'Urgent' THEN 1000.0 "
            "WHEN priority = 'High' THEN 500.0 "
            "WHEN priority = 'Medium' THEN 200.0 "
            "WHEN priority = 'Low' THEN 50.0 "
            "ELSE 200.0 END"
        )
    )

    # (b) Backfill effective_deadline_at from check_in_date
    op.execute(
        sa.text("UPDATE tickets SET effective_deadline_at = check_in_date WHERE effective_deadline_at IS NULL")
    )

    # (c) Backfill hotel_timezone to UTC default
    op.execute(
        sa.text("UPDATE tickets SET hotel_timezone = 'UTC' WHERE hotel_timezone IS NULL")
    )

    # 4. For PostgreSQL, alter datetime columns to TIMESTAMP WITH TIME ZONE using postgresql_using
    bind = op.get_bind()
    if bind and bind.dialect.name == "postgresql":
        datetime_columns = [
            ('tickets', ['check_in_date', 'lcd_date', 'effective_deadline_at', 'created_at', 'updated_at']),
            ('events_outbox', ['created_at', 'delivered_at']),
            ('ticket_messages', ['created_at']),
            ('side_conversations', ['created_at']),
            ('side_conversation_messages', ['created_at']),
            ('ticket_themes', ['created_at']),
            ('audit_logs', ['created_at']),
            ('idempotency_records', ['created_at']),
        ]
        for table_name, cols in datetime_columns:
            for col in cols:
                op.alter_column(
                    table_name,
                    col,
                    type_=sa.DateTime(timezone=True),
                    existing_type=sa.DateTime(timezone=False),
                    existing_nullable=True if col != 'check_in_date' else False,
                    postgresql_using=f"{col} AT TIME ZONE 'UTC'"
                )


def downgrade() -> None:
    bind = op.get_bind()
    if bind and bind.dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))

    # 1. For PostgreSQL, revert datetime columns to TIMESTAMP WITHOUT TIME ZONE using postgresql_using
    if bind and bind.dialect.name == "postgresql":
        datetime_columns = [
            ('tickets', ['check_in_date', 'lcd_date', 'effective_deadline_at', 'created_at', 'updated_at']),
            ('events_outbox', ['created_at', 'delivered_at']),
            ('ticket_messages', ['created_at']),
            ('side_conversations', ['created_at']),
            ('side_conversation_messages', ['created_at']),
            ('ticket_themes', ['created_at']),
            ('audit_logs', ['created_at']),
            ('idempotency_records', ['created_at']),
        ]
        for table_name, cols in datetime_columns:
            for col in cols:
                op.alter_column(
                    table_name,
                    col,
                    type_=sa.DateTime(timezone=False),
                    existing_type=sa.DateTime(timezone=True),
                    existing_nullable=True if col != 'check_in_date' else False,
                    postgresql_using=f"{col} AT TIME ZONE 'UTC'"
                )

    # 2. Drop columns and index from tickets
    with op.batch_alter_table('tickets') as batch_op:
        batch_op.drop_index('ix_tickets_effective_deadline_at')
        batch_op.drop_column('priority_weight')
        batch_op.drop_column('hotel_timezone')
        batch_op.drop_column('effective_deadline_at')

    # 3. Drop hashed_password from users
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('hashed_password')

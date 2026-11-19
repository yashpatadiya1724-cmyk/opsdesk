"""timezone aware and queue score

Revision ID: 0002_timezone_aware_and_queue_score
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
revision: str = '0002_timezone_aware_and_queue_score'
down_revision: Union[str, None] = '0001_baseline_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add priority_weight column to tickets
    with op.batch_alter_table('tickets') as batch_op:
        batch_op.add_column(
            sa.Column('priority_weight', sa.Float(), server_default='200.0', nullable=False)
        )

    # 2. For PostgreSQL, alter datetime columns to TIMESTAMP WITH TIME ZONE
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
                    existing_nullable=True if col != 'check_in_date' else False
                )


def downgrade() -> None:
    # 1. For PostgreSQL, revert datetime columns to TIMESTAMP WITHOUT TIME ZONE
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
                    type_=sa.DateTime(timezone=False),
                    existing_type=sa.DateTime(timezone=True),
                    existing_nullable=True if col != 'check_in_date' else False
                )

    # 2. Drop priority_weight from tickets
    with op.batch_alter_table('tickets') as batch_op:
        batch_op.drop_column('priority_weight')

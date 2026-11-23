"""partial triage indexes and not null queue score

Revision ID: 0005_partial_triage_indexes
Revises: 0004_stored_queue_score_trigram
Create Date: 2026-11-22

"""
from typing import Sequence, Union
import sqlalchemy as sa

try:
    from alembic import op
except ImportError:
    op = None

# revision identifiers, used by Alembic.
revision: str = '0005_partial_triage_indexes'
down_revision: Union[str, None] = '0004_stored_queue_score_trigram'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind) if bind else None
    dialect_name = bind.dialect.name if bind else "sqlite"
    indexes = [idx['name'] for idx in insp.get_indexes('tickets')] if insp else []

    # 1. Backfill any existing NULL queue_score rows using priority_weight or fallback
    op.execute("""
        UPDATE tickets
        SET queue_score = COALESCE(priority_weight, 200.0)
        WHERE queue_score IS NULL;
    """)

    # 2. Make queue_score NOT NULL with server_default 0.0
    with op.batch_alter_table('tickets') as batch_op:
        batch_op.alter_column(
            'queue_score',
            existing_type=sa.Float(),
            nullable=False,
            server_default='0.0'
        )
        # Drop legacy composite index
        if 'ix_tickets_status_assigned_score' in indexes:
            batch_op.drop_index('ix_tickets_status_assigned_score')

    # 3. Create partial indexes for triage and my_queue
    if dialect_name == "postgresql":
        op.execute("""
            CREATE INDEX IF NOT EXISTS ix_tickets_triage
            ON tickets (queue_score DESC, effective_deadline_at ASC, id ASC)
            WHERE assigned_to IS NULL AND status IN ('New', 'Open', 'Pending', 'Escalated');
        """)
        op.execute("""
            CREATE INDEX IF NOT EXISTS ix_tickets_my_queue
            ON tickets (assigned_to, queue_score DESC, effective_deadline_at ASC, id ASC)
            WHERE status IN ('New', 'Open', 'Pending', 'Escalated');
        """)
    else:
        # SQLite partial indexes support
        try:
            op.execute("""
                CREATE INDEX IF NOT EXISTS ix_tickets_triage
                ON tickets (queue_score DESC, effective_deadline_at ASC, id ASC)
                WHERE assigned_to IS NULL AND status IN ('New', 'Open', 'Pending', 'Escalated');
            """)
            op.execute("""
                CREATE INDEX IF NOT EXISTS ix_tickets_my_queue
                ON tickets (assigned_to, queue_score DESC, effective_deadline_at ASC, id ASC)
                WHERE status IN ('New', 'Open', 'Pending', 'Escalated');
            """)
        except Exception:
            # Fallback for SQLite versions without partial index support
            with op.batch_alter_table('tickets') as batch_op:
                batch_op.create_index('ix_tickets_status_assigned_score', ['status', 'assigned_to', 'queue_score'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind) if bind else None
    dialect_name = bind.dialect.name if bind else "sqlite"
    indexes = [idx['name'] for idx in insp.get_indexes('tickets')] if insp else []

    # 1. Drop partial indexes
    if dialect_name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_tickets_my_queue;")
        op.execute("DROP INDEX IF EXISTS ix_tickets_triage;")
    else:
        try:
            op.execute("DROP INDEX IF EXISTS ix_tickets_my_queue;")
            op.execute("DROP INDEX IF EXISTS ix_tickets_triage;")
        except Exception:
            pass

    # 2. Re-create legacy index and make queue_score nullable
    with op.batch_alter_table('tickets') as batch_op:
        if 'ix_tickets_status_assigned_score' not in indexes:
            batch_op.create_index('ix_tickets_status_assigned_score', ['status', 'assigned_to', 'queue_score'], unique=False)
        batch_op.alter_column(
            'queue_score',
            existing_type=sa.Float(),
            nullable=True,
            server_default=None
        )

"""stored queue score and trigram

Revision ID: 0004_stored_queue_score_trigram
Revises: 0003_remove_stored_queue_score
Create Date: 2026-11-22

"""
from typing import Sequence, Union
import sqlalchemy as sa

try:
    from alembic import op
except ImportError:
    op = None

# revision identifiers, used by Alembic.
revision: str = '0004_stored_queue_score_trigram'
down_revision: Union[str, None] = '0003_remove_stored_queue_score'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind) if bind else None
    dialect_name = bind.dialect.name if bind else "sqlite"
    cols = [c['name'] for c in insp.get_columns('tickets')] if insp else []
    indexes = [idx['name'] for idx in insp.get_indexes('tickets')] if insp else []

    with op.batch_alter_table('tickets') as batch_op:
        if 'queue_score' not in cols:
            batch_op.add_column(sa.Column('queue_score', sa.Float(), nullable=True))
        if 'score_computed_at' not in cols:
            batch_op.add_column(sa.Column('score_computed_at', sa.DateTime(timezone=True), nullable=True))
        if 'ix_tickets_status_assigned_score' not in indexes:
            batch_op.create_index('ix_tickets_status_assigned_score', ['status', 'assigned_to', 'queue_score'], unique=False)
        if 'ix_tickets_queue_score' not in indexes:
            batch_op.create_index('ix_tickets_queue_score', ['queue_score'], unique=False)

    if dialect_name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_title_trgm ON tickets USING gin (title gin_trgm_ops);")
        op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_tboh_id_trgm ON tickets USING gin (tboh_id gin_trgm_ops);")


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else "sqlite"
    if dialect_name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_tickets_tboh_id_trgm;")
        op.execute("DROP INDEX IF EXISTS ix_tickets_title_trgm;")

    insp = sa.inspect(bind) if bind else None
    indexes = [idx['name'] for idx in insp.get_indexes('tickets')] if insp else []
    cols = [c['name'] for c in insp.get_columns('tickets')] if insp else []

    with op.batch_alter_table('tickets') as batch_op:
        if 'ix_tickets_status_assigned_score' in indexes:
            batch_op.drop_index('ix_tickets_status_assigned_score')
        if 'ix_tickets_queue_score' in indexes:
            batch_op.drop_index('ix_tickets_queue_score')
        if 'score_computed_at' in cols:
            batch_op.drop_column('score_computed_at')
        if 'queue_score' in cols:
            batch_op.drop_column('queue_score')

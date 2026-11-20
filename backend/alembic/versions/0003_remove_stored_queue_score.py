"""remove stored queue score

Revision ID: 0003_remove_stored_queue_score
Revises: 0002_tz_aware_priority_weight
Create Date: 2026-11-20

"""
from typing import Sequence, Union
import sqlalchemy as sa

try:
    from alembic import op
except ImportError:
    op = None

# revision identifiers, used by Alembic.
revision: str = '0003_remove_stored_queue_score'
down_revision: Union[str, None] = '0002_tz_aware_priority_weight'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Safely drop stored queue_score column if it exists in tickets table
    bind = op.get_bind()
    insp = sa.inspect(bind) if bind else None
    cols = [c['name'] for c in insp.get_columns('tickets')] if insp else []
    if 'queue_score' in cols:
        with op.batch_alter_table('tickets') as batch_op:
            indexes = [idx['name'] for idx in insp.get_indexes('tickets')] if insp else []
            if 'ix_tickets_queue_score' in indexes:
                batch_op.drop_index('ix_tickets_queue_score')
            batch_op.drop_column('queue_score')


def downgrade() -> None:
    with op.batch_alter_table('tickets') as batch_op:
        batch_op.add_column(
            sa.Column('queue_score', sa.Float(), nullable=True)
        )
        batch_op.create_index('ix_tickets_queue_score', ['queue_score'], unique=False)

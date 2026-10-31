"""user avatar

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18 01:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite DDL is not transactional: a run interrupted after the ALTER leaves the column but no version stamp.
    if 'avatar_name' in {c['name'] for c in sa.inspect(op.get_bind()).get_columns('users')}:
        return
    op.add_column('users', sa.Column('avatar_name', sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('avatar_name')

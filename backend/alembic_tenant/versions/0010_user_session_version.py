"""user session version (server-side session revocation)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-28 18:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite DDL is not transactional: tolerate a run interrupted after the ALTER.
    if 'session_version' in {c['name'] for c in sa.inspect(op.get_bind()).get_columns('users')}:
        return
    op.add_column('users', sa.Column('session_version', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('session_version')

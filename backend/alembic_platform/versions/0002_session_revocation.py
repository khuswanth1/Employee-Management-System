"""session revocation: per-user session version and a token denylist

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-28 18:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if 'session_version' not in {c['name'] for c in insp.get_columns('platform_users')}:
        op.add_column('platform_users', sa.Column('session_version', sa.Integer(), server_default='0', nullable=False))
    if 'revoked_tokens' not in insp.get_table_names():
        op.create_table('revoked_tokens',
        sa.Column('jti', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('jti', name=op.f('pk_revoked_tokens')),
        )
        op.create_index(op.f('ix_revoked_tokens_expires_at'), 'revoked_tokens', ['expires_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_revoked_tokens_expires_at'), table_name='revoked_tokens')
    op.drop_table('revoked_tokens')
    with op.batch_alter_table('platform_users', schema=None) as batch_op:
        batch_op.drop_column('session_version')

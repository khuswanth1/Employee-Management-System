"""two-step verification for platform administrators

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-28 21:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('platform_users')}
    if 'mfa_enabled' not in cols:
        op.add_column('platform_users', sa.Column('mfa_enabled', sa.Boolean(), server_default=sa.false(), nullable=False))
    if 'mfa_secret_enc' not in cols:
        op.add_column('platform_users', sa.Column('mfa_secret_enc', sa.String(length=255), nullable=True))
    if 'mfa_last_step' not in cols:
        op.add_column('platform_users', sa.Column('mfa_last_step', sa.Integer(), nullable=True))
    if 'mfa_recovery' not in cols:
        op.add_column('platform_users', sa.Column('mfa_recovery', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('platform_users', schema=None) as batch_op:
        for c in ('mfa_recovery', 'mfa_last_step', 'mfa_secret_enc', 'mfa_enabled'):
            batch_op.drop_column(c)

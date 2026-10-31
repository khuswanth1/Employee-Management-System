"""MFA columns, e-mail verification and single-use auth tokens

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-28 20:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite DDL is not transactional: tolerate a run interrupted part-way.
    insp = sa.inspect(op.get_bind())
    cols = {c['name'] for c in insp.get_columns('users')}
    if 'email_verified_at' not in cols:
        op.add_column('users', sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True))
    if 'mfa_enabled' not in cols:
        op.add_column('users', sa.Column('mfa_enabled', sa.Boolean(), server_default=sa.false(), nullable=False))
    if 'mfa_secret_enc' not in cols:
        op.add_column('users', sa.Column('mfa_secret_enc', sa.String(length=255), nullable=True))
    if 'mfa_last_step' not in cols:
        op.add_column('users', sa.Column('mfa_last_step', sa.Integer(), nullable=True))
    if 'mfa_recovery' not in cols:
        op.add_column('users', sa.Column('mfa_recovery', sa.JSON(), nullable=True))
    if 'auth_tokens' not in insp.get_table_names():
        op.create_table('auth_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('purpose', sa.String(length=20), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_auth_tokens_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_tokens')),
        sa.UniqueConstraint('token_hash', name=op.f('uq_auth_tokens_token_hash')),
        )
        op.create_index(op.f('ix_auth_tokens_user_id'), 'auth_tokens', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_auth_tokens_user_id'), table_name='auth_tokens')
    op.drop_table('auth_tokens')
    with op.batch_alter_table('users', schema=None) as batch_op:
        for c in ('mfa_recovery', 'mfa_last_step', 'mfa_secret_enc', 'mfa_enabled', 'email_verified_at'):
            batch_op.drop_column(c)

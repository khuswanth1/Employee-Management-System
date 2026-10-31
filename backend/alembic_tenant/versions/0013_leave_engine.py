"""leave engine: policy fields, ledger, delegations, half-day and revisions

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-28 23:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # SQLite DDL is not transactional: every step tolerates a run that was interrupted part-way.
    if 'accrual' not in _cols('leave_types'):
        with op.batch_alter_table('leave_types', schema=None) as b:
            b.add_column(sa.Column('accrual', sa.String(length=16), server_default='annual_upfront', nullable=False))
            b.add_column(sa.Column('carry_forward_max', sa.Float(), server_default='0', nullable=False))
            b.add_column(sa.Column('carry_expiry_months', sa.Integer(), nullable=True))
            b.add_column(sa.Column('allow_half_day', sa.Boolean(), server_default=sa.true(), nullable=False))
            b.add_column(sa.Column('count_all_days', sa.Boolean(), server_default=sa.false(), nullable=False))
            b.add_column(sa.Column('min_notice_days', sa.Integer(), server_default='0', nullable=False))
            b.add_column(sa.Column('max_consecutive_days', sa.Float(), nullable=True))
            b.add_column(sa.Column('encashable', sa.Boolean(), server_default=sa.false(), nullable=False))
            b.add_column(sa.Column('encash_max_days', sa.Float(), nullable=True))
            b.add_column(sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False))

    if 'carried_in' not in _cols('leave_balances'):
        with op.batch_alter_table('leave_balances', schema=None) as b:
            b.add_column(sa.Column('carried_in', sa.Float(), server_default='0', nullable=False))
            b.add_column(sa.Column('expired', sa.Float(), server_default='0', nullable=False))
            b.add_column(sa.Column('encashed', sa.Float(), server_default='0', nullable=False))

    if 'half_day' not in _cols('leave_requests'):
        with op.batch_alter_table('leave_requests', schema=None) as b:
            b.add_column(sa.Column('half_day', sa.String(length=8), nullable=True))
            b.add_column(sa.Column('supersedes_id', sa.Integer(), nullable=True))
            b.add_column(sa.Column('decided_via', sa.Integer(), nullable=True))
            b.create_foreign_key(b.f('fk_leave_requests_supersedes_id_leave_requests'), 'leave_requests', ['supersedes_id'], ['id'], ondelete='SET NULL')

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if 'leave_ledger' not in tables:
        op.create_table('leave_ledger',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('leave_type_id', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=12), nullable=False),
        sa.Column('days', sa.Float(), nullable=False),
        sa.Column('period', sa.String(length=24), nullable=True),
        sa.Column('request_id', sa.Integer(), nullable=True),
        sa.Column('note', sa.String(length=300), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_leave_ledger_created_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['leave_type_id'], ['leave_types.id'], name=op.f('fk_leave_ledger_leave_type_id_leave_types'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['request_id'], ['leave_requests.id'], name=op.f('fk_leave_ledger_request_id_leave_requests'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_leave_ledger_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_leave_ledger')),
        sa.UniqueConstraint('request_id', 'kind', name='uq_leave_ledger_request_kind'),
        sa.UniqueConstraint('user_id', 'leave_type_id', 'year', 'kind', 'period', name='uq_leave_ledger_period'),
        )
        op.create_index(op.f('ix_leave_ledger_user_id'), 'leave_ledger', ['user_id'], unique=False)
        op.create_index('ix_leave_ledger_balance', 'leave_ledger', ['user_id', 'leave_type_id', 'year'], unique=False)
        # Opening entries so that "remaining == sum(ledger)" holds for balances that existed before this migration.
        op.execute("INSERT INTO leave_ledger (user_id, leave_type_id, year, kind, days, period, note, created_at) "
                   "SELECT user_id, leave_type_id, year, 'grant', allocated, 'opening', 'Opening balance (migrated)', CURRENT_TIMESTAMP "
                   "FROM leave_balances WHERE allocated <> 0")
        op.execute("INSERT INTO leave_ledger (user_id, leave_type_id, year, kind, days, period, note, created_at) "
                   "SELECT user_id, leave_type_id, year, 'use', -used, 'opening', 'Leave taken before the ledger existed (migrated)', CURRENT_TIMESTAMP "
                   "FROM leave_balances WHERE used <> 0")

    if 'leave_delegations' not in tables:
        op.create_table('leave_delegations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('delegator_id', sa.Integer(), nullable=False),
        sa.Column('delegate_id', sa.Integer(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['delegate_id'], ['users.id'], name=op.f('fk_leave_delegations_delegate_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['delegator_id'], ['users.id'], name=op.f('fk_leave_delegations_delegator_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_leave_delegations')),
        )
        op.create_index(op.f('ix_leave_delegations_delegator_id'), 'leave_delegations', ['delegator_id'], unique=False)
        op.create_index(op.f('ix_leave_delegations_delegate_id'), 'leave_delegations', ['delegate_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_leave_delegations_delegate_id'), table_name='leave_delegations')
    op.drop_index(op.f('ix_leave_delegations_delegator_id'), table_name='leave_delegations')
    op.drop_table('leave_delegations')
    op.drop_index('ix_leave_ledger_balance', table_name='leave_ledger')
    op.drop_index(op.f('ix_leave_ledger_user_id'), table_name='leave_ledger')
    op.drop_table('leave_ledger')
    with op.batch_alter_table('leave_requests', schema=None) as b:
        b.drop_constraint(b.f('fk_leave_requests_supersedes_id_leave_requests'), type_='foreignkey')
        for c in ('decided_via', 'supersedes_id', 'half_day'):
            b.drop_column(c)
    with op.batch_alter_table('leave_balances', schema=None) as b:
        for c in ('encashed', 'expired', 'carried_in'):
            b.drop_column(c)
    with op.batch_alter_table('leave_types', schema=None) as b:
        for c in ('is_active', 'encash_max_days', 'encashable', 'max_consecutive_days', 'min_notice_days', 'count_all_days',
                  'allow_half_day', 'carry_expiry_months', 'carry_forward_max', 'accrual'):
            b.drop_column(c)

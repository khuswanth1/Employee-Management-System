"""payroll: components, versioned compensation, runs, payslips

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-29 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    have = set(sa.inspect(op.get_bind()).get_table_names())  # SQLite DDL is not transactional: tolerate an interrupted run
    if 'salary_components' not in have:
        op.create_table('salary_components',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=24), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('calc', sa.String(length=20), nullable=False),
        sa.Column('default_value', sa.BigInteger(), nullable=False),
        sa.Column('prorate', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('cap_minor', sa.BigInteger(), nullable=True),
        sa.Column('note', sa.String(length=300), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_salary_components')),
        sa.UniqueConstraint('code', name=op.f('uq_salary_components_code')),
        sa.UniqueConstraint('name', name=op.f('uq_salary_components_name')),
        )
    if 'compensations' not in have:
        op.create_table('compensations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('basic_minor', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('note', sa.String(length=300), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_compensations_created_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_compensations_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_compensations')),
        sa.UniqueConstraint('user_id', 'effective_from', name='uq_compensation_user_from'),
        )
        op.create_index(op.f('ix_compensations_user_id'), 'compensations', ['user_id'], unique=False)
    if 'compensation_lines' not in have:
        op.create_table('compensation_lines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('compensation_id', sa.Integer(), nullable=False),
        sa.Column('component_id', sa.Integer(), nullable=False),
        sa.Column('value', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['compensation_id'], ['compensations.id'], name=op.f('fk_compensation_lines_compensation_id_compensations'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['component_id'], ['salary_components.id'], name=op.f('fk_compensation_lines_component_id_salary_components'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_compensation_lines')),
        sa.UniqueConstraint('compensation_id', 'component_id', name='uq_compensation_line'),
        )
        op.create_index(op.f('ix_compensation_lines_compensation_id'), 'compensation_lines', ['compensation_id'], unique=False)
    if 'payroll_runs' not in have:
        op.create_table('payroll_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=12), server_default='draft', nullable=False),
        sa.Column('note', sa.String(length=300), nullable=True),
        sa.Column('settings', sa.JSON(), nullable=True),
        sa.Column('skipped', sa.JSON(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('processed_by', sa.Integer(), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', sa.Integer(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('payment_reference', sa.String(length=120), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id'], name=op.f('fk_payroll_runs_approved_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_payroll_runs_created_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['processed_by'], ['users.id'], name=op.f('fk_payroll_runs_processed_by_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_runs')),
        )
        op.create_index(op.f('ix_payroll_runs_status'), 'payroll_runs', ['status'], unique=False)
        op.create_index('ix_payroll_runs_period', 'payroll_runs', ['year', 'month'], unique=False)
    if 'payslips' not in have:
        op.create_table('payslips',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('compensation_id', sa.Integer(), nullable=True),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('employee_name', sa.String(length=200), nullable=False),
        sa.Column('employee_code', sa.String(length=20), nullable=True),
        sa.Column('designation', sa.String(length=120), nullable=True),
        sa.Column('basic_minor', sa.BigInteger(), nullable=False),
        sa.Column('gross_minor', sa.BigInteger(), nullable=False),
        sa.Column('deductions_minor', sa.BigInteger(), nullable=False),
        sa.Column('net_minor', sa.BigInteger(), nullable=False),
        sa.Column('facts', sa.JSON(), nullable=True),
        sa.Column('warnings', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['compensation_id'], ['compensations.id'], name=op.f('fk_payslips_compensation_id_compensations'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['run_id'], ['payroll_runs.id'], name=op.f('fk_payslips_run_id_payroll_runs'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_payslips_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payslips')),
        sa.UniqueConstraint('run_id', 'user_id', name='uq_payslip_run_user'),
        )
        op.create_index(op.f('ix_payslips_run_id'), 'payslips', ['run_id'], unique=False)
        op.create_index(op.f('ix_payslips_user_id'), 'payslips', ['user_id'], unique=False)
    if 'payslip_lines' not in have:
        op.create_table('payslip_lines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('payslip_id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=24), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('basis', sa.String(length=120), nullable=True),
        sa.Column('is_adjustment', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.ForeignKeyConstraint(['payslip_id'], ['payslips.id'], name=op.f('fk_payslip_lines_payslip_id_payslips'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payslip_lines')),
        )
        op.create_index(op.f('ix_payslip_lines_payslip_id'), 'payslip_lines', ['payslip_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_payslip_lines_payslip_id'), table_name='payslip_lines')
    op.drop_table('payslip_lines')
    op.drop_index(op.f('ix_payslips_user_id'), table_name='payslips')
    op.drop_index(op.f('ix_payslips_run_id'), table_name='payslips')
    op.drop_table('payslips')
    op.drop_index('ix_payroll_runs_period', table_name='payroll_runs')
    op.drop_index(op.f('ix_payroll_runs_status'), table_name='payroll_runs')
    op.drop_table('payroll_runs')
    op.drop_index(op.f('ix_compensation_lines_compensation_id'), table_name='compensation_lines')
    op.drop_table('compensation_lines')
    op.drop_index(op.f('ix_compensations_user_id'), table_name='compensations')
    op.drop_table('compensations')
    op.drop_table('salary_components')

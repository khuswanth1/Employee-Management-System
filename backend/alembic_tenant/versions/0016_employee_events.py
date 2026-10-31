"""employee lifecycle: append-only employment events

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-29 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if 'employee_events' in set(sa.inspect(op.get_bind()).get_table_names()):  # SQLite DDL is not transactional: tolerate an interrupted run
        return
    op.create_table('employee_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('effective_date', sa.Date(), nullable=False),
    sa.Column('from_value', sa.JSON(), nullable=True),
    sa.Column('to_value', sa.JSON(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_employee_events_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_employee_events_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_employee_events')),
    )
    op.create_index(op.f('ix_employee_events_user_id'), 'employee_events', ['user_id'], unique=False)
    op.create_index(op.f('ix_employee_events_kind'), 'employee_events', ['kind'], unique=False)
    # The history starts from what exists today: one "joined" row per person, dated with their hire date.
    op.execute("INSERT INTO employee_events (user_id, kind, effective_date, note, created_at) "
               "SELECT id, 'joined', COALESCE(hire_date, DATE(created_at)), 'Recorded when the history was introduced', CURRENT_TIMESTAMP FROM users")


def downgrade() -> None:
    op.drop_index(op.f('ix_employee_events_kind'), table_name='employee_events')
    op.drop_index(op.f('ix_employee_events_user_id'), table_name='employee_events')
    op.drop_table('employee_events')

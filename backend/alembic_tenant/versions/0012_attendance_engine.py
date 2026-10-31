"""attendance engine: shifts, frozen daily metrics, work mode, geo-fence, correction requests

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-28 22:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # SQLite DDL is not transactional: every step tolerates a run that was interrupted part-way.
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if 'shifts' not in tables:
        op.create_table('shifts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=True),
        sa.Column('end_time', sa.Time(), nullable=True),
        sa.Column('grace_minutes', sa.Integer(), server_default='0', nullable=False),
        sa.Column('required_hours', sa.Float(), server_default='8', nullable=False),
        sa.Column('half_day_hours', sa.Float(), nullable=True),
        sa.Column('overtime_after_hours', sa.Float(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_shifts')),
        sa.UniqueConstraint('name', name=op.f('uq_shifts_name')),
        )

    if 'shift_id' not in _cols('users'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.add_column(sa.Column('shift_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key(batch_op.f('fk_users_shift_id_shifts'), 'shifts', ['shift_id'], ['id'], ondelete='SET NULL')

    if 'geo_lat' not in _cols('branches'):
        with op.batch_alter_table('branches', schema=None) as batch_op:
            batch_op.add_column(sa.Column('geo_lat', sa.Float(), nullable=True))
            batch_op.add_column(sa.Column('geo_lng', sa.Float(), nullable=True))
            batch_op.add_column(sa.Column('geo_radius_m', sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column('geo_required', sa.Boolean(), server_default=sa.false(), nullable=False))

    if 'work_mode' not in _cols('attendance'):
        with op.batch_alter_table('attendance', schema=None) as batch_op:
            batch_op.add_column(sa.Column('work_mode', sa.String(length=10), server_default='office', nullable=False))
            batch_op.add_column(sa.Column('shift_id', sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column('check_in_lat', sa.Float(), nullable=True))
            batch_op.add_column(sa.Column('check_in_lng', sa.Float(), nullable=True))
            batch_op.add_column(sa.Column('source', sa.String(length=12), server_default='self', nullable=False))
            batch_op.add_column(sa.Column('auto_closed', sa.Boolean(), server_default=sa.false(), nullable=False))
            batch_op.add_column(sa.Column('status', sa.String(length=16), nullable=True))
            batch_op.add_column(sa.Column('day_type', sa.String(length=10), nullable=True))
            batch_op.add_column(sa.Column('worked_minutes', sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column('break_minutes', sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column('late_minutes', sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column('early_minutes', sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column('overtime_minutes', sa.Integer(), nullable=True))
            batch_op.create_foreign_key(batch_op.f('fk_attendance_shift_id_shifts'), 'shifts', ['shift_id'], ['id'], ondelete='SET NULL')

    if 'attendance_corrections' not in tables:
        op.create_table('attendance_corrections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('work_date', sa.Date(), nullable=False),
        sa.Column('requested_check_in', sa.DateTime(timezone=True), nullable=False),
        sa.Column('requested_check_out', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=10), server_default='pending', nullable=False),
        sa.Column('decided_by', sa.Integer(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decision_note', sa.Text(), nullable=True),
        sa.Column('attendance_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['attendance_id'], ['attendance.id'], name=op.f('fk_attendance_corrections_attendance_id_attendance'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['decided_by'], ['users.id'], name=op.f('fk_attendance_corrections_decided_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_attendance_corrections_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_attendance_corrections')),
        )
        op.create_index(op.f('ix_attendance_corrections_user_id'), 'attendance_corrections', ['user_id'], unique=False)
        op.create_index(op.f('ix_attendance_corrections_status'), 'attendance_corrections', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_attendance_corrections_status'), table_name='attendance_corrections')
    op.drop_index(op.f('ix_attendance_corrections_user_id'), table_name='attendance_corrections')
    op.drop_table('attendance_corrections')
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_attendance_shift_id_shifts'), type_='foreignkey')
        for c in ('overtime_minutes', 'early_minutes', 'late_minutes', 'break_minutes', 'worked_minutes', 'day_type', 'status',
                  'auto_closed', 'source', 'check_in_lng', 'check_in_lat', 'shift_id', 'work_mode'):
            batch_op.drop_column(c)
    with op.batch_alter_table('branches', schema=None) as batch_op:
        for c in ('geo_required', 'geo_radius_m', 'geo_lng', 'geo_lat'):
            batch_op.drop_column(c)
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_users_shift_id_shifts'), type_='foreignkey')
        batch_op.drop_column('shift_id')
    op.drop_table('shifts')

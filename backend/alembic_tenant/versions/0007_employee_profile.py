"""extended employee profile and document verification

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-26 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    # SQLite DDL is not transactional, so every step tolerates an interrupted earlier run.
    if 'employee_profiles' not in insp.get_table_names():
        op.create_table('employee_profiles',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('middle_name', sa.String(length=100), nullable=True),
        sa.Column('display_name', sa.String(length=100), nullable=True),
        sa.Column('employment_type', sa.String(length=20), nullable=True),
        sa.Column('employment_category', sa.String(length=60), nullable=True),
        sa.Column('job_level', sa.String(length=40), nullable=True),
        sa.Column('probation_end_date', sa.Date(), nullable=True),
        sa.Column('confirmation_date', sa.Date(), nullable=True),
        sa.Column('notice_period_days', sa.Integer(), nullable=True),
        sa.Column('last_working_date', sa.Date(), nullable=True),
        sa.Column('skills', sa.JSON(), nullable=True),
        sa.Column('certifications', sa.JSON(), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('personal_email', sa.String(length=255), nullable=True),
        sa.Column('date_of_birth', sa.Date(), nullable=True),
        sa.Column('gender', sa.String(length=30), nullable=True),
        sa.Column('address', sa.String(length=300), nullable=True),
        sa.Column('emergency_contact_name', sa.String(length=120), nullable=True),
        sa.Column('emergency_contact_relationship', sa.String(length=60), nullable=True),
        sa.Column('emergency_contact_phone', sa.String(length=40), nullable=True),
        sa.Column('emergency_contact_address', sa.String(length=300), nullable=True),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('user_id'),
        )
    have = {c['name'] for c in insp.get_columns('employee_documents')}
    with op.batch_alter_table('employee_documents', schema=None) as batch_op:
        if 'expiry_date' not in have:
            batch_op.add_column(sa.Column('expiry_date', sa.Date(), nullable=True))
        if 'verification_status' not in have:
            batch_op.add_column(sa.Column('verification_status', sa.String(length=12), nullable=False, server_default='pending'))
        if 'verified_by' not in have:
            batch_op.add_column(sa.Column('verified_by', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_employee_documents_verified_by', 'users', ['verified_by'], ['id'], ondelete='SET NULL')
        if 'verified_at' not in have:
            batch_op.add_column(sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('employee_documents', schema=None) as batch_op:
        batch_op.drop_constraint('fk_employee_documents_verified_by', type_='foreignkey')
        for c in ('verified_at', 'verified_by', 'verification_status', 'expiry_date'):
            batch_op.drop_column(c)
    op.drop_table('employee_profiles')

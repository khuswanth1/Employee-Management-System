"""department and branch detail fields

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-26 15:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None

DEPT = [
    ('code', sa.String(length=20)), ('head_id', sa.Integer()), ('parent_id', sa.Integer()), ('cost_center', sa.String(length=40)),
]
BRANCH = [
    ('state', sa.String(length=100)), ('postal_code', sa.String(length=20)), ('contact_email', sa.String(length=255)),
    ('contact_phone', sa.String(length=40)), ('timezone', sa.String(length=64)), ('working_days', sa.JSON()),
    ('manager_id', sa.Integer()), ('hr_representative_id', sa.Integer()),
]


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())  # SQLite DDL is not transactional: every step tolerates an interrupted run
    have = {c['name'] for c in insp.get_columns('departments')}
    with op.batch_alter_table('departments', schema=None) as b:
        for name, typ in DEPT:
            if name not in have:
                b.add_column(sa.Column(name, typ, nullable=True))
        if 'status' not in have:
            b.add_column(sa.Column('status', sa.String(length=10), nullable=False, server_default='active'))
        if 'code' not in have:
            b.create_unique_constraint('uq_departments_code', ['code'])
        if 'head_id' not in have:
            b.create_foreign_key('fk_departments_head', 'users', ['head_id'], ['id'], ondelete='SET NULL')
        if 'parent_id' not in have:
            b.create_foreign_key('fk_departments_parent', 'departments', ['parent_id'], ['id'], ondelete='SET NULL')
    have = {c['name'] for c in insp.get_columns('branches')}
    with op.batch_alter_table('branches', schema=None) as b:
        for name, typ in BRANCH:
            if name not in have:
                b.add_column(sa.Column(name, typ, nullable=True))
        if 'manager_id' not in have:
            b.create_foreign_key('fk_branches_manager', 'users', ['manager_id'], ['id'], ondelete='SET NULL')
        if 'hr_representative_id' not in have:
            b.create_foreign_key('fk_branches_hr_rep', 'users', ['hr_representative_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('branches', schema=None) as b:
        b.drop_constraint('fk_branches_hr_rep', type_='foreignkey')
        b.drop_constraint('fk_branches_manager', type_='foreignkey')
        for name, _ in reversed(BRANCH):
            b.drop_column(name)
    with op.batch_alter_table('departments', schema=None) as b:
        b.drop_constraint('fk_departments_parent', type_='foreignkey')
        b.drop_constraint('fk_departments_head', type_='foreignkey')
        b.drop_constraint('uq_departments_code', type_='unique')
        b.drop_column('status')
        for name, _ in reversed(DEPT):
            b.drop_column(name)

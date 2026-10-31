"""project and task detail fields

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-26 17:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None

PROJECT = [
    ('code', sa.String(length=20), None), ('category', sa.String(length=60), None), ('client_name', sa.String(length=120), None),
    ('risk_level', sa.String(length=10), 'low'), ('visibility', sa.String(length=12), 'restricted'),
    ('estimated_hours', sa.Float(), None), ('tags', sa.JSON(), None), ('completed_on', sa.Date(), None),
]
TASK = [
    ('task_type', sa.String(length=20), 'feature'), ('labels', sa.JSON(), None), ('start_date', sa.Date(), None),
    ('estimated_hours', sa.Float(), None), ('actual_hours', sa.Float(), None), ('review_notes', sa.Text(), None), ('completed_on', sa.Date(), None),
]


def _add(table, cols):
    have = {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}  # SQLite DDL is not transactional: tolerate a half-run
    with op.batch_alter_table(table, schema=None) as b:
        for name, typ, default in cols:
            if name not in have:
                if default is None:
                    b.add_column(sa.Column(name, typ, nullable=True))
                else:
                    b.add_column(sa.Column(name, typ, nullable=False, server_default=default))


def upgrade() -> None:
    _add('projects', PROJECT)
    _add('tasks', TASK)
    with op.batch_alter_table('projects', schema=None) as b:
        if 'uq_projects_code' not in {u['name'] for u in sa.inspect(op.get_bind()).get_unique_constraints('projects')}:
            b.create_unique_constraint('uq_projects_code', ['code'])
    # existing projects get a stable code; existing tasks in review/in progress keep their status
    bind = op.get_bind()
    for pid, in bind.execute(sa.text("select id from projects where code is null")).fetchall():
        bind.execute(sa.text("update projects set code = :c where id = :i"), {"c": f"PRJ-{pid:04d}", "i": pid})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("update tasks set status = 'in_progress' where status = 'changes_requested'"))
    with op.batch_alter_table('projects', schema=None) as b:
        b.drop_constraint('uq_projects_code', type_='unique')
        for name, _, _ in reversed(PROJECT):
            b.drop_column(name)
    with op.batch_alter_table('tasks', schema=None) as b:
        for name, _, _ in reversed(TASK):
            b.drop_column(name)

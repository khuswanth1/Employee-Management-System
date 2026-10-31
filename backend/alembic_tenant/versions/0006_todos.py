"""personal to-do tasks with subtasks

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-21 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if 'todos' in sa.inspect(op.get_bind()).get_table_names():  # interrupted earlier run (SQLite DDL is not transactional)
        return
    op.create_table('todos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('parent_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('priority', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('duration_minutes', sa.Integer(), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['parent_id'], ['todos.id'], name=op.f('fk_todos_parent_id_todos'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_todos_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_todos'))
    )
    with op.batch_alter_table('todos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_todos_parent_id'), ['parent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_todos_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('todos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_todos_user_id'))
        batch_op.drop_index(batch_op.f('ix_todos_parent_id'))
    op.drop_table('todos')

"""task comments

Revision ID: 0018
Revises: 0017
"""
import sqlalchemy as sa
from alembic import op

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if 'task_comments' not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table('task_comments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_task_comments_author_id_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], name=op.f('fk_task_comments_task_id_tasks'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_task_comments')),
        )
        op.create_index(op.f('ix_task_comments_task_id'), 'task_comments', ['task_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_task_comments_task_id'), table_name='task_comments')
    op.drop_table('task_comments')

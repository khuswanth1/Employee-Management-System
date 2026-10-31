"""performance management: rating scales, cycles, goals, reviews, feedback

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-29 14:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    have = set(sa.inspect(op.get_bind()).get_table_names())  # SQLite DDL is not transactional: tolerate an interrupted run
    if 'rating_scales' not in have:
        op.create_table('rating_scales',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_rating_scales')),
        sa.UniqueConstraint('name', name=op.f('uq_rating_scales_name')),
        )
    if 'rating_levels' not in have:
        op.create_table('rating_levels',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scale_id', sa.Integer(), nullable=False),
        sa.Column('value', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=60), nullable=False),
        sa.Column('description', sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(['scale_id'], ['rating_scales.id'], name=op.f('fk_rating_levels_scale_id_rating_scales'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_rating_levels')),
        sa.UniqueConstraint('scale_id', 'value', name='uq_rating_level'),
        )
        op.create_index(op.f('ix_rating_levels_scale_id'), 'rating_levels', ['scale_id'], unique=False)
    if 'performance_cycles' not in have:
        op.create_table('performance_cycles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('self_review_due', sa.Date(), nullable=True),
        sa.Column('manager_review_due', sa.Date(), nullable=True),
        sa.Column('scale_id', sa.Integer(), nullable=False),
        sa.Column('competencies', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=10), server_default='draft', nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_performance_cycles_created_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['scale_id'], ['rating_scales.id'], name=op.f('fk_performance_cycles_scale_id_rating_scales')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_performance_cycles')),
        sa.UniqueConstraint('name', name=op.f('uq_performance_cycles_name')),
        )
        op.create_index(op.f('ix_performance_cycles_status'), 'performance_cycles', ['status'], unique=False)
    if 'goals' not in have:
        op.create_table('goals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cycle_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('kind', sa.String(length=6), server_default='goal', nullable=False),
        sa.Column('weight', sa.Integer(), server_default='0', nullable=False),
        sa.Column('unit', sa.String(length=30), nullable=True),
        sa.Column('target_value', sa.Float(), nullable=True),
        sa.Column('current_value', sa.Float(), nullable=True),
        sa.Column('progress', sa.Integer(), server_default='0', nullable=False),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=10), server_default='proposed', nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('agreed_by', sa.Integer(), nullable=True),
        sa.Column('agreed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['agreed_by'], ['users.id'], name=op.f('fk_goals_agreed_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_goals_created_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['cycle_id'], ['performance_cycles.id'], name=op.f('fk_goals_cycle_id_performance_cycles'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_goals_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_goals')),
        )
        op.create_index(op.f('ix_goals_cycle_id'), 'goals', ['cycle_id'], unique=False)
        op.create_index(op.f('ix_goals_user_id'), 'goals', ['user_id'], unique=False)
    if 'goal_updates' not in have:
        op.create_table('goal_updates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('goal_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=True),
        sa.Column('progress', sa.Integer(), nullable=True),
        sa.Column('current_value', sa.Float(), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_goal_updates_author_id_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['goal_id'], ['goals.id'], name=op.f('fk_goal_updates_goal_id_goals'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_goal_updates')),
        )
        op.create_index(op.f('ix_goal_updates_goal_id'), 'goal_updates', ['goal_id'], unique=False)
    if 'performance_reviews' not in have:
        op.create_table('performance_reviews',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cycle_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('reviewer_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=16), server_default='pending_self', nullable=False),
        sa.Column('self_rating', sa.Integer(), nullable=True),
        sa.Column('self_comments', sa.Text(), nullable=True),
        sa.Column('self_submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('manager_rating', sa.Integer(), nullable=True),
        sa.Column('manager_comments', sa.Text(), nullable=True),
        sa.Column('strengths', sa.Text(), nullable=True),
        sa.Column('development_areas', sa.Text(), nullable=True),
        sa.Column('manager_submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('manager_submitted_by', sa.Integer(), nullable=True),
        sa.Column('ratings', sa.JSON(), nullable=True),
        sa.Column('goal_score', sa.Float(), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('employee_response', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['cycle_id'], ['performance_cycles.id'], name=op.f('fk_performance_reviews_cycle_id_performance_cycles'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['manager_submitted_by'], ['users.id'], name=op.f('fk_performance_reviews_manager_submitted_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reviewer_id'], ['users.id'], name=op.f('fk_performance_reviews_reviewer_id_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_performance_reviews_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_performance_reviews')),
        sa.UniqueConstraint('cycle_id', 'user_id', name='uq_review_cycle_user'),
        )
        op.create_index(op.f('ix_performance_reviews_cycle_id'), 'performance_reviews', ['cycle_id'], unique=False)
        op.create_index(op.f('ix_performance_reviews_user_id'), 'performance_reviews', ['user_id'], unique=False)
        op.create_index(op.f('ix_performance_reviews_status'), 'performance_reviews', ['status'], unique=False)
    if 'feedback' not in have:
        op.create_table('feedback',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('from_user_id', sa.Integer(), nullable=False),
        sa.Column('to_user_id', sa.Integer(), nullable=False),
        sa.Column('cycle_id', sa.Integer(), nullable=True),
        sa.Column('kind', sa.String(length=12), server_default='praise', nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('shared', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['cycle_id'], ['performance_cycles.id'], name=op.f('fk_feedback_cycle_id_performance_cycles'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['from_user_id'], ['users.id'], name=op.f('fk_feedback_from_user_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['to_user_id'], ['users.id'], name=op.f('fk_feedback_to_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_feedback')),
        )
        op.create_index(op.f('ix_feedback_from_user_id'), 'feedback', ['from_user_id'], unique=False)
        op.create_index(op.f('ix_feedback_to_user_id'), 'feedback', ['to_user_id'], unique=False)


def downgrade() -> None:
    for ix, t in (('ix_feedback_to_user_id', 'feedback'), ('ix_feedback_from_user_id', 'feedback')):
        op.drop_index(op.f(ix), table_name=t)
    op.drop_table('feedback')
    for ix in ('ix_performance_reviews_status', 'ix_performance_reviews_user_id', 'ix_performance_reviews_cycle_id'):
        op.drop_index(op.f(ix), table_name='performance_reviews')
    op.drop_table('performance_reviews')
    op.drop_index(op.f('ix_goal_updates_goal_id'), table_name='goal_updates')
    op.drop_table('goal_updates')
    op.drop_index(op.f('ix_goals_user_id'), table_name='goals')
    op.drop_index(op.f('ix_goals_cycle_id'), table_name='goals')
    op.drop_table('goals')
    op.drop_index(op.f('ix_performance_cycles_status'), table_name='performance_cycles')
    op.drop_table('performance_cycles')
    op.drop_index(op.f('ix_rating_levels_scale_id'), table_name='rating_levels')
    op.drop_table('rating_levels')
    op.drop_table('rating_scales')

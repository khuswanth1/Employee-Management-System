"""meetings are private to the host and the people invited

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-29 21:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if 'kind' not in {c['name'] for c in insp.get_columns('meetings')}:
        op.add_column('meetings', sa.Column('kind', sa.String(length=10), server_default='meeting', nullable=False))
    if 'meeting_participants' not in insp.get_table_names():
        op.create_table('meeting_participants',
        sa.Column('meeting_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('invited_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['invited_by'], ['users.id'], name=op.f('fk_meeting_participants_invited_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['meeting_id'], ['meetings.id'], name=op.f('fk_meeting_participants_meeting_id_meetings'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_meeting_participants_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('meeting_id', 'user_id', name=op.f('pk_meeting_participants')),
        )
        op.create_index(op.f('ix_meeting_participants_user_id'), 'meeting_participants', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_meeting_participants_user_id'), table_name='meeting_participants')
    op.drop_table('meeting_participants')
    with op.batch_alter_table('meetings', schema=None) as b:
        b.drop_column('kind')

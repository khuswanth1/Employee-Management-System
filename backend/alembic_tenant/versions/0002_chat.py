"""chat: conversations, members, messages

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('conversations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=True),
    sa.Column('dm_key', sa.String(length=40), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_conversations_created_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conversations')),
    sa.UniqueConstraint('dm_key', name=op.f('uq_conversations_dm_key'))
    )
    op.create_table('conversation_members',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('conversation_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('last_read_message_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_conversation_members_conversation_id_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_conversation_members_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conversation_members')),
    sa.UniqueConstraint('conversation_id', 'user_id', name=op.f('uq_conversation_members_conversation_id'))
    )
    with op.batch_alter_table('conversation_members', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_conversation_members_user_id'), ['user_id'], unique=False)

    op.create_table('messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('conversation_id', sa.Integer(), nullable=False),
    sa.Column('sender_id', sa.Integer(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_messages_conversation_id_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['sender_id'], ['users.id'], name=op.f('fk_messages_sender_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messages'))
    )
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.create_index('ix_messages_conversation_id_id', ['conversation_id', 'id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_index('ix_messages_conversation_id_id')
    op.drop_table('messages')
    with op.batch_alter_table('conversation_members', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_conversation_members_user_id'))
    op.drop_table('conversation_members')
    op.drop_table('conversations')

"""chat replies, edit/delete, pins, delivered marks, last seen, and call outcomes

Revision ID: 0020
Revises: 0019
"""
import sqlalchemy as sa
from alembic import op

revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def _missing(table, names):
    have = {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}
    return [n for n in names if n not in have]


def upgrade() -> None:
    new = _missing('messages', ['reply_to_id', 'edited_at', 'deleted_at'])
    if new:
        with op.batch_alter_table('messages', schema=None) as b:
            if 'reply_to_id' in new:
                b.add_column(sa.Column('reply_to_id', sa.Integer(), nullable=True))
                b.create_foreign_key(op.f('fk_messages_reply_to_id_messages'), 'messages', ['reply_to_id'], ['id'], ondelete='SET NULL')
            if 'edited_at' in new:
                b.add_column(sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True))
            if 'deleted_at' in new:
                b.add_column(sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    new = _missing('conversation_members', ['last_delivered_message_id', 'pinned'])
    if new:
        with op.batch_alter_table('conversation_members', schema=None) as b:
            if 'last_delivered_message_id' in new:
                b.add_column(sa.Column('last_delivered_message_id', sa.Integer(), server_default='0', nullable=False))
            if 'pinned' in new:
                b.add_column(sa.Column('pinned', sa.Boolean(), server_default=sa.false(), nullable=False))
    if _missing('users', ['last_seen_at']):
        with op.batch_alter_table('users', schema=None) as b:
            b.add_column(sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
    new = _missing('meetings', ['call_video', 'answered_at', 'ended_at', 'outcome'])
    if new:
        with op.batch_alter_table('meetings', schema=None) as b:
            if 'call_video' in new:
                b.add_column(sa.Column('call_video', sa.Boolean(), server_default=sa.true(), nullable=False))
            if 'answered_at' in new:
                b.add_column(sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True))
            if 'ended_at' in new:
                b.add_column(sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True))
            if 'outcome' in new:
                b.add_column(sa.Column('outcome', sa.String(length=12), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('meetings', schema=None) as b:
        for n in ('outcome', 'ended_at', 'answered_at', 'call_video'):
            b.drop_column(n)
    with op.batch_alter_table('users', schema=None) as b:
        b.drop_column('last_seen_at')
    with op.batch_alter_table('conversation_members', schema=None) as b:
        b.drop_column('pinned')
        b.drop_column('last_delivered_message_id')
    with op.batch_alter_table('messages', schema=None) as b:
        b.drop_constraint(op.f('fk_messages_reply_to_id_messages'), type_='foreignkey')
        for n in ('deleted_at', 'edited_at', 'reply_to_id'):
            b.drop_column(n)

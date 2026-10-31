"""chat attachments, voice messages, stickers and reactions

Revision ID: 0019
Revises: 0018
"""
import sqlalchemy as sa
from alembic import op

revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    have = {c['name'] for c in insp.get_columns('messages')}
    with op.batch_alter_table('messages', schema=None) as b:
        if 'kind' not in have:
            b.add_column(sa.Column('kind', sa.String(length=10), server_default='text', nullable=False))
        for name, col in (('file_name', sa.String(length=255)), ('stored_name', sa.String(length=64)), ('file_size', sa.Integer()),
                          ('mime', sa.String(length=60)), ('duration_s', sa.Integer())):
            if name not in have:
                b.add_column(sa.Column(name, col, nullable=True))
    if 'message_reactions' not in insp.get_table_names():
        op.create_table('message_reactions',
        sa.Column('message_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('emoji', sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_message_reactions_message_id_messages'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_message_reactions_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('message_id', 'user_id', 'emoji', name=op.f('pk_message_reactions')),
        )


def downgrade() -> None:
    op.drop_table('message_reactions')
    with op.batch_alter_table('messages', schema=None) as b:
        for name in ('duration_s', 'mime', 'file_size', 'stored_name', 'file_name', 'kind'):
            b.drop_column(name)

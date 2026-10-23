"""Extend the existing chat store; keep every legacy ID and planning reference."""
from uuid import uuid4
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = '0003_conversations'
down_revision = '0002_task_hierarchy'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = lambda name: {c['name']: c for c in sa.inspect(bind).get_columns(name)}
    if 'owner_id' not in columns('workspace_metadata'):
        op.add_column('workspace_metadata', sa.Column('owner_id', sa.String(36), nullable=False, server_default='local'))
    identity = bind.execute(sa.text('SELECT owner_id FROM workspace_metadata WHERE id=1')).scalar()
    if not identity:
        identity = str(uuid4())
        bind.execute(sa.text('INSERT INTO workspace_metadata(id,workspace_id,owner_id,created_at) VALUES(1,:workspace,:owner,:now)'),
                     dict(workspace=str(uuid4()), owner=identity, now=datetime.now(timezone.utc).replace(tzinfo=None)))
    elif identity == 'local':
        identity = str(uuid4())
        bind.execute(sa.text('UPDATE workspace_metadata SET owner_id=:owner WHERE id=1'), dict(owner=identity))
    existing = columns('assistant_sessions')
    additions = [
        sa.Column('owner_id', sa.String(36), nullable=False, server_default='local'),
        sa.Column('title', sa.String(160), nullable=False, server_default='新对话'),
        sa.Column('title_source', sa.String(20), nullable=False, server_default='default'),
        sa.Column('client_request_id', sa.String(100), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        *[sa.Column(name, sa.DateTime(), nullable=True) for name in
          ('updated_at', 'last_activity_at', 'pinned_at', 'archived_at', 'deleted_at')],
    ]
    with op.batch_alter_table('assistant_sessions') as batch:
        if not existing['week_start']['nullable']:
            batch.alter_column('week_start', existing_type=sa.Date(), nullable=True)
        for column in additions:
            if column.name not in existing:
                batch.add_column(column)
    bind.execute(sa.text("UPDATE assistant_sessions SET owner_id=:owner WHERE owner_id='local'"), dict(owner=identity))
    if 'title' not in existing:
        bind.execute(sa.text("UPDATE assistant_sessions SET title=CASE scope WHEN 'planning' THEN '历史规划会话' WHEN 'review' THEN '历史复盘会话' WHEN 'profile' THEN '历史档案会话' ELSE '历史工具会话' END, title_source='legacy'"))
    message_columns = columns('assistant_messages')
    if 'owner_id' not in message_columns:
        op.add_column('assistant_messages', sa.Column('owner_id', sa.String(36), nullable=False, server_default='local'))
    if 'created_at' not in message_columns:
        op.add_column('assistant_messages', sa.Column('created_at', sa.DateTime(), nullable=True))
    bind.execute(sa.text('UPDATE assistant_messages SET owner_id=(SELECT owner_id FROM assistant_sessions WHERE id=assistant_messages.session_id)'))
    for table, name, keys, unique in [
        ('assistant_sessions','conversation_create_once',['owner_id','client_request_id'],True),
        ('assistant_sessions','conversation_owner_activity',['owner_id','deleted_at','archived_at','last_activity_at','id'],False),
        ('assistant_messages','conversation_message_page',['owner_id','session_id','id'],False),
    ]:
        if name not in {i['name'] for i in sa.inspect(bind).get_indexes(table)}:
            op.create_index(name, table, keys, unique=unique)


def downgrade():
    raise RuntimeError('Destructive downgrade disabled; restore the pre-migration SQLite backup.')

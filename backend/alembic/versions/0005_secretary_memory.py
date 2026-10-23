"""Explicit long-term memory. Summaries reuse messages/runs, no text copy table."""
from alembic import op
import sqlalchemy as sa

revision='0005_secretary_memory'
down_revision='0004_review_records'
branch_labels=depends_on=None


def upgrade():
    columns=[sa.Column('id',sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column('owner_id',sa.String(36),nullable=False),sa.Column('client_request_id',sa.String(100),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False),sa.Column('text',sa.Text(),nullable=False),
        sa.Column('scope',sa.String(20),nullable=False),sa.Column('status',sa.String(20),nullable=False),
        sa.Column('sources',sa.JSON(),nullable=False),sa.Column('receipt',sa.JSON(),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('updated_at',sa.DateTime(),nullable=False)]
    inspector=sa.inspect(op.get_bind())
    if 'memory_entries' in inspector.get_table_names():
        existing={c['name']:c for c in inspector.get_columns('memory_entries')}
        if set(existing)!={c.name for c in columns} or any(c.type._type_affinity is not existing[c.name]['type']._type_affinity or c.nullable!=existing[c.name]['nullable'] for c in columns):
            raise RuntimeError('Unrecognized memory_entries schema')
        indexes={i['name']:i for i in inspector.get_indexes('memory_entries')}
        if not indexes.get('memory_once',{}).get('unique') or indexes['memory_once']['column_names']!=['owner_id','client_request_id'] or indexes.get('memory_active',{}).get('column_names')!=['owner_id','status','updated_at','id']:
            raise RuntimeError('Unrecognized memory_entries indexes')
        return
    op.create_table('memory_entries',*columns)
    op.create_index('memory_once','memory_entries',['owner_id','client_request_id'],unique=True)
    op.create_index('memory_active','memory_entries',['owner_id','status','updated_at','id'])


def downgrade():
    raise RuntimeError('Destructive downgrade disabled; use a separately verified backup.')

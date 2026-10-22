"""Explicit user review records. Existing facts and frozen migrations unchanged."""
from alembic import op
import sqlalchemy as sa

revision = '0004_review_records'
down_revision = '0003_conversations'
branch_labels = depends_on = None


def upgrade():
    existing=sa.inspect(op.get_bind())
    if 'review_records' in existing.get_table_names():
        expected={'id','owner_id','client_request_id','version','period','start_date','end_date','title','summary','conclusion','next_steps','facts','sources','history','created_at','updated_at'}
        if {c['name'] for c in existing.get_columns('review_records')}!=expected:
            raise RuntimeError('Unrecognized review_records schema')
        columns={c['name']:c for c in existing.get_columns('review_records')}
        if not isinstance(columns['id']['type'],sa.Integer) or any(columns[key]['nullable'] for key in expected-{'id'}):
            raise RuntimeError('Unrecognized review_records types or nullability')
        families={**dict.fromkeys(['owner_id','client_request_id','period','title'],sa.String),
            **dict.fromkeys(['summary','conclusion','next_steps'],sa.String),
            **dict.fromkeys(['facts','sources','history'],sa.JSON),
            **dict.fromkeys(['id','version'],sa.Integer),**dict.fromkeys(['start_date','end_date'],sa.Date),
            **dict.fromkeys(['created_at','updated_at'],sa.DateTime)}
        if any(columns[key]['type']._type_affinity is not family()._type_affinity for key,family in families.items()):
            raise RuntimeError('Unrecognized review_records column type')
        indexes=existing.get_indexes('review_records')
        if not any(i['unique'] and i['column_names']==['owner_id','client_request_id'] for i in indexes):
            raise RuntimeError('Unrecognized review_records uniqueness')
        return
    op.create_table('review_records',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('owner_id', sa.String(36), nullable=False),
        sa.Column('client_request_id', sa.String(100), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('period', sa.String(10), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False), sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('title', sa.String(160), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False), sa.Column('conclusion', sa.Text(), nullable=False),
        sa.Column('next_steps', sa.Text(), nullable=False),
        sa.Column('facts', sa.JSON(), nullable=False), sa.Column('sources', sa.JSON(), nullable=False),
        sa.Column('history', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False))
    op.create_index('review_record_once', 'review_records', ['owner_id', 'client_request_id'], unique=True)


def downgrade():
    raise RuntimeError('Destructive downgrade disabled; restore a separately verified backup.')

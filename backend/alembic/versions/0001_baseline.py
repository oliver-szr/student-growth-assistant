"""Frozen public MVP baseline; upgrades only recognized additive legacy schemas."""
import importlib.util
import sys
from pathlib import Path
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.orm import Session

revision = '0001_baseline'
down_revision = None
branch_labels = depends_on = None

def upgrade():
    baseline=sys.modules.get('sga_frozen_baseline')
    if baseline is None:
        spec=importlib.util.spec_from_file_location('sga_frozen_baseline', Path(__file__).parents[1]/'baseline_models.py')
        baseline=importlib.util.module_from_spec(spec); spec.loader.exec_module(baseline)
        sys.modules['sga_frozen_baseline']=baseline
    connection=op.get_bind()
    existing=set(inspect(connection).get_table_names())-{'alembic_version'}
    known_additions={
        'assistant_sessions':{'scope'}, 'assistant_messages':{'content'},
        'task_feedback':{'title_snapshot','deadline_snapshot','priority_snapshot','occurred_at','category_name_snapshot'},
        'task_work_sessions':{'family_snapshot','family_confirmed_snapshot','category_name_snapshot'},
    }
    for name in existing:
        if name not in baseline.Base.metadata.tables: continue
        expected=baseline.Base.metadata.tables[name]
        pk=inspect(connection).get_pk_constraint(name)['constrained_columns']
        if set(pk)!=set(expected.primary_key.columns.keys()):raise RuntimeError(f'Incompatible primary key: {name}')
        actual_fks={(tuple(f['constrained_columns']),f['referred_table'],tuple(f['referred_columns'])) for f in inspect(connection).get_foreign_keys(name)}
        required_fks={(tuple(f.parent.name for f in constraint.elements),constraint.referred_table.name,tuple(f.column.name for f in constraint.elements)) for constraint in expected.foreign_key_constraints}
        if not required_fks<=actual_fks:raise RuntimeError(f'Incompatible foreign keys: {name}')
        actual={column['name']:column for column in inspect(connection).get_columns(name)}
        missing=set(expected.columns.keys())-set(actual)-known_additions.get(name,set())
        if missing: raise RuntimeError(f'Unrecognized legacy schema {name}: missing {sorted(missing)}; restore backup or repair explicitly.')
        for column in expected.columns:
            if column.name in actual and column.type._type_affinity is not actual[column.name]['type']._type_affinity:
                raise RuntimeError(f'Incompatible type: {name}.{column.name}')
    baseline.Base.metadata.create_all(connection)
    for table in baseline.Base.metadata.tables.values():
        if table.name not in existing:continue
        for index in table.indexes:index.create(connection,checkfirst=True)
    from app.services.growth_migrations import _upgrade_feedback_snapshots, _upgrade_workspace_columns, _upgrade_taxonomy_snapshots
    with Session(bind=connection) as db:
        if existing:
            _upgrade_feedback_snapshots(db); _upgrade_workspace_columns(db); _upgrade_taxonomy_snapshots(db)
        else:
            from app.models import GrowthMigration, utc_now
            for name in ('growth_v2_feedback_snapshots','growth_v3_workspace_columns','growth_v4_category_snapshots'):
                db.add(GrowthMigration(name=name,applied_at=utc_now()))
        db.commit()
    for name, table in baseline.Base.metadata.tables.items():
        if name not in existing:continue
        actual={column['name'] for column in inspect(connection).get_columns(name)}
        if set(table.columns.keys())-actual: raise RuntimeError(f'Incomplete schema: {name}')

def downgrade():
    raise RuntimeError('Destructive downgrade disabled; restore the pre-migration SQLite backup.')

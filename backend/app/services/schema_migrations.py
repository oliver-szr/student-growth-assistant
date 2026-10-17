"""One explicit schema upgrade path for startup and CLI. No implicit stamp."""
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from alembic.script import ScriptDirectory
from ..database import Base
from .growth_data import create_sqlite_backup

def upgrade_database(engine):
    config=Config()
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[2]/'alembic'))
    head=ScriptDirectory.from_config(config).get_current_head()
    # Every real schema upgrade gets an online backup, independent of daily backups.
    if inspect(engine).get_table_names():
        with engine.connect() as connection:
            current=connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar() if 'alembic_version' in inspect(connection).get_table_names() else None
        if current==head:
            for name,table in Base.metadata.tables.items():
                if name not in inspect(engine).get_table_names():raise RuntimeError(f'Migration version does not match schema: missing {name}')
                columns={c['name']:c for c in inspect(engine).get_columns(name)}
                if set(table.columns.keys())-set(columns):raise RuntimeError(f'Migration version does not match schema: {name}')
                for column in table.columns:
                    if column.type._type_affinity is not columns[column.name]['type']._type_affinity:raise RuntimeError(f'Incompatible type: {name}.{column.name}')
            return
        create_sqlite_backup(engine, force=True)
    with engine.begin() as connection:
        config.attributes['connection']=connection
        command.upgrade(config,'head')

from sqlalchemy import event, inspect, text
from app.database import Base, create_sqlite_engine
from app.services.schema_migrations import upgrade_database

def test_empty_upgrade_and_repeat(tmp_path):
    engine=create_sqlite_engine(f'sqlite:///{tmp_path / "empty.db"}')
    upgrade_database(engine);upgrade_database(engine)
    assert set(Base.metadata.tables)<=set(inspect(engine).get_table_names())
    with engine.connect() as c:assert c.execute(text('SELECT version_num FROM alembic_version')).scalar()=='0003_conversations'
    engine.dispose()

def test_recognized_legacy_columns_retained(tmp_path,monkeypatch):
    monkeypatch.setenv('SGA_BACKUP_DIR',str(tmp_path/'backups'))
    engine=create_sqlite_engine(f'sqlite:///{tmp_path / "old.db"}')
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(text("INSERT INTO assistant_sessions(id,week_start,scope,created_at) VALUES(1,'2026-10-12','planning','2026-10-04')"))
        c.execute(text('ALTER TABLE assistant_sessions DROP COLUMN scope'))
    upgrade_database(engine)
    with engine.connect() as c:assert c.execute(text('SELECT scope FROM assistant_sessions WHERE id=1')).scalar()=='planning'
    assert list((tmp_path/'backups').rglob('*.sqlite'))
    engine.dispose()

def test_unrecognized_schema_not_stamped(tmp_path,monkeypatch):
    monkeypatch.setenv('SGA_BACKUP_DIR',str(tmp_path/'backups'))
    engine=create_sqlite_engine(f'sqlite:///{tmp_path / "bad.db"}')
    with engine.begin() as c:c.execute(text('CREATE TABLE tasks(id INTEGER PRIMARY KEY, title TEXT)'))
    import pytest
    with pytest.raises(RuntimeError,match='Unrecognized'):upgrade_database(engine)
    with engine.connect() as c:
        if 'alembic_version' in inspect(engine).get_table_names():assert c.execute(text('SELECT COUNT(*) FROM alembic_version')).scalar()==0
    engine.dispose()

def test_dashboard_query_count_constant(client,test_engine):
    counts=[]
    def count(*args):counts.append(1)
    for target in (1,20,100):
        existing=len(client.get('/api/tasks').json())
        for n in range(existing,target):
            assert client.post('/api/tasks',json={'title':f'task {n}','duration_minutes':45,'deadline':'2026-10-21T12:00:00+08:00'}).status_code==201
        event.listen(test_engine,'before_cursor_execute',count)
        try:
            counts.clear();response=client.get('/api/tasks/dashboard');assert response.status_code==200
            assert len(response.json()['tasks'])==target
            assert len(counts)<=7
        finally:event.remove(test_engine,'before_cursor_execute',count)
    assert client.get('/api/profile/context').status_code==200
    assert client.get('/api/review/context').status_code==200


def _version_two_database(engine):
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).parents[1] / 'alembic'))
    with engine.connect() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, '0002_task_hierarchy')
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO assistant_sessions(id,week_start,scope,created_at) VALUES(71,'2026-10-12','planning','2026-10-14 10:00:00')"))
        connection.execute(text("INSERT INTO assistant_proposals(id,session_id,source_revision,status,payload,created_at) VALUES(31,71,0,'ready','{}','2026-10-14 10:00:00')"))
        connection.execute(text("UPDATE assistant_sessions SET latest_proposal_id=31 WHERE id=71"))
        connection.execute(text("INSERT INTO assistant_messages(id,session_id,role,text,proposal_id) VALUES(81,71,'user','历史正文',31)"))


def test_v2_upgrade_preserves_references_and_unknown_historical_times(tmp_path, monkeypatch):
    from sqlalchemy.orm import Session
    from app.models import AssistantSession, AssistantMessage, WorkspaceMetadata
    monkeypatch.setenv('SGA_BACKUP_DIR', str(tmp_path/'backups'))
    engine = create_sqlite_engine(f'sqlite:///{tmp_path / "version-two.db"}')
    try:
        _version_two_database(engine)
        upgrade_database(engine)
        upgrade_database(engine)
        with Session(engine) as db:
            session, message = db.get(AssistantSession,71), db.get(AssistantMessage,81)
            assert session.latest_proposal_id == message.proposal_id == 31
            assert session.title_source == 'legacy' and session.last_activity_at is None
            assert message.text == '历史正文' and message.created_at is None
            assert session.owner_id == message.owner_id == db.get(WorkspaceMetadata,1).owner_id
        with engine.connect() as connection:
            assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
            assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert next(c for c in inspect(engine).get_columns('assistant_sessions') if c['name']=='week_start')['nullable']
        assert list((tmp_path/'backups').rglob('*.sqlite'))
    finally:
        engine.dispose()


def test_migration_failure_rolls_back_ddl_data_and_version_then_can_retry(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setenv('SGA_BACKUP_DIR', str(tmp_path/'backups'))
    engine = create_sqlite_engine(f'sqlite:///{tmp_path / "rollback.db"}')
    try:
        _version_two_database(engine)
        def fail_late(connection, cursor, statement, parameters, context, executemany):
            if 'CREATE INDEX conversation_message_page' in statement:
                raise RuntimeError('injected late DDL failure')
        event.listen(engine, 'before_cursor_execute', fail_late)
        try:
            with pytest.raises(RuntimeError, match='injected late DDL'):
                upgrade_database(engine)
        finally:
            event.remove(engine, 'before_cursor_execute', fail_late)
        assert 'owner_id' not in {c['name'] for c in inspect(engine).get_columns('assistant_sessions')}
        assert not any(name.startswith('_alembic_tmp') for name in inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar() == '0002_task_hierarchy'
            assert connection.exec_driver_sql('SELECT id,text,proposal_id FROM assistant_messages').one() == (81,'历史正文',31)
            assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
            assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        upgrade_database(engine)
        with engine.connect() as connection:
            assert connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar() == '0003_conversations'
    finally:
        engine.dispose()

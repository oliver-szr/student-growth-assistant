from sqlalchemy import event, inspect, text
from app.database import Base, create_sqlite_engine
from app.services.schema_migrations import upgrade_database

def test_empty_upgrade_and_repeat(tmp_path):
    engine=create_sqlite_engine(f'sqlite:///{tmp_path / "empty.db"}')
    upgrade_database(engine);upgrade_database(engine)
    assert set(Base.metadata.tables)<=set(inspect(engine).get_table_names())
    with engine.connect() as c:assert c.execute(text('SELECT version_num FROM alembic_version')).scalar()=='0002_task_hierarchy'
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

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import shutil
from uuid import uuid4

from sqlalchemy.orm import Session

from app.database import Base, create_sqlite_engine
from app.models import GrowthProfileRevision, Task, TaskGrowthContext, TaskPriority, TaskStatus
from app.services.growth_data import create_daily_backup, create_sqlite_backup, list_sqlite_backups
from app.services.growth_migrations import apply_growth_migrations


def test_existing_task_database_gets_growth_context_without_losing_tasks() -> None:
    directory = Path(__file__).resolve().parents[2] / "codex" / ".runtime" / f"migration-test-{uuid4().hex}"
    directory.mkdir(parents=True)
    database = directory / "legacy.db"
    engine = create_sqlite_engine(f"sqlite:///{database.as_posix()}")
    Task.__table__.create(engine)
    with Session(engine) as db:
        db.add(Task(
            title="旧课程作业", description=None, duration_minutes=90,
            deadline=datetime(2026, 10, 10, 12, tzinfo=timezone.utc),
            priority=TaskPriority.high, status=TaskStatus.todo,
        ))
        db.commit()

    # Simulate an application restart where create_all adds new tables but leaves old rows untouched.
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        apply_growth_migrations(db)
        task = db.query(Task).one()
        context = db.get(TaskGrowthContext, task.id)
        profile_revision = db.query(GrowthProfileRevision).one()
        assert task.title == "旧课程作业"
        assert context.initial_estimate_minutes == 90
        assert context.family_confirmed is False
        assert context.goal_id is None
        assert profile_revision.version == 1
    engine.dispose()
    shutil.rmtree(directory)


def test_daily_backup_is_idempotent_and_retains_five_integrity_checked_copies(test_engine, monkeypatch) -> None:
    from app.models import PlanningState

    Base.metadata.create_all(test_engine)
    with Session(test_engine) as db:
        db.add(PlanningState(id=1, revision=7))
        db.commit()
    directory = Path(__file__).resolve().parents[2] / "codex" / ".runtime" / f"backup-test-{uuid4().hex}"
    directory.mkdir(parents=True)
    try:
        monkeypatch.setenv("SGA_BACKUP_DIR", str(directory))
        first = create_daily_backup(test_engine)
        second = create_daily_backup(test_engine)
        assert first == second
        db = sqlite3.connect(first)
        try:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert db.execute("SELECT revision FROM planning_state WHERE id=1").fetchone()[0] == 7
        finally:
            db.close()
        for _ in range(7):
            create_sqlite_backup(test_engine, force=True)

        backups = list_sqlite_backups(test_engine)
        assert len(backups) == 5
    finally:
        shutil.rmtree(directory)

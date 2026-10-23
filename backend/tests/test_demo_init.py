from pathlib import Path
import importlib.util
import pytest
from uuid import uuid4
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Task,Plan,TimeRule,TaskFeedback,TaskGrowthContext,TaskStatus
from app.database import Base,create_sqlite_engine


def test_seed_is_repeatable_and_safe(monkeypatch):
    path=Path(__file__).resolve().parents[2]/'scripts'/'demo_init.py'
    spec=importlib.util.spec_from_file_location('demo_init',path)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    data_dir=Path(__file__).resolve().parents[1]/'data'
    token=uuid4().hex
    normal=data_dir/f'normal-{token}.db'
    database=data_dir/f'test-{token}.db'
    with pytest.raises(ValueError): mod.initialize(normal)
    engine=create_sqlite_engine(f'sqlite:///{database.as_posix()}')
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            mod.seed(db,mod.example_source())
            db.commit()
            mod.seed(db,mod.example_source())
            db.commit()
            assert len(db.scalars(select(Task).where(Task.status==TaskStatus.todo)).all())==3
            assert len(db.scalars(select(TaskFeedback)).all())==10
            assert len(db.scalars(select(Plan)).all())==1
            assert any(r.recurrence.value=='once' for r in db.scalars(select(TimeRule)).all())
            from app.services import assistant_clock
            from app.services.growth_insights import collect_supported_observations
            from app.routers.growth import _duration_advice
            now=mod.DEMO_NOW
            monkeypatch.setattr(assistant_clock,'assistant_now',lambda:now)
            observations=collect_supported_observations(db)
            assert {item['candidate_id'] for item in observations}=={'writing:morning','practice:afternoon'}
            assert all(item['sample_count']==5 for item in observations)
            report=db.scalar(select(Task).where(Task.title=='软件工程报告'))
            context=db.get(TaskGrowthContext,report.id)
            advice=_duration_advice(db,report,context,now)
            assert advice['suggested_minutes']==90
    finally:
        engine.dispose()
        database.unlink(missing_ok=True)

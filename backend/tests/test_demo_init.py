from pathlib import Path
import importlib.util
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Task,Plan,TimeRule
from app.database import Base,create_sqlite_engine


def test_seed_is_repeatable_and_safe(tmp_path):
    path=Path(__file__).resolve().parents[2]/'codex'/'demo_init.py'
    spec=importlib.util.spec_from_file_location('demo_init',path)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    normal=tmp_path/'app.db'
    with pytest.raises(ValueError): mod.initialize(normal)
    engine=create_sqlite_engine(f'sqlite:///{(tmp_path/"test.db").as_posix()}')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        mod.seed(db,mod.example_source())
        db.commit()
        mod.seed(db,mod.example_source())
        db.commit()
        assert len(db.scalars(select(Task)).all())==3
        assert len(db.scalars(select(Plan)).all())==1
        assert any(r.recurrence.value=='once' for r in db.scalars(select(TimeRule)).all())
    engine.dispose()

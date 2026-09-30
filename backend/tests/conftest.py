"""Each API test uses its own temporary SQLite database."""

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import create_sqlite_engine, get_db
from app.main import app


@pytest.fixture
def test_engine(tmp_path: Path) -> Generator[Engine, None, None]:
    database_path = tmp_path / "test.db"
    engine = create_sqlite_engine(f"sqlite:///{database_path.as_posix()}")
    yield engine
    engine.dispose()
    database_path.unlink(missing_ok=True)


@pytest.fixture
def client(test_engine: Engine) -> Generator[TestClient, None, None]:
    testing_sessions = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

    def get_test_db() -> Generator[Session, None, None]:
        with testing_sessions() as session:
            yield session

    original_engine = app.state.db_engine
    original_override = app.dependency_overrides.get(get_db)
    app.state.db_engine = test_engine
    app.dependency_overrides[get_db] = get_test_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        if original_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = original_override
        app.state.db_engine = original_engine

"""Each API test uses its own temporary SQLite database."""

from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import create_sqlite_engine, get_db
from app.main import app


@pytest.fixture(autouse=True)
def no_live_ai(monkeypatch):
    """All pytest parsing is mocked; never load local secrets or pay a provider."""
    from app.services import assistant_ai, claude_client, constraint_parser, plan_explanation

    monkeypatch.setattr(claude_client, "load_dotenv", lambda *args, **kwargs: None)
    for name in ("CLAUDE_API_KEY", "CLAUDE_MODEL", "CLAUDE_BASE_URL", "CLAUDE_API_VERSION", "AI_API_FORMAT", "AI_THINKING_EFFORT", "AI_TIMEOUT_SECONDS", "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SGA_AUTO_BACKUP", "0")
    monkeypatch.setenv("SGA_SKIP_IMPORT_BACKUP", "1")

    async def reject_live_request(*args, **kwargs):
        raise AssertionError("pytest must mock Claude parsing")

    monkeypatch.setattr(constraint_parser, "request_claude", reject_live_request)
    monkeypatch.setattr(plan_explanation, "request_claude", reject_live_request)

    async def select_review_facts(facts, suggestions):
        suggestion_id = suggestions[0]["id"] if suggestions else None
        return {"lead_fact_id": facts[0]["id"], "additional_fact_ids": [], "suggestion_id": suggestion_id}

    monkeypatch.setattr(assistant_ai, "select_growth_review", select_review_facts)


@pytest.fixture
def test_engine() -> Generator[Engine, None, None]:
    database_path = Path(__file__).resolve().parents[1] / 'data' / f'test-{uuid4().hex}.db'
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

"""Cross-stage anonymous HTTP acceptance and repeatable test clocks."""
from pathlib import Path
import runpy
from uuid import uuid4
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEMO = runpy.run_path(str(ROOT/"scripts/integration_demo.py"))


def test_mock_breakdown_planning_repair_feedback_and_statistics(client, monkeypatch):
    from app.services import assistant_ai
    monkeypatch.setenv("SGA_DEMO", "1")
    monkeypatch.setenv("SGA_DEMO_NOW", DEMO["NOW"])
    monkeypatch.setenv("SGA_DATABASE_PATH", str(ROOT/"scripts/.runtime"/f"demo-test-{uuid4().hex}.db"))
    monkeypatch.setattr(assistant_ai, "decompose_task", DEMO["mock_breakdown"])
    result = DEMO["exercise"](client)
    assert result["known_actual_minutes"] == 40


def test_default_clock_is_fixed_for_imported_aliases_and_database_timestamps():
    from app.models import utc_now
    from app.services.assistant_clock import assistant_now
    assert assistant_now().isoformat() == "2026-10-14T18:00:00+08:00"
    assert utc_now().isoformat() == "2026-10-14T10:00:00+00:00"


def test_verification_refuses_an_unmarked_server_before_any_write(monkeypatch, tmp_path):
    import httpx
    requests = []
    def respond(request):
        requests.append(request.method)
        return httpx.Response(200, json={"status": "ok"})
    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(sys, "argv", ["integration_demo.py", "--verify", "--output", str(tmp_path/"report.json")])
    with pytest.raises(RuntimeError, match="explicitly mocked server"):
        DEMO["main"]()
    assert requests == ["GET"]

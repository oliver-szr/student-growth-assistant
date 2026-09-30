import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import TimeRule


COURSE = {
    "kind": "course",
    "title": "Software Engineering",
    "recurrence": "weekly",
    "weekday": 3,
    "date": None,
    "start_time": "10:00",
    "end_time": "12:00",
}
PROTECTED_WEEKLY = {
    **COURSE,
    "kind": "protected",
    "title": "Wednesday evening",
    "start_time": "18:00",
    "end_time": "22:00",
}
PROTECTED_ONCE = {
    **COURSE,
    "kind": "protected",
    "title": "One-time break",
    "recurrence": "once",
    "weekday": None,
    "date": "2026-10-07",
}


@pytest.mark.parametrize("payload", [COURSE, PROTECTED_WEEKLY, PROTECTED_ONCE])
def test_create_get_and_database_persistence(
    client: TestClient, test_engine: Engine, payload: dict[str, object]
) -> None:
    response = client.post("/api/time-rules", json=payload)
    assert response.status_code == 201
    created = response.json()
    assert created["kind"] == payload["kind"]
    assert created["recurrence"] == payload["recurrence"]
    assert created["active"] is True
    assert created["created_at"] and created["updated_at"]

    listing = client.get("/api/time-rules")
    assert listing.status_code == 200
    assert [rule["id"] for rule in listing.json()] == [created["id"]]

    with Session(test_engine) as session:
        saved = session.get(TimeRule, created["id"])
        assert saved is not None
        assert saved.title == payload["title"]


@pytest.mark.parametrize("changes", [
    {"weekday": None},
    {"date": "2026-10-07"},
    {"kind": "course", "recurrence": "once", "weekday": None, "date": "2026-10-07"},
    {"start_time": "10:00", "end_time": "10:00"},
    {"start_time": "12:00", "end_time": "10:00"},
    {"weekday": 0},
    {"weekday": 8},
    {"title": "   "},
    {"kind": "unknown"},
])
def test_rejects_invalid_weekly_course(client: TestClient, changes: dict[str, object]) -> None:
    response = client.post("/api/time-rules", json={**COURSE, **changes})
    assert response.status_code == 422


@pytest.mark.parametrize("changes", [
    {"date": None},
    {"weekday": 3},
])
def test_rejects_invalid_once_protected(client: TestClient, changes: dict[str, object]) -> None:
    assert client.post(
        "/api/time-rules", json={**PROTECTED_ONCE, **changes}
    ).status_code == 422


def test_patch_title_deactivate_and_change_recurrence(client: TestClient) -> None:
    rule_id = client.post("/api/time-rules", json=PROTECTED_WEEKLY).json()["id"]

    title = client.patch(f"/api/time-rules/{rule_id}", json={"title": "  Rest time  "})
    assert title.status_code == 200
    assert title.json()["title"] == "Rest time"

    inactive = client.patch(f"/api/time-rules/{rule_id}", json={"active": False})
    assert inactive.status_code == 200
    assert inactive.json()["active"] is False
    assert inactive.json()["updated_at"] != title.json()["updated_at"]
    assert client.get("/api/time-rules").json()[0]["active"] is False

    before_invalid_patch = client.get("/api/time-rules").json()[0]
    invalid = client.patch(f"/api/time-rules/{rule_id}", json={"recurrence": "once"})
    assert invalid.status_code == 422
    assert client.get("/api/time-rules").json()[0] == before_invalid_patch

    once = client.patch(
        f"/api/time-rules/{rule_id}",
        json={"recurrence": "once", "weekday": None, "date": "2026-10-08"},
    )
    assert once.status_code == 200
    assert once.json()["recurrence"] == "once"
    assert once.json()["weekday"] is None
    assert once.json()["date"] == "2026-10-08"


def test_patch_rejects_invalid_final_state_without_writing(client: TestClient) -> None:
    rule_id = client.post("/api/time-rules", json=COURSE).json()["id"]
    before = client.get("/api/time-rules").json()[0]

    response = client.patch(f"/api/time-rules/{rule_id}", json={"recurrence": "once"})
    assert response.status_code == 422
    assert "once requires date and no weekday" in str(response.json())
    assert client.get("/api/time-rules").json()[0] == before

    response = client.patch(
        f"/api/time-rules/{rule_id}",
        json={"recurrence": "once", "weekday": None, "date": "2026-10-07"},
    )
    assert response.status_code == 422
    assert "course must be weekly" in str(response.json())
    assert client.get("/api/time-rules").json()[0] == before


def test_patch_missing_rule_and_no_delete(client: TestClient) -> None:
    assert client.patch("/api/time-rules/999", json={"title": "Missing"}).status_code == 404
    assert client.delete("/api/time-rules/999").status_code == 405

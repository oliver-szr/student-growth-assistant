from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import Task


TASK = {
    "title": "  Finish report  ",
    "description": "Phase 2 test",
    "duration_minutes": 90,
    "deadline": "2026-10-05T18:00:00+08:00",
    "priority": "high",
}


@pytest.mark.parametrize("duration", [1, 17, 31])
def test_create_get_and_database_persistence(client: TestClient, test_engine: Engine, duration: int) -> None:
    response = client.post("/api/tasks", json={**TASK, "duration_minutes": duration})
    assert response.status_code == 201
    created = response.json()
    assert created["title"] == "Finish report"
    assert created["status"] == "todo"
    assert created["priority"] == "high"
    assert created["duration_minutes"] == duration
    assert created["deadline"] == "2026-10-05T10:00:00Z"
    assert created["created_at"] and created["updated_at"]

    listing = client.get("/api/tasks")
    assert listing.status_code == 200
    assert [task["id"] for task in listing.json()] == [created["id"]]
    assert listing.json()[0]["duration_minutes"] == duration

    with Session(test_engine) as session:
        saved = session.get(Task, created["id"])
        assert saved is not None
        assert saved.title == "Finish report"
        assert saved.duration_minutes == duration
        assert saved.deadline == datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)


def test_deadline_timezone_round_trip(client: TestClient, test_engine: Engine) -> None:
    input_deadline = "2026-10-05T22:00:00+08:00"
    created = client.post("/api/tasks", json={**TASK, "deadline": input_deadline})
    assert created.status_code == 201
    task_id = created.json()["id"]

    with test_engine.connect() as connection:
        raw_value = connection.exec_driver_sql(
            "SELECT deadline FROM tasks WHERE id = ?", (task_id,)
        ).scalar_one()
    assert raw_value.startswith("2026-10-05 14:00:00")

    with Session(test_engine) as session:
        deadline = session.get(Task, task_id).deadline
    assert deadline == datetime(2026, 10, 5, 14, 0, tzinfo=timezone.utc)
    assert deadline.utcoffset() == timedelta(0)
    assert deadline < datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)

    listed = client.get("/api/tasks")
    assert listed.status_code == 200
    assert listed.json()[0]["deadline"] == "2026-10-05T14:00:00Z"

    changed = client.patch(
        f"/api/tasks/{task_id}", json={"deadline": "2026-10-06T09:00:00+09:00"}
    )
    assert changed.status_code == 200
    assert changed.json()["deadline"] == "2026-10-06T00:00:00Z"
    assert client.get("/api/tasks").json()[0]["deadline"] == "2026-10-06T00:00:00Z"


@pytest.mark.parametrize("title", ["", "   "])
def test_rejects_blank_title(client: TestClient, title: str) -> None:
    assert client.post("/api/tasks", json={**TASK, "title": title}).status_code == 422


@pytest.mark.parametrize("duration", [0, -1, 17.5, True])
def test_rejects_invalid_duration(client: TestClient, duration: object) -> None:
    assert client.post("/api/tasks", json={**TASK, "duration_minutes": duration}).status_code == 422


def test_rejects_invalid_priority_status_and_naive_deadline(client: TestClient) -> None:
    assert client.post("/api/tasks", json={**TASK, "priority": "urgent"}).status_code == 422
    assert client.post("/api/tasks", json={**TASK, "status": "done"}).status_code == 422
    assert client.post(
        "/api/tasks", json={**TASK, "deadline": "2026-10-05T18:00:00"}
    ).status_code == 422


def test_patch_title_duration_done_and_cancelled(client: TestClient) -> None:
    task_id = client.post("/api/tasks", json=TASK).json()["id"]

    title_change = client.patch(f"/api/tasks/{task_id}", json={"title": "  Updated  "})
    assert title_change.status_code == 200
    assert title_change.json()["title"] == "Updated"
    assert title_change.json()["duration_minutes"] == 90

    duration_change = client.patch(f"/api/tasks/{task_id}", json={"duration_minutes": 17})
    assert duration_change.status_code == 200
    assert duration_change.json()["duration_minutes"] == 17
    assert client.get("/api/tasks").json()[0]["duration_minutes"] == 17
    assert duration_change.json()["updated_at"] != title_change.json()["updated_at"]

    done = client.patch(f"/api/tasks/{task_id}", json={"status": "done"})
    assert done.status_code == 200
    assert done.json()["status"] == "done"
    assert [task["id"] for task in client.get("/api/tasks?status=done").json()] == [task_id]

    cancelled = client.patch(f"/api/tasks/{task_id}", json={"status": "cancelled"})
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert client.get("/api/tasks?status=done").json() == []
    assert [task["id"] for task in client.get("/api/tasks?status=cancelled").json()] == [task_id]


@pytest.mark.parametrize("changes", [
    {"duration_minutes": 17.5},
    {"duration_minutes": 0},
    {"duration_minutes": None},
    {"title": "   "},
    {"priority": "urgent"},
    {"status": "unknown"},
    {"deadline": None},
    {"id": 999},
])
def test_patch_rejects_invalid_fields(client: TestClient, changes: dict[str, object]) -> None:
    task_id = client.post("/api/tasks", json=TASK).json()["id"]
    assert client.patch(f"/api/tasks/{task_id}", json=changes).status_code == 422
    assert client.get("/api/tasks").json()[0]["title"] == "Finish report"


def test_patch_missing_task_and_no_delete(client: TestClient) -> None:
    assert client.patch("/api/tasks/999", json={"title": "Missing"}).status_code == 404
    assert client.delete("/api/tasks/999").status_code == 405

from datetime import timedelta

from fastapi.testclient import TestClient
from app.services.assistant_clock import assistant_now


def test_export_and_import_restore_growth_data_atomically(client: TestClient) -> None:
    task = client.post("/api/tasks", json={
        "title": "项目复盘",
        "duration_minutes": 60,
        "deadline": (assistant_now() + timedelta(days=2)).isoformat(),
        "priority": "high",
    }).json()
    client.put("/api/goals/direction", json={"direction": "持续完成课程项目"})
    client.post("/api/goals", json={
        "title": "每周完成一次复盘", "metric_kind": "count", "weekly_target": 1, "unit_label": "次",
    })

    exported = client.get("/api/data/export")
    assert exported.status_code == 200
    snapshot = exported.json()
    assert snapshot["format_version"] == 1
    assert "growth_goals" in snapshot["tables"]

    client.patch(f"/api/tasks/{task['id']}", json={"status": "done"})
    client.put("/api/goals/direction", json={"direction": "should be rolled back"})
    restored = client.post("/api/data/import", json=snapshot)

    assert restored.status_code == 200
    assert client.get("/api/goals").json()["direction"] == "持续完成课程项目"
    assert client.get("/api/tasks").json()[0]["status"] == "todo"
    assert restored.json()["revision"] > snapshot["revision"]


def test_invalid_import_rolls_back_all_rows(client: TestClient) -> None:
    task = client.post("/api/tasks", json={
        "title": "保留任务", "duration_minutes": 60,
        "deadline": (assistant_now() + timedelta(days=2)).isoformat(), "priority": "normal",
    }).json()
    snapshot = client.get("/api/data/export").json()
    snapshot["tables"]["tasks"][0]["unknown_column"] = "invalid"

    response = client.post("/api/data/import", json=snapshot)

    assert response.status_code == 422
    assert [row["id"] for row in client.get("/api/tasks").json()] == [task["id"]]


def test_task_growth_context_patch_preserves_goal_when_omitted(client: TestClient) -> None:
    goal = client.post("/api/goals", json={
        "title": "完成项目", "metric_kind": "deliverable", "weekly_target": 1, "unit_label": "项",
    }).json()
    task = client.post("/api/tasks", json={
        "title": "实现功能", "duration_minutes": 60,
        "deadline": (assistant_now() + timedelta(days=2)).isoformat(), "priority": "normal",
    }).json()
    client.put(f"/api/tasks/{task['id']}/growth-context", json={"family": "writing", "goal_id": goal["id"]})

    changed = client.put(f"/api/tasks/{task['id']}/growth-context", json={"family": "reading"})

    assert changed.status_code == 200
    assert changed.json()["goal_id"] == goal["id"]


def test_import_requires_full_valid_snapshot_and_keeps_database_on_bad_reference(client: TestClient) -> None:
    task = client.post("/api/tasks", json={
        "title": "引用完整性", "duration_minutes": 60,
        "deadline": (assistant_now() + timedelta(days=2)).isoformat(), "priority": "normal",
    }).json()
    snapshot = client.get("/api/data/export").json()
    snapshot["tables"]["task_growth_contexts"][0]["goal_id"] = 999999

    response = client.post("/api/data/import", json=snapshot)

    assert response.status_code == 422
    assert client.get("/api/tasks").json()[0]["id"] == task["id"]


def test_import_does_not_accept_wrong_schema_version(client: TestClient) -> None:
    snapshot = client.get("/api/data/export").json()
    snapshot["format_version"] = 999

    response = client.post("/api/data/import", json=snapshot)

    assert response.status_code == 422

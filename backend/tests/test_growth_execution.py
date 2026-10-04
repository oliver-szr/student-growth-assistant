from fastapi.testclient import TestClient


def _task(client: TestClient) -> int:
    response = client.post(
        "/api/tasks",
        json={
            "title": "短报告",
            "duration_minutes": 120,
            "deadline": "2026-10-11T20:00:00+08:00",
            "priority": "normal",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_completion_feedback_is_idempotent_and_records_actual_minutes(client: TestClient) -> None:
    task_id = _task(client)
    payload = {
        "client_action_id": "complete-report-1",
        "outcome": "completed",
        "actual_minutes": 86,
        "difficulty": "expected",
        "family": "短报告写作",
    }

    first = client.post(f"/api/tasks/{task_id}/feedback", json=payload)
    assert first.status_code == 201
    assert first.json()["task_status"] == "done"
    assert first.json()["actual_minutes"] == 86
    assert first.json()["initial_estimate_minutes"] == 120
    assert first.json()["eligible_for_learning"] is True

    duplicate = client.post(f"/api/tasks/{task_id}/feedback", json=payload)
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == first.json()["id"]
    history = client.get(f"/api/tasks/{task_id}/feedback")
    assert history.status_code == 200
    assert len(history.json()["entries"]) == 1
    assert client.get("/api/tasks").json()[0]["status"] == "done"


def test_partial_feedback_updates_remaining_time_without_completing(client: TestClient) -> None:
    task_id = _task(client)
    response = client.post(
        f"/api/tasks/{task_id}/feedback",
        json={
            "client_action_id": "partial-report-1",
            "outcome": "partial",
            "actual_minutes": 42,
            "remaining_minutes": 60,
            "family": "短报告写作",
        },
    )
    assert response.status_code == 201
    assert response.json()["cumulative_actual_minutes"] == 42
    assert response.json()["remaining_minutes"] == 60
    task = client.get("/api/tasks").json()[0]
    assert task["status"] == "todo"
    assert task["duration_minutes"] == 60


def test_task_status_patch_uses_one_unknown_effort_record(client: TestClient) -> None:
    task_id = _task(client)
    for _ in range(2):
        changed = client.patch(f"/api/tasks/{task_id}", json={"status": "done"})
        assert changed.status_code == 200
    history = client.get(f"/api/tasks/{task_id}/feedback")
    assert history.status_code == 200
    assert len(history.json()["entries"]) == 1
    assert history.json()["entries"][0]["actual_minutes"] is None
    assert history.json()["entries"][0]["eligible_for_learning"] is False


def test_work_timer_can_pause_resume_and_needs_explicit_feedback(client: TestClient) -> None:
    task_id = _task(client)
    start = client.post(
        "/api/work-sessions/start",
        json={"task_id": task_id, "client_action_id": "timer-start-1"},
    )
    assert start.status_code == 201
    assert start.json()["status"] == "running"

    pause = client.post(f"/api/work-sessions/{start.json()['id']}/pause")
    assert pause.status_code == 200
    assert pause.json()["status"] == "paused"

    resume = client.post(f"/api/work-sessions/{start.json()['id']}/resume")
    assert resume.status_code == 200
    assert resume.json()["status"] == "running"

    finish = client.post(f"/api/work-sessions/{start.json()['id']}/finish")
    assert finish.status_code == 200
    assert finish.json()["status"] == "stopped"
    assert finish.json()["confirmed_for_learning"] is False
    assert client.get(f"/api/tasks/{task_id}/feedback").json()["entries"] == []

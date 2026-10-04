from datetime import timedelta

from fastapi.testclient import TestClient

from app.services.assistant_clock import assistant_now


def _task(client: TestClient, title: str, minutes: int = 120) -> int:
    response = client.post("/api/tasks", json={
        "title": title,
        "duration_minutes": minutes,
        "deadline": (assistant_now() + timedelta(days=10)).isoformat(),
        "priority": "normal",
    })
    assert response.status_code == 201
    return response.json()["id"]


def _record(client: TestClient, task_id: int, action: str, completed_at, actual: int = 60) -> None:
    response = client.post(f"/api/tasks/{task_id}/feedback", json={
        "client_action_id": action,
        "outcome": "completed",
        "actual_minutes": actual,
        "family": "写作",
        "completed_at": completed_at.isoformat(),
    })
    assert response.status_code == 201


def test_duration_advice_uses_five_distinct_confirmed_tasks_and_caps_reduction(client: TestClient) -> None:
    now = assistant_now()
    target = _task(client, "本次短报告")
    context = client.put(f"/api/tasks/{target}/growth-context", json={"family": "写作", "goal_id": None})
    assert context.status_code == 200
    for index, day in enumerate([1, 1, 2, 4, 6]):
        task_id = _task(client, f"历史报告 {index}")
        _record(client, task_id, f"done-{index}", now - timedelta(days=day))

    result = client.get(f"/api/growth/tasks/{target}/duration-advice")

    assert result.status_code == 200
    advice = result.json()
    assert advice["status"] == "suggested"
    assert advice["current_minutes"] == 120
    assert advice["suggested_minutes"] == 90
    assert advice["evidence"]["sample_count"] == 5
    assert advice["evidence"]["active_days"] == 4


def test_duration_advice_does_not_infer_from_fewer_than_five_tasks(client: TestClient) -> None:
    now = assistant_now()
    target = _task(client, "本次短报告")
    client.put(f"/api/tasks/{target}/growth-context", json={"family": "写作", "goal_id": None})
    for index in range(4):
        task_id = _task(client, f"历史报告 {index}")
        _record(client, task_id, f"few-{index}", now - timedelta(days=index + 1))

    advice = client.get(f"/api/growth/tasks/{target}/duration-advice").json()

    assert advice["status"] == "insufficient_data"
    assert advice["suggestion"] is None

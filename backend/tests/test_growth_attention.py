from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


def _task(client: TestClient, title: str, deadline: datetime, priority: str = "normal") -> int:
    response = client.post("/api/tasks", json={
        "title": title,
        "duration_minutes": 60,
        "deadline": deadline.isoformat(),
        "priority": priority,
    })
    assert response.status_code == 201
    return response.json()["id"]


def test_attention_separates_user_importance_from_dynamic_urgency(client: TestClient) -> None:
    now = datetime.now(timezone.utc)
    later_high = _task(client, "长期项目", now + timedelta(days=4), "high")
    soon_low = _task(client, "明早汇报稿", now + timedelta(hours=10), "low")

    response = client.get("/api/growth/attention")

    assert response.status_code == 200
    tasks = response.json()["items"]
    assert tasks[0]["task_id"] == soon_low
    assert tasks[0]["urgency"] in {"critical", "urgent"}
    assert tasks[0]["importance"] == "low"
    assert tasks[1]["task_id"] == later_high
    assert tasks[1]["importance"] == "high"
    assert tasks[0]["reason"]


def test_attention_marks_overdue_tasks_without_changing_deadline(client: TestClient) -> None:
    deadline = datetime.now(timezone.utc) - timedelta(days=1)
    task_id = _task(client, "逾期作业", deadline)

    response = client.get("/api/growth/attention")

    assert response.status_code == 200
    item = next(x for x in response.json()["items"] if x["task_id"] == task_id)
    assert item["urgency"] == "overdue"
    assert datetime.fromisoformat(item["deadline"]) == deadline.astimezone(datetime.fromisoformat(item["deadline"]).tzinfo)
    assert datetime.fromisoformat(client.get("/api/tasks").json()[0]["deadline"]) == deadline


def test_seven_day_urgency_reason_does_not_claim_calendar_week(client: TestClient) -> None:
    deadline = datetime.now(timezone.utc) + timedelta(days=6)
    task_id = _task(client, "下周截止任务", deadline)

    response = client.get("/api/growth/attention")

    assert response.status_code == 200
    item = next(x for x in response.json()["items"] if x["task_id"] == task_id)
    assert item["urgency"] == "soon"
    assert item["reason"].startswith("7天内截止")


def test_paused_goal_no_longer_changes_current_attention_context(client: TestClient) -> None:
    goal = client.post("/api/goals", json={
        "title": "已暂停目标", "metric_kind": "count", "weekly_target": 2, "unit_label": "次", "priority": 1,
    }).json()
    task_id = _task(client, "目标关联任务", datetime.now(timezone.utc) + timedelta(days=3))
    client.put(f"/api/tasks/{task_id}/growth-context", json={"family": "writing", "goal_id": goal["id"]})
    client.patch(f"/api/goals/{goal['id']}", json={"status": "paused"})

    item = next(row for row in client.get("/api/growth/attention").json()["items"] if row["task_id"] == task_id)

    assert item["goal"] is None

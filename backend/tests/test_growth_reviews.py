from datetime import timedelta

from fastapi.testclient import TestClient

from app.services.assistant_clock import assistant_now


def _week_start() -> str:
    today = assistant_now().date()
    return (today - timedelta(days=today.weekday())).isoformat()


def test_profile_keeps_user_confirmed_versions(client: TestClient) -> None:
    initial = client.get("/api/growth/profile").json()
    assert initial["version"] == 1
    assert len(initial["history"]) == 1

    saved = client.put("/api/goals/direction", json={"direction": "建立稳定的科研阅读习惯"})
    assert saved.status_code == 200
    changed = client.get("/api/growth/profile").json()
    assert changed["direction"] == "建立稳定的科研阅读习惯"
    assert changed["version"] == 2
    assert changed["history"][-1]["direction"] == changed["direction"]


def test_week_review_counts_only_confirmed_feedback_and_goal_progress(client: TestClient) -> None:
    goal = client.post("/api/goals", json={
        "title": "每周阅读三篇",
        "metric_kind": "count",
        "weekly_target": 3,
        "unit_label": "篇",
    }).json()
    task = client.post("/api/tasks", json={
        "title": "论文阅读",
        "duration_minutes": 60,
        "deadline": (assistant_now() + timedelta(days=2)).isoformat(),
        "priority": "normal",
    }).json()
    client.put(f"/api/tasks/{task['id']}/growth-context", json={"family": "reading", "goal_id": goal["id"]})
    completed_at = assistant_now() - timedelta(hours=1)
    saved = client.post(f"/api/tasks/{task['id']}/feedback", json={
        "client_action_id": "review-confirmed-1",
        "outcome": "completed",
        "actual_minutes": 47,
        "family": "reading",
        "completed_at": completed_at.isoformat(),
    })
    assert saved.status_code == 201

    review = client.post("/api/growth/reviews", json={"week_start": _week_start()})

    assert review.status_code == 201
    facts = review.json()["facts"]
    assert facts["completed_count"] == 1
    assert facts["confirmed_actual_minutes"] == 47
    assert facts["goal_progress"] == [{
        "goal_id": goal["id"], "goal_title": "每周阅读三篇", "metric_kind": "count",
        "target": 3, "unit_label": "篇", "actual": 1, "remaining": 2, "status": "active",
    }]
    assert review.json()["summary_mode"] == "ai"
    assert "本周重点" in review.json()["narrative"]


def test_week_review_includes_partial_and_postponed_effort_without_counting_as_completed(client: TestClient) -> None:
    goal = client.post("/api/goals", json={"title": "每周阅读两篇", "metric_kind": "count", "weekly_target": 2, "unit_label": "篇"}).json()
    task = client.post("/api/tasks", json={
        "title": "本周阅读", "duration_minutes": 60,
        "deadline": (assistant_now() + timedelta(days=2)).isoformat(), "priority": "normal",
    }).json()
    client.put(f"/api/tasks/{task['id']}/growth-context", json={"family": "reading", "goal_id": goal["id"]})
    response = client.post(f"/api/tasks/{task['id']}/feedback", json={
        "client_action_id": "review-partial-1", "outcome": "partial", "actual_minutes": 25,
        "remaining_minutes": 30, "reason": "临时开会",
    })
    assert response.status_code == 201

    review = client.post("/api/growth/reviews", json={"week_start": _week_start()}).json()
    facts = review["facts"]
    assert facts["completed_count"] == 0
    assert facts["confirmed_actual_minutes"] == 25
    assert facts["goal_progress"][0]["actual"] == 0
    assert facts["blockers"][0]["reason"] == "临时开会"
    assert facts["execution_feedback"][0]["outcome"] == "partial"


def test_review_revisions_are_kept_instead_of_overwritten(client: TestClient) -> None:
    first = client.post("/api/growth/reviews", json={"week_start": _week_start()}).json()
    second = client.post("/api/growth/reviews", json={"week_start": _week_start()}).json()

    assert second["version"] == first["version"] + 1
    history = client.get(f"/api/growth/reviews?week_start={_week_start()}").json()["reviews"]
    assert len(history) == 2


def test_ai_review_failure_keeps_fact_based_fallback(client: TestClient, monkeypatch) -> None:
    from app.services import assistant_ai
    from app.services.claude_client import AIServiceError

    async def unavailable(*args, **kwargs):
        raise AIServiceError("AI_UNAVAILABLE")

    monkeypatch.setattr(assistant_ai, "select_growth_review", unavailable)
    review = client.post("/api/growth/reviews", json={"week_start": _week_start()})

    assert review.status_code == 201
    assert review.json()["summary_mode"] == "facts_only"
    assert "AI 暂时无法整理说明" in review.json()["narrative"]
    assert review.json()["facts"]["completed_count"] == 0

from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import Task, TaskFeedback, TaskGrowthContext, TaskWorkSession, TaskPriority, TaskStatus, utc_now
from app.services.assistant_clock import assistant_now


def _seed_timed_tasks(test_engine) -> None:
    now = assistant_now()
    with Session(test_engine) as db:
        for index, days_ago in enumerate([1, 1, 2, 4, 6], start=1):
            task = Task(
                title=f"报告 {index}",
                duration_minutes=120,
                deadline=now + timedelta(days=10),
                priority=TaskPriority.normal,
                status=TaskStatus.done,
            )
            db.add(task); db.flush()
            completed = now - timedelta(days=days_ago)
            started = (completed - timedelta(hours=2)).replace(hour=9, minute=0)
            db.add(TaskGrowthContext(task_id=task.id, family="writing", family_confirmed=True, initial_estimate_minutes=120))
            db.add(TaskFeedback(
                task_id=task.id, client_action_id=f"seed-{index}", outcome="completed", actual_minutes=90,
                title_snapshot=task.title, deadline_snapshot=task.deadline, priority_snapshot="normal",
                family_snapshot="writing", family_confirmed_snapshot=True, initial_estimate_minutes=120,
                completed_at=completed, created_at=completed,
            ))
            db.add(TaskWorkSession(
                task_id=task.id, client_action_id=f"timer-{index}", status="stopped",
                family_snapshot="writing", family_confirmed_snapshot=True, accumulated_seconds=5400,
                segment_started_at=None, started_at=started, updated_at=started,
            ))
        db.commit()


def test_ai_habit_observation_is_a_draft_until_user_accepts(client, test_engine, monkeypatch) -> None:
    from app.services import assistant_ai

    _seed_timed_tasks(test_engine)
    saved = client.put("/api/assistant/preferences", json={
        "task_windows": {"writing": [{"start": "13:00", "end": "18:00"}]},
        "avoid_windows": [], "deadline_buffer_hours": 24, "adjustment_mode": "balanced",
    })
    assert saved.status_code == 200, saved.text

    async def choose_supported(candidates, preferences=None):
        assert candidates[0]["sample_count"] >= 5
        assert preferences["task_windows"]["writing"] == [{"start": "13:00", "end": "18:00"}]
        return ["writing:morning"]
    monkeypatch.setattr(assistant_ai, "select_growth_insights", choose_supported)

    analyzed = client.post("/api/growth/insights/analyze")
    assert analyzed.status_code == 200
    created = analyzed.json()["created"]
    assert len(created) == 1
    insight = created[0]
    assert insight["status"] == "draft"
    assert insight["evidence"]["sample_count"] == 5
    assert client.get("/api/assistant/preferences").json()["task_windows"].get("writing")

    accepted = client.post(f"/api/growth/insights/{insight['id']}/accept")
    assert accepted.status_code == 200
    assert accepted.json()["insight"]["status"] == "accepted"
    assert accepted.json()["preferences"]["task_windows"]["writing"] == [{"start": "08:00", "end": "12:00"}]


def test_ai_cannot_create_a_habit_when_timer_sample_gate_is_not_met(client, monkeypatch) -> None:
    from app.services import assistant_ai

    async def should_not_call(candidates, preferences=None):
        raise AssertionError("no supported observation should reach the AI")
    monkeypatch.setattr(assistant_ai, "select_growth_insights", should_not_call)

    result = client.post("/api/growth/insights/analyze")

    assert result.status_code == 200
    assert result.json()["status"] == "insufficient_data"
    assert client.get("/api/growth/insights").json()["insights"] == []


def test_existing_confirmed_window_is_not_repeated_as_a_new_insight(client, test_engine, monkeypatch) -> None:
    from app.services import assistant_ai

    _seed_timed_tasks(test_engine)
    saved = client.put("/api/assistant/preferences", json={
        "task_windows": {"writing": [{"start": "08:00", "end": "12:00"}]},
        "avoid_windows": [], "deadline_buffer_hours": 24, "adjustment_mode": "balanced",
    })
    assert saved.status_code == 200, saved.text

    async def should_not_call(candidates, preferences=None):
        raise AssertionError("the only supported observation repeats a confirmed preference")
    monkeypatch.setattr(assistant_ai, "select_growth_insights", should_not_call)

    result = client.post("/api/growth/insights/analyze")

    assert result.status_code == 200
    assert result.json()["status"] == "no_new_suggestion"
    assert client.get("/api/growth/insights").json()["insights"] == []

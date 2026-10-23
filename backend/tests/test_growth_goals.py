from fastapi.testclient import TestClient


def test_growth_goals_are_persisted_and_versioned(client: TestClient) -> None:
    initial = client.get("/api/goals")
    assert initial.status_code == 200
    assert initial.json() == {"direction": "", "direction_version": 1, "revision": 0, "goals": []}

    created = client.post(
        "/api/goals",
        json={
            "title": "每周阅读三篇论文",
            "motivation": "为科研方向做准备",
            "priority": 1,
            "metric_kind": "count",
            "weekly_target": 3,
            "unit_label": "篇",
            "due_date": "2027-06-01",
        },
    )
    assert created.status_code == 201
    goal = created.json()
    assert goal["goal_type"] == "long_term"
    assert goal["status"] == "active"
    assert goal["version"] == 1

    changed = client.patch(f"/api/goals/{goal['id']}", json={"priority": 2})
    assert changed.status_code == 200
    assert changed.json()["version"] == 2
    assert changed.json()["priority"] == 2

    restored = client.get("/api/goals")
    assert restored.status_code == 200
    assert restored.json()["goals"][0]["version"] == 2
    assert restored.json()["revision"] == 2


def test_invalid_growth_goal_does_not_change_revision(client: TestClient) -> None:
    response = client.post(
        "/api/goals",
        json={"title": "   ", "priority": 8, "metric_kind": "score", "weekly_target": -1},
    )
    assert response.status_code == 422
    assert client.get("/api/goals").json()["revision"] == 0

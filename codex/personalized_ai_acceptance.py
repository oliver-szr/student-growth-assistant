"""Real DeepSeek acceptance against a fresh, isolated demo database."""
import json
import os
import sys
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SCENARIO = json.loads((ROOT / "codex" / "demo_scenario.json").read_text(encoding="utf-8"))
DEMO_NOW = SCENARIO["now"]
WEEK_START = date.fromisoformat(SCENARIO["week_start"])
THURSDAY = (WEEK_START + timedelta(days=3)).isoformat()
SUNDAY = (WEEK_START + timedelta(days=6)).isoformat()
sys.path.insert(0, str(BACKEND))

DEMO_DB = ROOT / "codex" / ".runtime" / f"demo-personalized-ai-{uuid.uuid4().hex}.db"
os.environ["SGA_DEMO"] = "1"
os.environ["SGA_DATABASE_PATH"] = str(DEMO_DB)
os.environ["SGA_DEMO_NOW"] = DEMO_NOW

from fastapi.testclient import TestClient
from app.main import app
from app.services.claude_client import get_claude_config


def wait_for_run(client, run_id):
    deadline = time.monotonic() + 270
    last = None
    previous_state = None
    while time.monotonic() < deadline:
        last = client.get(f"/api/assistant/runs/{run_id}").json()
        state = (last["status"], last["phase"])
        if state != previous_state:
            print(json.dumps({"run": run_id, "status": last["status"], "phase": last["phase"]}, ensure_ascii=False), flush=True)
            previous_state = state
        if last["status"] != "running":
            return last
        time.sleep(0.5)
    raise TimeoutError(f"AI run {run_id} exceeded the 270 second acceptance limit")


def submit(client, session_id, text, label):
    response = client.post(
        f"/api/assistant/sessions/{session_id}/runs",
        json={"client_message_id": f"live-{label}-{uuid.uuid4()}", "text": text},
    )
    response.raise_for_status()
    run = wait_for_run(client, response.json()["id"])
    if run["status"] != "completed":
        raise AssertionError(f"{label} run did not complete: {run}")
    return client.get(f"/api/assistant/sessions/{session_id}").json()["proposal"]


def main():
    config = get_claude_config()
    if config.api_format != "openai" or not config.base_url.startswith("https://api.deepseek.com"):
        raise RuntimeError("Live acceptance is restricted to the configured official DeepSeek OpenAI-compatible endpoint")
    result = {"mode": "real_ai", "provider": "DeepSeek official OpenAI-compatible API", "model": config.model,
              "clock": DEMO_NOW, "week_start": SCENARIO["week_start"], "cases": []}
    app.state.db_engine.dispose()
    try:
        with TestClient(app) as client:
            course = client.post("/api/time-rules", json={"kind": "course", "title": "验收示例课程", "recurrence": "once",
                "weekday": None, "date": THURSDAY, "start_time": "14:00", "end_time": "16:00"})
            course.raise_for_status()
            old_task = client.post("/api/tasks", json={"title": "文献阅读", "duration_minutes": 60,
                "deadline": f"{SUNDAY}T22:00:00+08:00", "priority": "low"})
            old_task.raise_for_status()
            session_id = client.post("/api/assistant/sessions", json={}).json()["id"]
            initial = client.get(f"/api/assistant/sessions/{session_id}").json()
            assert initial["settings"]["demo"] is True
            assert initial["courses"] and initial["tasks"]
            result["seeded_course_count"] = len(initial["courses"])
            result["seeded_task_count"] = len(initial["tasks"])

            proposal = submit(client, session_id,
                "新增写作任务‘偏好验收报告’，预计60分钟，周日20:00前交，普通重要程度。以后写作尽量安排在上午8点到中午12点之间，请把这条写作偏好记住，并重新安排本周任务。",
                "long-term-writing")
            result["cases"].append({"name": "任务理解与长期偏好提议", "status": proposal["status"],
                "recommendation_source": (proposal.get("recommendation") or {}).get("source"),
                "candidate_count": len(proposal.get("candidate_options", [])),
                "task_types": [t.get("task_type") for t in proposal.get("tasks", [])],
                "preference_update_staged": bool(proposal.get("preference_updates"))})
            assert proposal["status"] == "ready", proposal.get("questions")
            assert proposal.get("recommendation", {}).get("source") == "ai", proposal.get("recommendation_error")
            assert proposal.get("preference_updates"), "The model did not stage the explicit long-term preference"
            assert any(t["title"] == "偏好验收报告" and t["task_type"] == "writing" for t in proposal["tasks"])
            assert client.get("/api/assistant/preferences").json()["is_sample"] is True
            report = next(t for t in proposal["tasks"] if t["title"] == "偏好验收报告")
            report_item = next(x for x in proposal["items"] if x["ref"] == report["ref"])
            assert report_item["start_at"][11:13] in {"08", "09", "10", "11"}, report_item
            result["cases"][-1]["report_start"] = report_item["start_at"]

            followup = submit(client, session_id,
                "把刚才新增的‘偏好验收报告’预计时长从60分钟改为90分钟，周日20:00截止不变；保留刚才提出的长期写作偏好和当前安排要求。",
                "follow-up-edit")
            result["cases"].append({"name": "引用当前候选继续修改", "status": followup["status"],
                "recommendation_source": (followup.get("recommendation") or {}).get("source"),
                "staged_preference_preserved": bool(followup.get("preference_updates")),
                "temporary_window_count": len((followup.get("temporary_preferences") or {}).get("blocked_windows", []))})
            assert followup["status"] == "ready", followup.get("questions")
            assert followup.get("recommendation", {}).get("source") == "ai"
            assert followup.get("preference_updates"), "The follow-up unexpectedly dropped the staged long-term preference"
            report = next(t for t in followup["tasks"] if t["title"] == "偏好验收报告")
            assert report["duration_minutes"] == 90, report
            assert client.get("/api/assistant/preferences").json()["is_sample"] is True

            applied = client.post(f"/api/assistant/proposals/{followup['id']}/confirm")
            applied.raise_for_status()
            saved_preferences = client.get("/api/assistant/preferences").json()
            assert saved_preferences["is_sample"] is False
            assert saved_preferences["task_windows"]["writing"][0]["start"] == "08:00"
            assert any(t["title"] == "偏好验收报告" for t in client.get("/api/tasks").json())
            result["confirmed_task_and_preference_persisted"] = True

            temporary = submit(client, session_id, "今天晚上不学习，请按这个临时要求重新安排本周任务。", "temporary-evening")
            result["cases"].append({"name": "临时要求与再次规划", "status": temporary["status"],
                "recommendation_source": (temporary.get("recommendation") or {}).get("source"),
                "temporary_window_count": len((temporary.get("temporary_preferences") or {}).get("blocked_windows", [])),
                "long_term_preferences_unchanged": client.get("/api/assistant/preferences").json() == saved_preferences})
            assert temporary["status"] == "ready", temporary.get("questions")
            assert temporary.get("recommendation", {}).get("source") == "ai"
            blocks = temporary["temporary_preferences"]["blocked_windows"]
            assert blocks, "The model did not represent the dated temporary restriction"
            for item in temporary["items"]:
                assert all(not (item["start_at"] < b["end_at"] and item["end_at"] > b["start_at"]) for b in blocks), item
            assert client.get("/api/assistant/preferences").json() == saved_preferences
            result["passed"] = True
    except Exception as exc:
        result["passed"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if app.state.db_engine:
            app.state.db_engine.dispose()
        evidence = ROOT / "codex" / "evidence"
        evidence.mkdir(exist_ok=True)
        path = evidence / f"personalized-ai-{uuid.uuid4().hex}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        for extra in (DEMO_DB, Path(str(DEMO_DB) + "-wal"), Path(str(DEMO_DB) + "-shm")):
            extra.unlink(missing_ok=True)
        print(json.dumps({"evidence": str(path.relative_to(ROOT)), "passed": result.get("passed"),
                          "model": result["model"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

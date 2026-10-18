"""Explicit isolated Mock-AI demo server and HTTP integration acceptance.

Normal app startup never imports this tool. --serve always creates a new named
demo DB; --verify refuses non-loopback URLs and nonempty task databases.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-10-14T18:00:00+08:00"


async def mock_breakdown(request, now):
    return {"parent": {"title": request["title"], "deadline": request["deadline"], "description": "匿名Mock演示"},
            "children": [{"title": title, "duration_minutes": 60, "deadline": request["deadline"], "sort_order": i}
                         for i, title in enumerate(("需求分析", "实现与验证"))]}


def serve(port):
    database = ROOT/"scripts/.runtime"/f"demo-integration-{uuid4().hex}.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    os.environ.update(SGA_DEMO="1", SGA_DEMO_NOW=NOW, SGA_DATABASE_PATH=str(database),
                      SGA_AUTO_BACKUP="0", SGA_SKIP_IMPORT_BACKUP="1")
    for key in ("CLAUDE_API_KEY", "CLAUDE_MODEL", "OPENAI_API_KEY", "OPENAI_MODEL"):
        os.environ.pop(key, None)
    sys.path.insert(0, str(ROOT/"backend"))
    from app.services import assistant_ai, claude_client, constraint_parser, growth_insights, plan_explanation
    claude_client.load_dotenv = lambda *a, **k: None

    async def reject_live(*args, **kwargs):
        raise AssertionError("Live AI is forbidden in this isolated integration demo")

    for module in (assistant_ai, claude_client, constraint_parser, plan_explanation):
        module.request_claude = reject_live
    assistant_ai.decompose_task = mock_breakdown
    growth_insights.launch_automatic_analysis = lambda *a, **k: None
    from app.main import app

    @app.middleware("http")
    async def mark_isolated_mock(request, call_next):
        response = await call_next(request)
        response.headers["X-SGA-Integration-Mock"] = "1"
        return response

    import uvicorn
    print("ISOLATED MOCK AI ONLY; new demo DB; normal startup is unchanged", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port)


def exercise(api):
    """Same API chain usable from an HTTP client or isolated TestClient."""
    def call(method, path, **kwargs):
        response = api.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    settings = call("GET", "/api/assistant/settings")
    if not settings["demo"] or settings["now"] != NOW or call("GET", "/api/tasks") != []:
        raise RuntimeError("Requires a fresh empty isolated integration demo, never normal/user data")
    assert call("GET", "/api/health")["status"] == "ok"
    goal = call("POST", "/api/goals", json={"title": "匿名课程交付", "metric_kind": "count", "weekly_target": 2})
    base = "/api/tasks/breakdown-drafts"
    draft = call("POST", base, json={"client_request_id": uuid4().hex, "source": "ai", "text": "匿名课程项目",
                 "title": "Software Engineering Project", "deadline": "2026-10-25T20:00:00+08:00", "expected_duration_minutes": 120, "goal_id": goal["id"]})
    content = deepcopy(draft["content"])
    content["children"][0]["duration_minutes"] = 45
    content["children"][0]["deadline"] = "2026-10-24T18:00:00+08:00"
    content["children"].reverse()
    for index, child in enumerate(content["children"]):
        child["sort_order"] = index
    draft = call("PATCH", f"{base}/{draft['id']}", json={"version": draft["version"], "content": content})
    assert call("GET", "/api/tasks") == [], "An AI draft must not create formal tasks"
    confirmed = call("POST", f"{base}/{draft['id']}/confirm", json={"version": draft["version"]})
    repeated = call("POST", f"{base}/{draft['id']}/confirm", json={"version": draft["version"]})
    assert confirmed["created_task_ids"] == repeated["created_task_ids"]
    tasks = call("GET", "/api/tasks")
    parent = next(t for t in tasks if t["task_kind"] == "container")
    children = [t for t in tasks if t["parent_task_id"] == parent["id"]]
    assert len(children) == 2
    assert [c["title"] for c in sorted(children, key=lambda c: c["sort_order"])] == ["实现与验证", "需求分析"]
    assert next(c for c in children if c["title"] == "需求分析")["duration_minutes"] == 45
    sid = call("POST", "/api/assistant/sessions", json={})["id"]
    def replan(actions=None):
        return call("POST", f"/api/assistant/sessions/{sid}/messages", json={"client_message_id": uuid4().hex,
                    "text": "匿名程序排程", "replan": True, "actions": actions or []})
    proposal = replan([{"op": "update", "target": f"task:{c['id']}", "fields": {"profile": {"allowed_windows": [
        {"start_at": "2026-10-15T08:00:00+08:00", "end_at": "2026-10-15T12:00:00+08:00"}]}}} for c in children])
    assert proposal["status"] == "ready" and len(proposal["items"]) == 2
    assert f"task:{parent['id']}" not in {x["ref"] for x in proposal["items"]}
    call("POST", f"/api/assistant/proposals/{proposal['id']}/confirm")
    before = call("GET", f"/api/assistant/sessions/{sid}")["confirmed_items"]
    pending = replan()
    assert pending["status"] == "ready"
    first = min(proposal["items"], key=lambda x: x["start_at"])
    from datetime import datetime, timedelta
    start = datetime.fromisoformat(first["start_at"])
    rule = call("POST", "/api/time-rules", json={"title": "匿名临时课程", "kind": "course", "recurrence": "once",
                "date": start.date().isoformat(), "start_time": start.strftime("%H:%M"), "end_time": (start+timedelta(minutes=15)).strftime("%H:%M")})
    stale = api.request("POST", f"/api/assistant/proposals/{pending['id']}/confirm")
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "STALE_CANDIDATE"
    assert call("GET", f"/api/assistant/sessions/{sid}")["confirmed_items"] == before
    repaired = replan()
    assert repaired["status"] == "ready" and repaired["replanning"]["mode"] == "local"
    assert repaired["selected_metrics"]["moved_task_count"] == 1
    assert any(d.get("time_rule_id") == rule["id"] for d in repaired["diagnostics"])
    unaffected = [item for item in before if item["ref"] != first["ref"]]
    assert unaffected and all(item in repaired["items"] for item in unaffected)
    call("POST", f"/api/assistant/proposals/{repaired['id']}/confirm")
    official = call("GET", f"/api/assistant/sessions/{sid}")["confirmed_items"]
    assert official == repaired["items"] and all(item in official for item in unaffected)
    call("POST", f"/api/tasks/{children[0]['id']}/feedback", json={"client_action_id": uuid4().hex, "outcome": "completed",
         "actual_minutes": 40, "occurred_at": NOW, "completed_at": NOW})
    stats = call("GET", "/api/growth/statistics?weeks=4")
    assert stats["overview"]["completed_count"] == 1 and stats["overview"]["actual_minutes"] == 40
    parent = next(t for t in call("GET", "/api/tasks") if t["id"] == parent["id"])
    assert parent["progress"]["completed_children"] == 1 and parent["progress"]["total_children"] == 2
    assert call("GET", "/api/profile/context")["goals"]
    call("GET", "/api/review/context")
    return dict(mode="anonymous_HTTP_integration_with_Mock_AI", checks=["health", "duration_deadline_order_edit_no_formal_write", "idempotent_hierarchy_confirmation",
                "child_only_candidates", "two_week_confirmation", "new_course_local_repair_one_move", "conflict_explanation", "formal_persistence",
                "stale_candidate_rejected_no_formal_write", "unaffected_items_preserved", "child_feedback", "growth_statistics", "parent_progress_1_of_2", "profile_and_review"],
                parent_id=parent["id"], child_ids=[c["id"] for c in children], known_actual_minutes=40)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--serve", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--api", default="http://127.0.0.1:8001")
    parser.add_argument("--output", type=Path, default=ROOT/"scripts/.local/integration-demo.json")
    args = parser.parse_args()
    if args.serve:
        serve(args.port)
    else:
        target = urlsplit(args.api)
        if target.scheme != "http" or target.hostname not in ("127.0.0.1", "localhost", "::1") or target.username or target.password:
            parser.error("Only a local anonymous demo HTTP endpoint is allowed")
        import httpx
        with httpx.Client(base_url=args.api, timeout=125, trust_env=False) as api:
            marker = api.get("/api/health")
            marker.raise_for_status()
            if marker.headers.get("X-SGA-Integration-Mock") != "1":
                raise RuntimeError("Verification requires this tool's explicitly mocked server; no writes were sent")
            report = exercise(api)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

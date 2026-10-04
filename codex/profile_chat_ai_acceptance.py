"""Live DeepSeek acceptance for clarification, profile drafts and confirmation."""
import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
SCENARIO = json.loads((ROOT / "codex" / "demo_scenario.json").read_text(encoding="utf-8"))
DATABASE = ROOT / "codex" / ".runtime" / f"demo-profile-ai-{uuid.uuid4().hex}.db"
EVIDENCE = ROOT / "codex" / "evidence"


def wait_run(client, run_id, timeout=270):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/assistant/runs/{run_id}")
        response.raise_for_status()
        run = response.json()
        if run["status"] != "running":
            return run
        time.sleep(0.5)
    raise TimeoutError("档案 AI 运行超时。")


def send(client, session_id, text, report):
    response = client.post(f"/api/assistant/sessions/{session_id}/runs", json={
        "client_message_id": str(uuid.uuid4()), "text": text,
    })
    response.raise_for_status()
    run = wait_run(client, response.json()["id"])
    report["runs"].append({"status": run["status"], "phase": run["phase"], "error_code": run.get("error_code")})
    if run["status"] != "completed":
        raise RuntimeError(f"档案助手运行失败：{run.get('error_code') or run['status']}")
    session = client.get(f"/api/assistant/sessions/{session_id}")
    session.raise_for_status()
    return session.json()


def main():
    EVIDENCE.mkdir(exist_ok=True)
    if DATABASE.exists():
        raise RuntimeError("拒绝覆盖已有演示数据库。")
    os.environ["SGA_DEMO"] = "1"
    os.environ["SGA_AUTO_BACKUP"] = "0"
    os.environ["SGA_DEMO_NOW"] = SCENARIO["now"]
    os.environ["SGA_DATABASE_PATH"] = str(DATABASE)
    sys.path.insert(0, str(ROOT / "backend"))
    from app.services.claude_client import get_claude_config
    from app.main import app

    config = get_claude_config()
    host = urlsplit(config.base_url).hostname
    if config.api_format != "openai" or host != "api.deepseek.com":
        raise RuntimeError("真实档案 AI 验收只允许使用已配置的 DeepSeek 官方 OpenAI 兼容接口。")

    report = {
        "mode": "real_ai_profile_chat",
        "provider": host,
        "model": config.model,
        "week_start": SCENARIO["week_start"],
        "simulated_now": SCENARIO["now"],
        "runs": [],
        "passed": False,
    }
    initialize_example_database(DATABASE)
    try:
        with TestClient(app) as client:
            settings = client.get("/api/assistant/settings").json()
            assert settings["demo"] and settings["now"] == SCENARIO["now"], settings
            session_id = client.post("/api/assistant/sessions/open", json={"scope": "profile"}).json()["id"]

            first = send(client, session_id,
                "新增一个任务类别‘编程’，编程尽量安排在下午；再新增一个‘完成个人项目原型’长期目标。",
                report)
            first_draft = first.get("draft")
            # A model may defer all changes until clarification, or propose only
            # the fully specified category. Both preserve the user-confirm gate.
            if first_draft:
                assert all(item["op"] == "create_category" for item in first_draft["operations"]), first_draft
            assert first["messages"][-1].get("content", {}).get("questions"), first
            assert not any(item["name"] == "编程" for item in client.get('/api/task-categories').json()['categories'])
            assert first["messages"] and first["messages"][-1]["role"] == "assistant", first["messages"]
            report["clarification_requested"] = True

            second = send(client, session_id,
                "下午按13:00到17:00。目标名称保持‘完成个人项目原型’，每周交付1个可演示原型版本，按明确交付衡量；动机是推进课程项目。",
                report)
            draft = second["draft"]
            assert draft and not draft.get("questions"), second
            operations = draft["operations"]
            kinds = {operation["op"] for operation in operations}
            assert "create_category" in kinds and "create_preference_rule" in kinds and "create_goal" in kinds, operations
            report["combined_draft_operations"] = sorted(kinds)

            third = send(client, session_id,
                "只把编程偏好时段改成14:00到18:00，目标名称和衡量方式保持不变。",
                report)
            corrected = third["draft"]
            assert corrected and corrected["id"] != draft["id"], third.get("draft")
            corrected_rules = [item for item in corrected["operations"] if item["op"] == "create_preference_rule"]
            assert corrected_rules, corrected["operations"]
            assert corrected_rules[-1]["parameters"] == {"start": "14:00", "end": "18:00"}, corrected_rules[-1]
            assert any(item["op"] == "create_goal" for item in corrected["operations"]), corrected["operations"]
            assert sum(item["op"] == "create_category" for item in corrected["operations"]) == 1, corrected["operations"]
            report["continued_draft_replaced_without_duplicate_category"] = True

            saved = client.post(f"/api/assistant/drafts/{corrected['id']}/confirm")
            saved.raise_for_status()
            categories = client.get("/api/task-categories").json()["categories"]
            rules = client.get("/api/assistant/preference-rules").json()["rules"]
            goals = client.get("/api/goals").json()["goals"]
            category = next(item for item in categories if item["name"] == "编程")
            rule = next(item for item in rules if item["category_key"] == category["key"])
            goal = next(item for item in goals if item["title"] == "完成个人项目原型")
            assert rule["parameters"] == {"start": "14:00", "end": "18:00"}, rule
            assert goal["weekly_target"] == 1 and goal["metric_kind"] == "deliverable", goal
            report.update({"passed": True, "confirmed_category_key": category["key"], "confirmed_preference": rule["parameters"], "confirmed_goal_id": goal["id"]})
    finally:
        engine = getattr(app.state, "db_engine", None)
        if engine is not None:
            engine.dispose()
        path = EVIDENCE / f"profile-chat-ai-{DATABASE.stem}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "provider": host, "model": config.model, "evidence": str(path.relative_to(ROOT))}, ensure_ascii=False))


def initialize_example_database(path):
    sys.path.insert(0, str(ROOT / "codex"))
    from demo_init import example_source, initialize
    initialize(path, source=example_source())


if __name__ == "__main__":
    main()

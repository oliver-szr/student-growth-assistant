"""Run isolated real-DeepSeek browser acceptance without touching the user's app."""
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
SCENARIO = json.loads((ROOT / "codex" / "demo_scenario.json").read_text(encoding="utf-8"))
DEMO_NOW = SCENARIO["now"]
WEEK_START = SCENARIO["week_start"]
DISPLAY_NOW = datetime.fromisoformat(DEMO_NOW).strftime("%Y-%m-%d %H:%M")
RUN_ID = uuid.uuid4().hex
DB = ROOT / "codex" / ".runtime" / f"demo-personalized-ui-{RUN_ID}.db"
EVIDENCE = ROOT / "codex" / "evidence"
API = "http://127.0.0.1:8003"
WEB = "http://127.0.0.1:5187"


def ready(url, proc, label, timeout=35):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if proc.poll() is not None:
            raise RuntimeError(f"{label} exited early with code {proc.returncode}")
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        time.sleep(0.25)
    raise TimeoutError(f"{label} did not start in time")


def get_json(url):
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    if DB.exists():
        raise RuntimeError("Refusing to overwrite an existing isolated UI database")
    DB.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(exist_ok=True)
    report = {"mode": "real_ai_browser", "model": "deepseek-v4-pro", "passed": False}
    env = os.environ.copy()
    env.update({"SGA_DEMO": "1", "SGA_DATABASE_PATH": str(DB), "SGA_DEMO_NOW": DEMO_NOW})
    seeded = subprocess.run(
        [str(ROOT / ".venv" / "Scripts" / "python.exe"), str(ROOT / "codex" / "demo_init.py"), "--database", str(DB)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=45,
    )
    if seeded.returncode:
        raise RuntimeError(f"Could not initialize isolated synthetic demo data: {seeded.stderr[-1200:]}")
    report["synthetic_demo_data_initialized"] = True
    api_proc = web_proc = None
    api_log_path = EVIDENCE / f"personalized-ui-{RUN_ID}-api.log"
    web_log_path = EVIDENCE / f"personalized-ui-{RUN_ID}-web.log"
    api_log = api_log_path.open("w", encoding="utf-8")
    web_log = web_log_path.open("w", encoding="utf-8")
    page = None
    failure = None
    try:
        api_proc = subprocess.Popen([str(ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8003"], cwd=BACKEND, env=env, stdout=api_log, stderr=subprocess.STDOUT)
        frontend_env = env.copy()
        frontend_env["VITE_API_BASE_URL"] = API
        npm = "npm.cmd" if os.name == "nt" else "npm"
        web_proc = subprocess.Popen(["node", str(FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"), "--host", "127.0.0.1", "--port", "5187", "--strictPort"], cwd=FRONTEND, env=frontend_env, stdout=web_log, stderr=subprocess.STDOUT)
        ready(API + "/api/assistant/settings", api_proc, "isolated API")
        ready(WEB, web_proc, "isolated web app")
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            context = browser.new_context(locale="zh-CN", timezone_id="America/Los_Angeles", viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("requestfailed", lambda r: errors.append(f"request failed {r.url}: {r.failure}"))
            page.goto(WEB)
            expect(page.get_by_role("heading", name="一起调整这一周")).to_be_visible(timeout=20000)
            expect(page.get_by_text(f"{DISPLAY_NOW} 北京时间")).to_be_visible()
            page.screenshot(path=str(EVIDENCE / f"personalized-ui-{RUN_ID}-initial.png"), full_page=True)
            deadline_day = int(WEEK_START[8:10]) + 6
            page.get_by_label("新增任务或调整要求", exact=True).fill(f"新增写作任务‘浏览器验收报告’，预计60分钟，{WEEK_START[:4]}年{int(WEEK_START[5:7])}月{deadline_day}日20:00前交，普通重要程度。以后写作尽量安排在上午8点到中午12点之间，请记住这条偏好并重新安排本周任务。")
            page.get_by_role("button", name="发送", exact=True).click()
            expect(page.get_by_role("button", name="采用方案", exact=True)).to_be_enabled(timeout=270000)
            settings = get_json(API + "/api/assistant/settings")
            session_id = page.evaluate("workspace => localStorage.getItem(`sga-assistant-session:${workspace.workspace_id}:${workspace.week_start}`)", settings)
            session = get_json(f"{API}/api/assistant/sessions/{session_id}")
            proposal = session["proposal"]
            assert proposal["status"] == "ready", proposal["status"]
            assert proposal["recommendation"]["source"] == "ai", proposal.get("recommendation")
            assert proposal["preference_updates"], "Expected the AI to stage a long-term preference"
            assert len(proposal["candidate_options"]) >= 2, "Expected multiple verified candidates"
            report.update({"session_id": session_id, "candidate_count": len(proposal["candidate_options"]), "recommendation_source": proposal["recommendation"]["source"], "preference_staged": True})
            choices = page.locator(".candidate-option")
            choices.nth(1).click()
            expect(page.get_by_role("heading", name="当前选择方案")).to_be_visible(timeout=15000)
            page.get_by_role("button", name="采用方案", exact=True).click()
            expect(page.get_by_role("heading", name="已采用方案")).to_be_visible(timeout=15000)
            page.reload()
            expect(page.get_by_role("heading", name="已采用方案")).to_be_visible(timeout=20000)
            final_state = get_json(f"{API}/api/assistant/sessions/{session_id}")
            prefs = get_json(API + "/api/assistant/preferences")
            assert any(t["title"] == "浏览器验收报告" for t in final_state["tasks"])
            assert not prefs.get("is_sample", False), "Confirmed preference should replace the sample setting"
            assert not errors, errors
            page.screenshot(path=str(EVIDENCE / f"personalized-ui-{RUN_ID}-confirmed.png"), full_page=True)
            page.get_by_role("button", name="我的资料", exact=True).click()
            expect(page.get_by_role("heading", name="我的档案")).to_be_visible(timeout=15000)
            expect(page.get_by_role("heading", name="安排偏好")).to_be_visible(timeout=15000)
            expect(page.get_by_role("heading", name="长期目标")).to_be_visible(timeout=15000)
            page.get_by_role("button", name="复盘", exact=True).click()
            expect(page.get_by_role("heading", name="复盘")).to_be_visible(timeout=15000)
            page.get_by_role("button", name="分析我的记录", exact=True).click()
            expect(page.get_by_text("练习尽量安排在下午", exact=False)).to_be_visible(timeout=180000)
            page.screenshot(path=str(EVIDENCE / f"personalized-ui-{RUN_ID}-insight-draft.png"), full_page=True)
            page.get_by_role("button", name="确认采用", exact=True).click()
            expect(page.get_by_text("建议已采用并保存为长期偏好。", exact=True)).to_be_visible(timeout=15000)
            profile = get_json(API + "/api/growth/profile")
            assert profile["preferences"]["task_windows"]["practice"] == [{"start": "12:00", "end": "18:00"}]

            page.get_by_role("button", name="生成本周复盘", exact=True).click()
            expect(page.get_by_text(f"{WEEK_START} 这一周 · 复盘 v1", exact=True)).to_be_visible(timeout=180000)
            reviews = get_json(API + f"/api/growth/reviews?week_start={WEEK_START}")["reviews"]
            assert reviews and reviews[0]["summary_mode"] == "ai", reviews
            assert reviews[0]["facts"]["completed_count"] >= 1, reviews[0]["facts"]
            page.screenshot(path=str(EVIDENCE / f"personalized-ui-{RUN_ID}-growth-review.png"), full_page=True)
            assert not errors, errors
            screenshots = [
                f"codex/evidence/personalized-ui-{RUN_ID}-initial.png",
                f"codex/evidence/personalized-ui-{RUN_ID}-confirmed.png",
                f"codex/evidence/personalized-ui-{RUN_ID}-insight-draft.png",
                f"codex/evidence/personalized-ui-{RUN_ID}-growth-review.png",
            ]
            report.update({"passed": True, "confirmed_task_persisted": True, "confirmed_preference_persisted": True,
                "real_ai_habit_draft_created": True, "habit_preference_saved_after_user_confirmation": True,
                "real_ai_weekly_review": True, "review_week_start": reviews[0]["week_start"],
                "review_completed_tasks": reviews[0]["facts"]["completed_count"],
                "runtime_errors": errors, "screenshots": screenshots})
            browser.close()
    except Exception as e:
        failure = e
        report["error"] = str(e)
        if page:
            try:
                page.screenshot(path=str(EVIDENCE / f"personalized-ui-{RUN_ID}-failure.png"), full_page=True)
            except Exception:
                pass
    finally:
        for proc in (web_proc, api_proc):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
        api_log.close()
        web_log.close()
        # Keep the uniquely named temporary database as recoverable evidence;
        # Windows may keep SQLite handles briefly while child processes exit.
    report["server_logs"] = [str(api_log_path.relative_to(ROOT)), str(web_log_path.relative_to(ROOT))]
    path = EVIDENCE / f"personalized-ui-{RUN_ID}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"evidence": str(path.relative_to(ROOT)), **report}, ensure_ascii=False), flush=True)
    if failure:
        raise RuntimeError("Personalized browser acceptance failed; see the saved evidence report.") from failure
    if not report["passed"]:
        raise RuntimeError("Personalized browser acceptance failed")


if __name__ == "__main__":
    main()

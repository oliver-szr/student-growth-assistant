"""Read-only browser acceptance for the three-page UI annotations."""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


ROOT = Path(__file__).resolve().parents[1]
SCENARIO = json.loads((ROOT / "codex" / "demo_scenario.json").read_text(encoding="utf-8"))
URL = "http://localhost:5175/"
OUT = ROOT / "codex" / "evidence"


def main():
    OUT.mkdir(exist_ok=True)
    failures = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(locale="zh-CN", timezone_id="America/Los_Angeles", viewport={"width": 1373, "height": 1163})
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.goto(URL, wait_until="networkidle")
        expect(page.get_by_role("button", name="规划", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="复盘", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="我的档案", exact=True)).to_be_visible()
        expect(page.get_by_text(f"{SCENARIO['week_start']}  至  ", exact=False)).to_be_visible()
        expect(page.get_by_text("2026-10-14 18:00", exact=False)).to_be_visible()
        expect(page.get_by_role("heading", name="规划助手", exact=True)).to_be_visible()

        calendar = page.locator(".week-scroll")
        calendar_metrics = calendar.evaluate("element => ({overflowY:getComputedStyle(element).overflowY, scrollHeight:element.scrollHeight, clientHeight:element.clientHeight, hours:[...element.querySelectorAll('.hours span')].map(node=>node.textContent.trim())})")
        assert "22:00" in calendar_metrics["hours"], calendar_metrics
        assert calendar_metrics["overflowY"] == "hidden", calendar_metrics
        assert calendar_metrics["scrollHeight"] <= calendar_metrics["clientHeight"] + 1, calendar_metrics
        page.screenshot(path=str(OUT / "ui-annotations-planning.png"), full_page=True)

        page.get_by_role("button", name="复盘", exact=True).click()
        expect(page.get_by_role("heading", name="复盘", exact=True)).to_be_visible()
        review_order = page.locator(".growth-page").evaluate("root => ['.growth-page-heading','.workspace-chat','.growth-section'].map(selector=>Array.from(root.children).findIndex(el=>el.matches(selector)))")
        assert review_order[0] < review_order[1] < review_order[2], review_order

        page.get_by_role("button", name="我的档案", exact=True).click()
        expect(page.get_by_role("heading", name="我的档案", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="档案", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="安排偏好", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="长期目标", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="任务类别与目标关联", exact=True)).to_be_visible()
        assert page.get_by_label("个人成长方向").count() == 0
        profile_order = page.locator(".profile-page").evaluate("root => ['.growth-page-heading','.workspace-chat','.growth-section','.growth-section','.growth-section','.course-settings'].map(selector=>Array.from(root.children).findIndex(el=>el.matches(selector)))")
        assert profile_order == sorted(profile_order), profile_order
        expect(page.get_by_text("无法连接后端，请检查后端服务是否正在运行。", exact=True)).to_have_count(0)
        page.screenshot(path=str(OUT / "ui-annotations-profile.png"), full_page=True)

        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.get_by_role("heading", name="我的档案", exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not page_errors, page_errors
        browser.close()

    report = {
        "passed": True,
        "week_start": SCENARIO["week_start"],
        "simulated_now": SCENARIO["now"],
        "desktop_viewport": [1373, 1163],
        "mobile_viewport": [390, 844],
        "calendar": calendar_metrics,
        "screenshots": ["codex/evidence/ui-annotations-planning.png", "codex/evidence/ui-annotations-profile.png"],
    }
    (OUT / "ui-annotation-acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Read-only browser verification for the three annotated UI adjustments."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]

def main():
    target = ROOT / 'codex' / '.local'
    target.mkdir(exist_ok=True)
    report = {'checks': [], 'errors': []}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1161, 'height': 1163}, locale='zh-CN')
        page.on('pageerror', lambda error: report['errors'].append(str(error)))
        page.goto('http://localhost:5175/', wait_until='networkidle')
        header = page.get_by_role('heading', name='规划', exact=True)
        expect(header).to_be_visible()
        planning_style = header.evaluate('(e)=>({size:getComputedStyle(e).fontSize,color:getComputedStyle(e).color,spacing:getComputedStyle(e).letterSpacing})')
        for width, height in ((1161,1163), (1373,1163), (390,844)):
            page.set_viewport_size({'width':width,'height':height})
            if width < 850:
                page.get_by_role('button',name='周日程',exact=True).click()
            calendar = page.locator('.week-scroll')
            expect(calendar).to_be_visible()
            assert calendar.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1 && e.scrollHeight<=e.clientHeight+1')
            assert page.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth+1')
            assert calendar.locator('.day-column').count()==7
            bounds = calendar.bounding_box()
            for day in calendar.locator('.day-column').all():
                rect = day.bounding_box()
                assert rect['x'] >= bounds['x']-1 and rect['x']+rect['width'] <= bounds['x']+bounds['width']+1
            expect(calendar.get_by_text('22:00', exact=True)).to_be_visible()
            group = page.get_by_role('group',name='选择日程周',exact=True)
            expect(group.get_by_role('button',name='上一周',exact=True)).to_be_disabled()
            group.get_by_role('button',name='下一周',exact=True).click()
            expect(group.get_by_role('button',name='下一周',exact=True)).to_be_disabled()
            expect(group.locator('.week-switch-range')).to_have_text('10.19–10.25')
            expect(calendar.locator('.day-heading').filter(has_text='10-19')).to_be_visible()
            group.get_by_role('button',name='上一周',exact=True).click()
            expect(group.get_by_role('button',name='上一周',exact=True)).to_be_disabled()
            expect(group.locator('.week-switch-range')).to_have_text('10.12–10.18')
            page.screenshot(path=str(target/f'calendar-ui-{width}.png'))
            report['checks'].append(f'{width}x{height}:seven_days_fit_no_horizontal_or_vertical_scroll_and_week_switch')
        page.set_viewport_size({'width':1161,'height':1163})
        page.get_by_role('button',name='手动任务卡片',exact=True).click()
        switch=page.get_by_role('switch',name='允许分段安排',exact=True)
        expect(switch).not_to_be_checked()
        switch.focus()
        switch.press('Space')
        expect(switch).to_be_checked()
        expect(page.get_by_label('每段至少分钟',exact=True)).to_be_visible()
        expect(page.get_by_label('最多分几段',exact=True)).to_be_visible()
        track=page.locator('.split-toggle-track')
        assert track.bounding_box()['width']==44
        active_color=track.evaluate('(e)=>getComputedStyle(e).backgroundColor')
        page.locator('.split-toggle').screenshot(path=str(target/'manual-split-switch.png'))
        switch.press('Space')
        expect(switch).not_to_be_checked()
        expect(page.get_by_label('每段至少分钟',exact=True)).to_have_count(0)
        assert track.evaluate('(e)=>getComputedStyle(e).backgroundColor')!=active_color
        report['checks'].append('split_switch_keyboard_visual_state_and_fields')
        for tab in ('复盘','我的档案'):
            page.get_by_role('button',name=tab,exact=True).click()
            heading = page.get_by_role('heading',name=tab,exact=True)
            expect(heading).to_be_visible()
            style = heading.evaluate('(e)=>({size:getComputedStyle(e).fontSize,color:getComputedStyle(e).color,spacing:getComputedStyle(e).letterSpacing})')
            assert style == planning_style, (tab,style,planning_style)
        report['checks'].append('three_page_heading_typography_matches')
        browser.close()
    assert not report['errors'], report['errors']
    (target/'calendar-ui-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
    main()

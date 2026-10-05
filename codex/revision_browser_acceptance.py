"""Interactive browser flow on the script-owned anonymous preview instance."""
import json,uuid
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
def main():
    api=httpx.Client(base_url='http://127.0.0.1:8002',timeout=125)
    settings=api.get('/api/assistant/settings').json()
    assert settings['demo'] and settings['grid_minutes']==5 and settings['planning_window_days']==14
    report={'mode':'manual_browser_real_database','checks':[],'errors':[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1373,'height':1163},locale='zh-CN',timezone_id='America/Los_Angeles')
        page.on('pageerror',lambda e:report['errors'].append(str(e)))
        page.goto('http://localhost:5175/',wait_until='networkidle')
        page.get_by_role('button',name='下一周',exact=True).click()
        expect(page.locator('.day-heading').filter(has_text='10-19')).to_be_visible()
        assert page.locator('.week-scroll').evaluate('(e)=>e.scrollHeight<=e.clientHeight+1')
        page.get_by_role('button',name='上一周',exact=True).click()
        page.get_by_role('button',name='手动添加',exact=True).click()
        form=page.locator('.manual-task')
        name='浏览器验证'+uuid.uuid4().hex[:6]
        form.get_by_label('名称',exact=True).fill(name)
        form.get_by_label('任务类型').select_option('writing')
        form.get_by_label('剩余时长（分钟）',exact=True).fill('75')
        form.get_by_label('截止时间',exact=True).fill('2026-10-21T12:00')
        form.get_by_label('允许分段安排',exact=True).check()
        form.get_by_role('button',name='生成候选',exact=True).click()
        adopt=page.get_by_role('button',name='采用方案',exact=True)
        expect(adopt).to_be_enabled(timeout=30000)
        assert not any(t['title']==name for t in api.get('/api/tasks').json())
        adopt.click()
        expect(page.get_by_role('heading',name='已采用方案',exact=True)).to_be_visible()
        task=next(t for t in api.get('/api/tasks').json() if t['title']==name)
        page.locator('.workspace-details>summary').click()
        card=page.locator('.task-execution-card').filter(has=page.get_by_role('heading',name=name,exact=True))
        expect(card).to_be_visible(timeout=10000)
        card.get_by_role('button',name='记录进度 / 完成',exact=True).click()
        card.get_by_label('本次结果').select_option('partial')
        card.get_by_label('实际投入（分钟，可留空）',exact=True).fill('15')
        card.get_by_label('剩余时长（分钟）',exact=True).fill('60')
        card.get_by_role('button',name='保存记录',exact=True).click()
        expect(card.get_by_text('60 分钟',exact=True)).to_be_visible()
        assert api.get(f"/api/tasks/{task['id']}/feedback").json()['entries'][0]['cumulative_actual_minutes']==15
        page.get_by_role('button',name='复盘',exact=True).click()
        expect(page.get_by_role('heading',name='复盘助手',exact=True)).to_be_visible()
        page.get_by_role('button',name='我的档案',exact=True).click()
        expect(page.get_by_role('heading',name='档案助手',exact=True)).to_be_visible()
        expect(page.get_by_role('heading',name='安排偏好',exact=True)).to_be_visible()
        # Show two real segments of one goal-linked candidate in the calendar.
        sid=api.post('/api/assistant/sessions',json={}).json()['id']
        goal=api.get('/api/goals').json()['goals'][0]
        split_name='跨周分段验证'+uuid.uuid4().hex[:6]
        fields={'title':split_name,'duration_minutes':180,'deadline':'2026-10-21T12:00:00+08:00','goal_id':goal['id'],'task_type':'writing','profile':{'splittable':True,'min_block_minutes':90,'max_segments':2,'allowed_windows':[{'start_at':'2026-10-19T08:05:00+08:00','end_at':'2026-10-19T09:35:00+08:00'},{'start_at':'2026-10-20T08:05:00+08:00','end_at':'2026-10-20T09:35:00+08:00'}]}}
        split=api.post(f'/api/assistant/sessions/{sid}/messages',json={'client_message_id':uuid.uuid4().hex,'text':'独立浏览器分段验收','actions':[{'op':'add','fields':fields}]}).json()
        assert split['status']=='ready',split.get('questions')
        assert next(t for t in split['tasks'] if t['title']==split_name)['goal']['id']==goal['id']
        page.evaluate('([key,id])=>localStorage.setItem(key,id)',[f"sga-assistant-session:{settings['workspace_id']}:{settings['week_start']}",str(sid)])
        page.reload(wait_until='networkidle')
        page.get_by_role('button',name='下一周',exact=True).click()
        blocks=page.locator('.calendar-block').filter(has_text=split_name)
        expect(blocks).to_have_count(2)
        expect(blocks.filter(has_text='第 1/2 段')).to_be_visible()
        expect(blocks.filter(has_text='第 2/2 段')).to_be_visible()
        page.get_by_role('button',name='采用方案',exact=True).click()
        expect(page.get_by_role('heading',name='已采用方案',exact=True)).to_be_visible()
        assert any(t['title']==split_name for t in api.get('/api/tasks').json())
        page.set_viewport_size({'width':390,'height':844})
        page.get_by_role('button',name='日程',exact=True).click()
        assert page.locator('.week-scroll').evaluate('(e)=>e.scrollHeight<=e.clientHeight+1')
        target=ROOT/'codex'/'.local'/'revision-browser.png'
        page.screenshot(path=str(target),full_page=True)
        browser.close()
        report['checks']=['current_next_week_switch','full_height_calendar','5_minute_manual_card','split_setting','draft_no_formal_write','confirm_persisted','task_list_refresh_without_reload','partial_feedback','three_page_aggregate','refresh','narrow_screen','non_shanghai_browser_timezone','goal_link_in_preview','split_labels_in_calendar','split_confirm_persisted']
    assert not report['errors'],report['errors']
    target=ROOT/'codex'/'.local'/'revision-browser-report.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()

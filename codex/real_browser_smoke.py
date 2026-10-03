"""A real-model browser chat/confirm/refresh flow on the isolated demo only."""
import json
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'codex/evidence'


def main():
    OUT.mkdir(exist_ok=True)
    api='http://127.0.0.1:8001'
    assert httpx.get(api+'/api/assistant/settings').json()['demo']
    count=len(httpx.get(api+'/api/tasks').json())
    result=dict(mode='real_ai_browser',model='demo-server configuration',errors=[])
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000},timezone_id='America/Los_Angeles')
        page.on('pageerror',lambda error:result['errors'].append(str(error)))
        try:
            page.goto('http://127.0.0.1:5174')
            text=page.get_by_label('新增任务或调整要求',exact=True)
            text.fill('增加演示复盘任务，预计一小时，周日20:00截止，普通重要程度，请自动安排。')
            page.get_by_role('button',name='发送',exact=True).click()
            expect(page.get_by_role('button',name='发送',exact=True)).to_be_visible(timeout=30000)
            if page.get_by_role('button',name='采用方案',exact=True).count()==0:
                result['explicit_retry']=True
                text.fill('增加演示复盘任务，预计一小时，2026年10月11日20:00截止，普通重要程度，不要求固定开始时间，请自动安排。')
                page.get_by_role('button',name='发送',exact=True).click()
            expect(page.get_by_role('button',name='采用方案',exact=True)).to_be_visible(timeout=30000)
            assert len(httpx.get(api+'/api/tasks').json())==count
            page.screenshot(path=str(OUT/'mvp-real-ai-browser-preview.png'),full_page=True)
            page.get_by_role('button',name='采用方案',exact=True).click()
            expect(page.get_by_role('heading',name='已采用方案')).to_be_visible()
            assert len(httpx.get(api+'/api/tasks').json())==count+1
            page.reload()
            expect(page.get_by_role('heading',name='已采用方案')).to_be_visible()
            assert not result['errors']
            result['passed']=True
            print('PASS real AI browser chat / candidate / confirm / refresh',flush=True)
        except Exception as exc:
            result.update(passed=False,error=str(exc));raise
        finally:
            (OUT/'real-browser-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            browser.close()


if __name__=='__main__':main()

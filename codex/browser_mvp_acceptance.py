"""Browser test with model-output fixtures, real backend/DB/scheduler/confirmation."""
import json
from datetime import date, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
SCENARIO=json.loads((ROOT/'codex'/'demo_scenario.json').read_text(encoding='utf-8'))
WEEK_START=date.fromisoformat(SCENARIO['week_start'])
WEDNESDAY=(WEEK_START+timedelta(days=2)).isoformat()
THURSDAY=(WEEK_START+timedelta(days=3)).isoformat()
FRIDAY=(WEEK_START+timedelta(days=4)).isoformat()
SUNDAY=(WEEK_START+timedelta(days=6)).isoformat()
API='http://127.0.0.1:8001'
OUT=ROOT/'codex'/'evidence'


def main():
    report={'mode':'model_output_fixtures_real_backend','cases':[],'runtime_errors':[]}
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        ctx=browser.new_context(locale='zh-CN',timezone_id='America/Los_Angeles',viewport={'width':1440,'height':1000})
        assert ctx.request.get(API+'/api/assistant/settings').json()['demo']
        latest={}; step=0
        def fixture(route):
            nonlocal latest,step
            if route.request.method!='POST':route.continue_();return
            body=route.request.post_data_json
            if 'actions' in body:route.continue_();return
            text=body['text']; step+=1
            if step==1: actions=[{'op':'add','fields':{'title':'实验报告','duration_minutes':120,'deadline':f'{FRIDAY}T20:00:00+08:00','priority':'normal','profile':{'preferred_windows':[{'start_at':f'{THURSDAY}T14:00:00+08:00','end_at':f'{THURSDAY}T18:00:00+08:00'}]}}}]
            elif step==2: actions=[{'op':'update','target':next(t['ref'] for t in latest['tasks'] if t['title']=='实验报告'),'fields':{'profile':{'fixed_start':f'{THURSDAY}T14:00:00+08:00'}}}]
            elif step==3: actions=[{'op':'update','target':next(t['ref'] for t in latest['tasks'] if t['title']=='实验报告'),'fields':{'profile':{'fixed_start':f'{THURSDAY}T19:00:00+08:00'}}}]
            elif step==4: actions=[{'op':'add','fields':{'title':'汇报稿','duration_minutes':60,'deadline':f'{THURSDAY}T12:00:00+08:00','priority':'high'}}]
            elif step==5: actions=[{'op':'update','target':next(t['ref'] for t in latest['tasks'] if t['title']=='实验报告'),'fields':{'profile':{'fixed_start':f'{WEDNESDAY}T19:00:00+08:00'}}},{'op':'update','target':next(t['ref'] for t in latest['tasks'] if t['title']=='汇报稿'),'fields':{'profile':{'allowed_windows':[{'start_at':f'{THURSDAY}T08:00:00+08:00','end_at':f'{THURSDAY}T12:00:00+08:00'}]}}}]
            else: actions=[{'op':'add','fields':{'title':'超大任务','duration_minutes':900,'deadline':f'{THURSDAY}T12:00:00+08:00'}}]
            body['actions']=actions
            response=route.fetch(post_data=json.dumps(body))
            latest=response.json();route.fulfill(response=response)
        ctx.route('**/api/assistant/sessions/*/messages',fixture)
        page=ctx.new_page();page.on('pageerror',lambda e:report['runtime_errors'].append(str(e)))
        def passed(name):report['cases'].append({'name':name,'passed':True});print('PASS',name,flush=True)
        def send(text,status):
            page.get_by_label('新增任务或调整要求',exact=True).fill(text)
            page.get_by_role('button',name='发送',exact=True).click()
            expect(page.get_by_role('button',name='发送',exact=True)).to_be_visible(timeout=15000)
            expect(page.get_by_label('新增任务或调整要求',exact=True)).to_have_value('')
            assert latest['status']==status,latest
        try:
            page.goto('http://127.0.0.1:5174');page.wait_for_load_state('networkidle')
            expect(page.get_by_role('heading',name='一起调整这一周')).to_be_visible()
            display_now=__import__('datetime').datetime.fromisoformat(SCENARIO['now']).strftime('%Y-%m-%d %H:%M')
            assert f'{display_now} 北京时间' in page.locator('body').inner_text()
            page.screenshot(path=str(OUT/'mvp-01-initial.png'),full_page=True);passed('真实课程、DDL记忆、非北京时间浏览器')
            send('周五20:00前交实验报告，预计两小时，尽量周四下午做。','ready')
            assert len(ctx.request.get(API+'/api/tasks').json())==3
            expect(page.get_by_role('button',name='采用方案')).to_be_enabled();passed('新增任务先预览、不写正式数据')
            send('实验报告改到周四14:00。','conflict')
            assert latest['alternatives'];assert any('云计算' in d['message'] for d in latest['diagnostics'])
            assert page.get_by_role('button',name='采用方案').count()==0
            page.screenshot(path=str(OUT/'mvp-02-conflict.png'),full_page=True);passed('固定课程冲突与备选')
            send('实验报告改到周四19:00。','ready')
            send('明天中午12:00前还要交汇报稿，预计一小时，很重要。','ready')
            assert any(c['title']=='文献阅读' for c in latest['changes']);passed('紧急插入移动低重要任务')
            send('实验报告改到今晚19:00，汇报稿明早做。','ready')
            assert any(c['title']=='软件工程报告' for c in latest['changes'])
            page.screenshot(path=str(OUT/'mvp-03-adjustment.png'),full_page=True);passed('两任务二次对话调整')
            page.get_by_role('button',name='采用方案',exact=True).click();expect(page.get_by_role('heading',name='已采用方案')).to_be_visible()
            assert len(ctx.request.get(API+'/api/tasks').json())==5
            page.reload();page.wait_for_load_state('networkidle');expect(page.get_by_role('heading',name='已采用方案')).to_be_visible()
            page.screenshot(path=str(OUT/'mvp-04-confirmed.png'),full_page=True);passed('原子采用、刷新恢复')
            send('增加超大任务。','no_plan');assert page.get_by_role('button',name='采用方案').count()==0;passed('无完整方案不伪造成功')
            page.get_by_role('button',name='放弃本轮').click();expect(page.get_by_role('heading',name='已放弃方案')).to_be_visible();assert len(ctx.request.get(API+'/api/tasks').json())==5;passed('放弃不写任务')
            page.get_by_role('button',name='手动任务卡片').click();f=page.locator('.manual-task')
            f.get_by_label('名称',exact=True).fill('手动待办');f.get_by_label('预计剩余分钟').fill('60');f.get_by_label('DDL（北京时间）').fill(f'{SUNDAY}T20:00');f.get_by_role('button',name='生成候选').click()
            expect(page.get_by_role('button',name='采用方案')).to_be_visible();page.get_by_role('button',name='放弃本轮').click();passed('手动任务与放弃')
            session_id=page.evaluate("localStorage.getItem('sga-assistant-session:'+location.host)")
            task=next(t for t in ctx.request.get(API+'/api/tasks').json() if t['title']=='软件工程报告')
            stale=ctx.request.post(f'{API}/api/assistant/sessions/{session_id}/messages',data={'client_message_id':'stale-preview-test','text':'更新云计算任务标题','actions':[{'op':'update','target':f"task:{task['id']}",'fields':{'title':'候选旧标题','profile':{'fixed_start':f'{THURSDAY}T19:00:00+08:00'}}}]})
            assert stale.status==200 and stale.json()['status']=='ready',stale.text()
            changed=ctx.request.patch(f"{API}/api/tasks/{task['id']}",data={'title':'任务管理新标题'})
            assert changed.status==200,changed.text()
            page.reload();page.wait_for_load_state('networkidle')
            expect(page.get_by_role('heading',name='资料已变化，请重新生成')).to_be_visible();assert page.get_by_role('button',name='采用方案',exact=True).count()==0
            page.screenshot(path=str(OUT/'mvp-06-stale-candidate.png'),full_page=True);passed('外部编辑使旧候选失效，不会覆盖新标题')
            page.get_by_role('button',name='手动任务卡片').click();f=page.locator('.manual-task')
            f.get_by_label('修改哪项任务').select_option(f"task:{task['id']}")
            f.get_by_label('名称',exact=True).fill('手动重新生成候选')
            f.get_by_role('button',name='生成候选').click()
            expect(page.get_by_role('button',name='采用方案',exact=True)).to_be_visible()
            assert any(t['title']=='任务管理新标题' for t in ctx.request.get(API+'/api/tasks').json())
            assert all(t['title']!='候选旧标题' for t in ctx.request.get(API+'/api/tasks').json())
            page.get_by_role('button',name='放弃本轮').click();passed('过期后手动修改基于最新任务生成，不覆盖已保存名称')
            for width in [390,320]:
                page.set_viewport_size({'width':width,'height':844});page.wait_for_timeout(100)
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),width
                page.get_by_role('button',name='周日程',exact=True).click();expect(page.get_by_role('heading',name='本周日程')).to_be_visible();page.get_by_role('button',name='聊天与方案').click()
            page.screenshot(path=str(OUT/'mvp-05-mobile.png'),full_page=True);passed('390和320宽度无页面溢出')
            page.set_viewport_size({'width':1440,'height':1000});ctx.route('**/api/assistant/sessions/*/messages',lambda route:route.abort())
            page.get_by_label('新增任务或调整要求').fill('网络故障时保留输入');page.get_by_role('button',name='发送',exact=True).click();expect(page.get_by_role('alert')).to_be_visible();expect(page.get_by_label('新增任务或调整要求')).to_have_value('网络故障时保留输入');passed('网络失败保留输入')
            assert not report['runtime_errors'],report['runtime_errors']
            report['passed']=True
        except Exception as e:report['passed']=False;report['error']=str(e);raise
        finally:
            (OUT/'browser-mvp-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');browser.close()


if __name__=='__main__':main()

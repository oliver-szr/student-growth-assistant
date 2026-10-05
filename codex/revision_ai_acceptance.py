"""Real provider acceptance in a unique anonymous database; no secret output."""
import os,sys,json,time,uuid
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
database=ROOT/'codex'/'.runtime'/f'demo-revision-ai-{uuid.uuid4().hex}.db'
os.environ.update(SGA_DEMO='1',SGA_DATABASE_PATH=str(database),SGA_DEMO_NOW='2026-10-18T21:00:00+08:00',SGA_AUTO_BACKUP='0')
sys.path.insert(0,str(ROOT/'backend'))
from fastapi.testclient import TestClient
from app.main import app
from app.services.claude_client import get_claude_config

def send(client,sid,text,report):
    response=client.post(f'/api/assistant/sessions/{sid}/runs',json={'client_message_id':uuid.uuid4().hex,'text':text})
    response.raise_for_status();run=response.json();until=time.monotonic()+270
    while time.monotonic()<until:
        run=client.get(f"/api/assistant/runs/{run['id']}").json()
        if run['status']!='running':break
        time.sleep(.5)
    report['runs'].append({'status':run['status'],'error_code':run.get('error_code')})
    if run['status']!='completed':raise AssertionError(f"AI run failed: {run.get('error_code') or run['status']}")
    return client.get(f'/api/assistant/sessions/{sid}').json()['proposal']

def main():
    config=get_claude_config()
    report={'real_ai':True,'model':config.model,'checks':[],'runs':[],'passed':False}
    try:
        with TestClient(app) as client:
            sid=client.post('/api/assistant/sessions',json={}).json()['id']
            p=send(client,sid,'新增写作任务“跨周报告”，预计180分钟，下周三10月21日中午12点截止。允许拆分，最多2段，每段至少90分钟。只能安排在10月19日周一08:05到09:35、10月20日周二08:05到09:35这两个时段。',report)
            assert p['status']=='ready',p['status']
            assert len(p['items'])==2
            assert p['recommendation']['source']=='ai'
            assert client.get('/api/tasks').json()==[]
            client.post(f"/api/assistant/proposals/{p['id']}/confirm").raise_for_status()
            task=client.get('/api/tasks').json()[0]
            report['checks']+=['real_parse_5_minute_split_crossweek','real_ai_recommendation','confirm_only_writes']
            os.environ['SGA_DEMO_NOW']='2026-10-19T10:00:00+08:00'
            client.post(f"/api/tasks/{task['id']}/feedback",json={'client_action_id':uuid.uuid4().hex,'outcome':'partial','actual_minutes':60,'remaining_minutes':120}).raise_for_status()
            sid=client.post('/api/assistant/sessions',json={}).json()['id']
            p=send(client,sid,'跨周报告剩余120分钟，改为10月20日周二08:10开始连续完成。取消之前两个时段的限制，不再拆分。截止时间保持不变。',report)
            assert p['status']=='ready',p['status']
            assert len(p['items'])==1 and p['items'][0]['start_at']=='2026-10-20T08:10:00+08:00'
            assert p['items'][0]['end_at']=='2026-10-20T10:10:00+08:00'
            client.post(f"/api/assistant/proposals/{p['id']}/confirm").raise_for_status()
            assert len(client.get('/api/tasks').json())==1
            report['checks']+=['real_followup_on_same_task','confirmed_remaining_only','crossweek_persisted']
            report['passed']=True
    except Exception as error:
        report['failure']=f'{type(error).__name__}: {error}'[:300]
        raise
    finally:
        target=ROOT/'codex'/'.local'/'revision-ai-report.json';target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()

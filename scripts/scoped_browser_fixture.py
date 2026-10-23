"""Prepare anonymous Stage 1 UI data through the existing APIs (never reset a DB)."""
import argparse
import uuid
import httpx


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--api',default='http://127.0.0.1:8087')
    parser.add_argument('--scenario',choices=['single','expansion'],default='single')
    args=parser.parse_args()
    with httpx.Client(base_url=args.api,timeout=125) as api:
        settings=api.get('/api/assistant/settings').raise_for_status().json()
        assert settings['demo'] and settings['now']=='2026-10-05T07:50:00+08:00', 'Requires isolated Stage 1 demo clock'
        assert api.get('/api/tasks').raise_for_status().json()==[], 'Use a new empty demo database; do not overwrite existing work'
        sid=api.post('/api/assistant/sessions',json={}).raise_for_status().json()['id']
        rows=[('报告',9,14),('练习',10,14),('阅读',12,14)] if args.scenario=='single' else [('紧急报告',8,10),('可调整练习',9,11)]
        for title,hour,ddl in rows:
            action=dict(op='add',fields=dict(title=title,duration_minutes=60,deadline=f'2026-10-05T{ddl:02}:00:00+08:00',profile={'fixed_start':f'2026-10-05T{hour:02}:00:00+08:00'}))
            p=api.post(f'/api/assistant/sessions/{sid}/messages',json=dict(client_message_id=uuid.uuid4().hex,text='匿名验收任务',actions=[action])).raise_for_status().json()
            assert p['status']=='ready', p
            api.post(f"/api/assistant/proposals/{p['id']}/confirm").raise_for_status()
        tasks=api.get('/api/tasks').raise_for_status().json()
        refs=[f"task:{t['id']}" for t in tasks]
        p=api.post(f'/api/assistant/sessions/{sid}/messages',json=dict(client_message_id=uuid.uuid4().hex,text='解除测试定位限制，保留原安排',actions=[dict(op='update',target=ref,fields={'profile':{'fixed_start':None}}) for ref in refs])).raise_for_status().json()
        assert p['status']=='ready',p
        api.post(f"/api/assistant/proposals/{p['id']}/confirm").raise_for_status()
        # The browser adds the actual conflicting rule in the normal rules form.
        print(dict(session_id=sid,task_refs=refs,now=settings['now'],database='anonymous_demo_only'))


if __name__=='__main__':
    main()

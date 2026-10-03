"""Real AI acceptance on an explicitly isolated demo server only."""
import json
import os
import sys
import uuid
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]


def main():
    evidence=ROOT/'codex'/'evidence';evidence.mkdir(exist_ok=True)
    result={'mode':'real_ai','model':os.getenv('CLAUDE_MODEL','backend/.env'),'cases':[]}
    try:
        with httpx.Client(base_url='http://127.0.0.1:8001',timeout=30) as client:
            settings=client.get('/api/assistant/settings').json()
            assert settings['demo'] and settings['now']=='2026-10-07T18:00:00+08:00'
            sid=client.post('/api/assistant/sessions',json={}).json()['id']
            original_deadlines={t['ref']:t['deadline'] for t in client.get(f'/api/assistant/sessions/{sid}').json()['tasks']}
            result['original_deadlines']=original_deadlines
            def send(text,want,clarification=None,retry=True):
                r=client.post(f'/api/assistant/sessions/{sid}/messages',json={'client_message_id':str(uuid.uuid4()),'text':text})
                r.raise_for_status();p=r.json()
                result['cases'].append({'text':text,'status':p['status'],'ai_error':p.get('ai_error'),'proposal':p})
                print(json.dumps({'step':len(result['cases']),'status':p['status'],'ai_error':p.get('ai_error'),'questions':p['questions'],'summary':p['summary']},ensure_ascii=False),flush=True)
                if p.get('ai_error')=='AI_UNAVAILABLE' and retry:
                    result['retry_used']=True
                    print('Explicit acceptance retry after temporary provider failure',flush=True)
                    return send(text,want,clarification,False)
                assert not p.get('ai_error'),p.get('ai_error')
                if p['status']=='needs_input' and want!='needs_input' and clarification:
                    return send(clarification,want)
                assert p['status']==want,(p['status'],p['questions'],p['diagnostics'])
                return p
            def information_flow():
                send('新增一个阅读总结任务。','needs_input')
                p=send('阅读总结预计30分钟，2026年10月11日20:00截止，普通重要程度，请自动安排。','ready')
                assert sum(a['op']=='add' for a in p['actions'])==1
                task=next(t for t in p['tasks'] if t['title'].startswith('阅读总结'))
                assert task['duration_minutes']==30 and task['deadline'].startswith('2026-10-11T20:00')
                r=client.post(f"/api/assistant/proposals/{p['id']}/discard");r.raise_for_status()
                result['information_completed_without_duplicate']=True
            if '--information-only' in sys.argv:
                information_flow()
                result['passed']=True
                return
            p=send('周五20:00前交实验报告，预计两小时，尽量周四下午做。','ready','任务名称就是“实验报告”，不关联课程，不用备注。120分钟，2026年10月9日20:00截止，普通重要程度，尽量10月8日下午做，信息已确认，请生成候选。')
            report=next(t for t in p['tasks'] if t['title']=='实验报告')
            assert report['duration_minutes']==120 and report['deadline'].startswith('2026-10-09T20:00')
            send('实验报告改到周四14:00。','conflict','是，实验报告固定在2026年10月8日14:00开始，时长和DDL不变。')
            send('那把实验报告放在周四19:00。','ready','是，实验报告固定在2026年10月8日19:00开始，清除旧的14:00要求，时长和DDL不变。')
            p=send('明天中午12:00前还要交汇报稿，预计一小时，很重要。','ready','汇报稿60分钟，2026年10月8日12:00截止，高重要程度，不需要备注，请安排在明天上午08:00至12:00内。')
            assert any(t['title']=='汇报稿' and t['priority']=='high' for t in p['tasks'])
            assert any(c['title']=='文献阅读' for c in p['changes'])
            p=send('实验报告改到今晚19:00，汇报稿明早做。','ready','实验报告固定2026年10月7日19:00开始，汇报稿固定10月8日10:30开始，时长和DDL不变。')
            assert sum(a['op']=='add' for a in p['actions'])==2
            assert any(c['title']=='软件工程报告' for c in p['changes'])
            assert all(t['deadline']==original_deadlines[t['ref']] for t in p['tasks'] if t['ref'] in original_deadlines)
            explanation=client.post(f"/api/assistant/proposals/{p['id']}/explanation").json()
            assert explanation['source']=='ai',explanation
            result['explanation']=explanation
            r=client.post(f"/api/assistant/proposals/{p['id']}/confirm");r.raise_for_status()
            restored=client.get(f'/api/assistant/sessions/{sid}').json()
            assert restored['proposal']['status']=='applied'
            assert len(restored['tasks'])==5
            assert all(t['deadline']==original_deadlines[t['ref']] for t in restored['tasks'] if t['ref'] in original_deadlines)
            result['original_deadlines_preserved']=True
            sid2=client.post('/api/assistant/sessions',json={}).json()['id']
            sid=sid2
            information_flow()
            result['passed']=True
    except Exception as e:
        result['passed']=False;result['error']=str(e);raise
    finally:
        filename='real-ai-information-results.json' if '--information-only' in sys.argv else 'real-ai-results.json'
        (evidence/filename).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__': main()

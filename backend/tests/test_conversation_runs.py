"""Real HTTP lifecycle and durable chunks; no live model calls."""
import asyncio
import time
from datetime import timedelta
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import AssistantMessage, AssistantRun, AssistantSession, Task
from app.services import conversation_runs as runs
from app.services.claude_client import AIServiceError


def conversation(client, key='chat'):
    r=client.post('/api/conversations',json={'client_request_id':key});assert r.status_code==201
    return r.json()['id']


def start(client,sid,key='send',text='你好'):
    r=client.post(f'/api/conversations/{sid}/runs',json={'client_message_id':key,'text':text})
    assert r.status_code==202,r.text
    return r.json()


def wait(client,sid,rid):
    for _ in range(200):
        value=client.get(f'/api/conversations/{sid}/runs/{rid}').json()
        if value['status']!='running':return value
        time.sleep(.015)
    raise AssertionError('run did not finish')


@pytest.fixture
def streaming(monkeypatch):
    requests=[]
    async def events(request):
        requests.append(request)
        yield {'type':'mode','value':'streaming'}
        for text in ['你好🙂，','可以慢慢聊。','我记得前面的讨论。']:
            await asyncio.sleep(.11)
            yield {'type':'delta','text':text}
    monkeypatch.setattr(runs,'reply_events',events)
    return requests


def test_real_increment_cursor_history_and_same_message_identity(client,test_engine,streaming):
    sid=conversation(client); first=start(client,sid)
    assert client.post(f'/api/conversations/{sid}/runs',json={'client_message_id':'send','text':'不同'}).status_code==409
    partial=None
    for _ in range(100):
        value=client.get(f"/api/conversations/{sid}/runs/{first['id']}").json()
        if value['delta'] and value['status']=='running':partial=value;break
        time.sleep(.02)
    assert partial and partial['delta']=='你好🙂，'
    done=wait(client,sid,first['id']);assert done['status']=='completed'
    tail=client.get(f"/api/conversations/{sid}/runs/{first['id']}?after={partial['next_cursor']}&attempt=1").json()
    assert not tail['reset'] and partial['delta']+tail['delta']==done['delta']
    again=client.get(f"/api/conversations/{sid}/runs/{first['id']}?after={done['next_cursor']}&attempt=1").json()
    assert again['delta']==''
    repeated=start(client,sid);assert repeated['id']==first['id']
    with Session(test_engine) as db:
        session=db.get(AssistantSession,sid);session.created_at-=timedelta(days=7);db.commit()
    second=start(client,sid,'next','你还记得什么？');wait(client,sid,second['id'])
    assert [{'role':m['role'],'text':m['text']} for m in streaming[-1]['history']]==[{'role':'user','text':'你好'},{'role':'assistant','text':done['delta']}]
    assert len(client.get(f'/api/conversations/{sid}/messages').json()['items'])==4
    assert client.get('/api/tasks').json()==[]
    other=conversation(client,'other')
    assert client.get(f"/api/conversations/{other}/runs/{first['id']}").status_code==404


def test_stop_retry_idempotency_archiving_and_old_api_are_safe(client,streaming):
    sid=conversation(client); initial=start(client,sid)
    version=client.get(f'/api/conversations/{sid}').json()['version']
    assert client.patch(f'/api/conversations/{sid}',json={'expected_version':version,'archived':True}).json()['detail']['code']=='CONVERSATION_BUSY'
    for action in ('', '/cancel','/retry'):
        r=client.get(f"/api/assistant/runs/{initial['id']}") if not action else client.post(f"/api/assistant/runs/{initial['id']}"+action)
        assert r.status_code==422
    stop=client.post(f"/api/conversations/{sid}/runs/{initial['id']}/stop",json={'expected_attempt':1}).json()
    assert stop['status']=='cancelled'
    retry=client.post(f"/api/conversations/{sid}/runs/{initial['id']}/retry",json={'expected_attempt':1}).json()
    assert retry['attempt']==2 and retry['user_message_id']==initial['user_message_id']
    duplicate=client.post(f"/api/conversations/{sid}/runs/{initial['id']}/retry",json={'expected_attempt':1}).json()
    assert duplicate['attempt']==2 and duplicate['assistant_message_id']==retry['assistant_message_id']
    assert client.post(f"/api/conversations/{sid}/runs/{initial['id']}/stop",json={'expected_attempt':1}).status_code==409
    done=wait(client,sid,initial['id']);assert done['status']=='completed'
    reset=client.get(f"/api/conversations/{sid}/runs/{initial['id']}?attempt=1&after=5").json()
    assert reset['reset'] and reset['from_cursor']==0
    messages=client.get(f'/api/conversations/{sid}/messages').json()['items']
    assert len([m for m in messages if m['role']=='user'])==1
    assert len([m for m in messages if m['role']=='assistant'])==2


def test_partial_failure_retry_and_missing_key(client,monkeypatch):
    async def failing(request):
        yield {'type':'delta','text':'真实部分文本'}
        await asyncio.sleep(.1)
        raise AIServiceError('AI_UNAVAILABLE')
    monkeypatch.setattr(runs,'reply_events',failing)
    sid=conversation(client);initial=start(client,sid)
    done=wait(client,sid,initial['id']);assert done['status']=='failed' and done['delta']=='真实部分文本'
    assert done['error_code']=='AI_UNAVAILABLE'
    async def no_key(request):
        raise AIServiceError('AI_NOT_CONFIGURED')
        yield
    monkeypatch.setattr(runs,'reply_events',no_key)
    retry=client.post(f"/api/conversations/{sid}/runs/{initial['id']}/retry",json={'expected_attempt':1}).json()
    done=wait(client,sid,initial['id']);assert done['error_code']=='AI_NOT_CONFIGURED'
    assert done['attempt']==2


def test_context_is_bounded_read_only_and_never_includes_other_conversation(client,test_engine,streaming):
    sid=conversation(client);other=conversation(client,'secret')
    client.post(f'/api/conversations/{other}/messages',json={'client_message_id':'private','text':'另一会话秘密'})
    for i in range(28):client.post(f'/api/conversations/{sid}/messages',json={'client_message_id':str(i),'text':str(i)+'甲'*1000})
    initial=start(client,sid,'context','看看任务、日程、目标、复盘与完成记录')
    done=wait(client,sid,initial['id']);assert done['status']=='completed',done
    sent=streaming[-1]
    assert len(sent['history'])<=24 and sum(len(m['text']) for m in sent['history'])<=12000
    assert '另一会话秘密' not in str(sent)
    assert sent['context']['tasks']==[] and sent['context']['goals']==[]
    assert client.get('/api/tasks').json()==[]


def test_v3_export_restore_preserves_partial_reply_and_interrupts_running(client,streaming):
    sid=conversation(client);initial=start(client,sid)
    wait(client,sid,initial['id'])
    snapshot=client.get('/api/data/export').json()
    assert snapshot['format_version']==5
    r=client.post('/api/data/import',json=snapshot);assert r.status_code==200,r.text
    restored=client.get(f"/api/conversations/{sid}/runs/{initial['id']}").json()
    assert restored['delta'].startswith('你好') and restored['status']=='completed'


def test_restore_running_partial_interrupts_old_worker_and_rejects_broken_refs(client,streaming):
    sid=conversation(client);initial=start(client,sid)
    for _ in range(100):
        data=client.get(f"/api/conversations/{sid}/runs/{initial['id']}").json()
        if data['delta']:break
        time.sleep(.015)
    assert data['status']=='running'
    snapshot=client.get('/api/data/export').json()
    assert client.post('/api/data/import',json=snapshot).status_code==200
    restored=client.get(f"/api/conversations/{sid}/runs/{initial['id']}").json()
    assert restored['status']=='interrupted' and restored['content']['status']=='interrupted'
    time.sleep(.3)
    after=client.get(f"/api/conversations/{sid}/runs/{initial['id']}").json()
    assert after['delta']==restored['delta'] and after['status']=='interrupted'
    snapshot['tables']['assistant_runs'][0]['payload']['assistant_message_id']=999999
    assert client.post('/api/data/import',json=snapshot).status_code==422
    snapshot['tables']['assistant_runs'][0]['payload']['assistant_message_id']=[]
    assert client.post('/api/data/import',json=snapshot).status_code==422
    assert client.get(f'/api/conversations/{sid}').status_code==200


def test_no_key_uses_actual_config_failure_without_provider(client):
    sid=conversation(client);initial=start(client,sid)
    done=wait(client,sid,initial['id'])
    assert done['status']=='failed' and done['error_code']=='AI_NOT_CONFIGURED'
    assert done['delta']==''


def test_first_message_default_title_never_overwrites_manual_title(client,streaming):
    sid=conversation(client);initial=start(client,sid,text='讨论本学期的学习安排')
    wait(client,sid,initial['id'])
    metadata=client.get(f'/api/conversations/{sid}').json()
    assert metadata['title']=='讨论本学期的学习安排' and metadata['title_source']=='auto'
    client.patch(f'/api/conversations/{sid}',json={'expected_version':metadata['version'],'title':'我的手动标题'})
    following=start(client,sid,'another','不同话题');wait(client,sid,following['id'])
    assert client.get(f'/api/conversations/{sid}').json()['title']=='我的手动标题'

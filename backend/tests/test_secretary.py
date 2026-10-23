"""Stage 3 uses only anonymous per-test databases and mocked providers."""
import json,time
from copy import deepcopy
import pytest
from sqlalchemy import select,event,inspect,text
from sqlalchemy.orm import Session
from app.models import AssistantRun,AssistantMessage,MemoryEntry
from app.services import conversation_runs,conversation_tools,claude_client
from app.services.conversation_context import context_for,bounded_drafts,bounded_request
from app.workspace_schemas import ToolPlan


def call(client,method,path,**kwargs):
    r=client.request(method,path,**kwargs);assert r.status_code<300,r.text;return r.json()


def conversation(client,key='chat'):
    return call(client,'POST','/api/conversations',json={'client_request_id':key})['id']


def send(client,sid,text,key):
    run=call(client,'POST',f'/api/conversations/{sid}/runs',json={'client_message_id':key,'text':text})
    for _ in range(200):
        result=call(client,'GET',f"/api/conversations/{sid}/runs/{run['id']}")
        if result['status']!='running':return result
        time.sleep(.01)
    raise AssertionError('run not finished')


@pytest.fixture
def reply(monkeypatch):
    requests=[]
    async def stream(request):
        requests.append(request)
        yield {'type':'delta','text':'这是基于本次提供资料的交流，不自动保存业务。'}
    monkeypatch.setattr(conversation_runs,'reply_events',stream)
    return requests


@pytest.fixture
def summarize(monkeypatch):
    requests=[]
    monkeypatch.setattr(claude_client,'get_claude_config',lambda:None)
    async def provider(prompt,*args):
        data=json.loads(prompt);requests.append(data);mid=data['messages'][0]['id']
        return json.dumps({'themes':[{'text':'讨论学习方法','message_ids':[mid]}],
            'conclusions':[],'questions':[{'text':'尚未决定下一步','message_ids':[mid]}],'followups':[]},ensure_ascii=False)
    monkeypatch.setattr(claude_client,'request_claude',provider)
    return requests


def test_memory_manual_versions_disable_delete_idempotence_and_no_business_writes(client,reply):
    content={'client_request_id':'memory','text':'学习时喜欢短例子','scope':'study'}
    row=call(client,'POST','/api/memories',json=content)
    assert row['status']=='confirmed' and row['source']['kind']=='manual'
    assert call(client,'POST','/api/memories',json=content)['id']==row['id']
    assert client.post('/api/memories',json={**content,'client_request_id':'different'}).json()['detail']['code']=='MEMORY_ALREADY_EXISTS'
    sid=conversation(client);send(client,sid,'你记得我学习时的偏好吗','1')
    assert reply[-1]['confirmed_memories'][0]['id']==row['id']
    changed=call(client,'PATCH',f"/api/memories/{row['id']}",json={'expected_version':1,'text':'学习时喜欢先看完整例子','scope':'study'})
    assert client.patch(f"/api/memories/{row['id']}",json={'expected_version':1,'text':'冲突文字','scope':'study'}).status_code==409
    send(client,sid,'我的学习偏好是什么','2');assert reply[-1]['confirmed_memories'][0]['text']==changed['text']
    disabled=call(client,'POST',f"/api/memories/{row['id']}/actions",json={'expected_version':2,'action':'disable'})
    send(client,sid,'我的学习偏好是什么','3');assert reply[-1]['confirmed_memories']==[]
    deleted=call(client,'POST',f"/api/memories/{row['id']}/actions",json={'expected_version':disabled['version'],'action':'delete'})
    assert deleted['status']=='deleted' and client.get(f"/api/memories/{row['id']}").status_code==410
    assert call(client,'GET','/api/memories')['items']==[]
    assert call(client,'GET','/api/tasks')==[] and call(client,'GET','/api/reviews/records')['items']==[]


def test_memory_tool_suggestion_not_reference_until_confirm_and_source_deleted_independent(client,reply,monkeypatch):
    sid=conversation(client)
    contexts=[]
    async def choose(request):
        contexts.append(request)
        return ToolPlan(calls=[{'name':'memory_suggestion','arguments':{'text':'交流时先给结论，再给例子','scope':'general'}}])
    monkeypatch.setattr(conversation_tools,'plan',choose)
    result=send(client,sid,'以后交流请先给结论，再给例子','suggest')
    row=result['content']['tools'][0]['memory'];assert row['status']=='suggested' and contexts[-1]['confirmed_memories']==[] and not reply
    confirmed=call(client,'POST',f"/api/memories/{row['id']}/actions",json={'expected_version':1,'action':'confirm'})
    assert confirmed['status']=='confirmed'
    meta=call(client,'GET',f'/api/conversations/{sid}')
    call(client,'DELETE',f"/api/conversations/{sid}?expected_version={meta['version']}")
    independent=call(client,'GET',f"/api/memories/{row['id']}")
    assert independent['status']=='confirmed' and not independent['source']['available'] and independent['source']['message_ids']==[]


def test_transient_chat_even_if_model_requests_memory_is_rejected(client,reply,monkeypatch):
    async def choose(request):return ToolPlan(calls=[{'name':'memory_suggestion','arguments':{'text':'用户很容易累','scope':'general'}}])
    monkeypatch.setattr(conversation_tools,'plan',choose)
    result=send(client,conversation(client),'今天有点累','tired')
    assert result['content']['tools'][0]['error']=='MEMORY_EXPLICIT_INTENT_REQUIRED'
    assert call(client,'GET','/api/memories')['items']==[]


@pytest.mark.parametrize('data',[
    {'text':'api_key: sk-12345678901234567890','scope':'general'},
    {'text':'以后周三晚上不要安排任务','scope':'planning'},
    {'text':'信息','scope':'general','owner_id':'other'},
])
def test_memory_secrets_scheduling_and_client_owner_rejected(client,data):
    assert client.post('/api/memories',json={'client_request_id':'invalid',**data}).status_code==422
    assert call(client,'GET','/api/memories')['items']==[]


def test_plain_chat_skips_business_tables_and_unrelated_memory(client,test_engine,reply):
    call(client,'POST','/api/memories',json={'client_request_id':'private','text':'私人项目名称BlueMountain','scope':'profile'})
    sql=[]
    def count(connection,cursor,statement,*args):sql.append(statement.lower())
    event.listen(test_engine,'before_cursor_execute',count)
    try:send(client,conversation(client),'你好，今天聊点轻松的话题','plain')
    finally:event.remove(test_engine,'before_cursor_execute',count)
    assert reply[-1]['confirmed_memories']==[] and 'BlueMountain' not in json.dumps(reply[-1])
    assert not any(' from tasks' in s or ' from growth_goals' in s or ' from plan_items' in s for s in sql)


def test_task_lookup_finds_named_old_resource_and_facts_override_history(client,monkeypatch,reply):
    task=call(client,'POST','/api/tasks',json={'title':'旧的精确标题','duration_minutes':30,'deadline':'2026-10-16T20:00:00+08:00'})
    async def choose(request):return ToolPlan(calls=[{'name':'tasks','arguments':{'q':'精确标题'}}])
    monkeypatch.setattr(conversation_tools,'plan',choose)
    call(client,'PATCH',f"/api/tasks/{task['id']}",json={'duration_minutes':45})
    result=send(client,conversation(client),'查一下旧的精确标题任务最新时长','lookup')
    assert result['content']['tools'][0]['items'][0]['minutes']==45
    assert '正式' in reply[-1]['evidence']['formal']


def test_summary_explicit_grounded_versions_retry_key_and_original_message(client,summarize):
    sid=conversation(client)
    message=call(client,'POST',f'/api/conversations/{sid}/messages',json={'client_message_id':'original','text':'我在考虑学习方法，但没有决定下一步'})
    request={'client_request_id':'summary'}
    result=call(client,'POST',f'/api/conversations/{sid}/summaries',json=request)
    assert result['status']=='completed' and result['result']['summary']['conclusions']==[]
    assert result['result']['source']['message_ids']==[message['id']]
    assert call(client,'POST',f'/api/conversations/{sid}/summaries',json=request)['result']['id']==result['result']['id'] and len(summarize)==1
    again=call(client,'POST',f'/api/conversations/{sid}/summaries',json={'client_request_id':'new-summary'})
    assert again['result']['version']==2 and len(call(client,'GET',f'/api/conversations/{sid}/summaries')['items'])==2
    assert client.get(f"/api/assistant/runs/{result['id']}").status_code==422
    assert call(client,'GET','/api/tasks')==[] and call(client,'GET','/api/memories')['items']==[]


def test_summary_no_key_invalid_reference_and_explicit_same_request_retry(client,monkeypatch,summarize):
    sid=conversation(client);call(client,'POST',f'/api/conversations/{sid}/messages',json={'client_message_id':'u','text':'学习讨论'})
    async def fail(*args):raise claude_client.AIServiceError('AI_UNAVAILABLE')
    original=claude_client.request_claude;monkeypatch.setattr(claude_client,'request_claude',fail)
    assert client.post(f'/api/conversations/{sid}/summaries',json={'client_request_id':'retry'}).status_code==503
    operation=call(client,'GET',f'/api/conversations/{sid}/summaries/requests/retry');assert operation['status']=='failed'
    late=call(client,'POST',f'/api/conversations/{sid}/messages',json={'client_message_id':'late','text':'失败后才新增的另一主题'})
    monkeypatch.setattr(claude_client,'request_claude',original)
    completed=call(client,'POST',f'/api/conversations/{sid}/summaries',json={'client_request_id':'retry','retry_attempt':operation['attempt']})
    assert completed['status']=='completed' and completed['attempt']==2
    assert late['id'] not in [m['id'] for m in summarize[-1]['messages']]
    async def bad(*args):return '{"themes":[{"text":"伪造引用","message_ids":[999999]}]}'
    monkeypatch.setattr(claude_client,'request_claude',bad)
    assert client.post(f'/api/conversations/{sid}/summaries',json={'client_request_id':'bad'}).status_code==502
    assert len(call(client,'GET',f'/api/conversations/{sid}/summaries')['items'])==1


def test_long_summary_budget_and_deleted_source_is_inaccessible(client,test_engine,summarize):
    sid=conversation(client)
    with Session(test_engine) as db:
        owner=db.get(__import__('app.models',fromlist=['AssistantSession']).AssistantSession,sid).owner_id
        for n in range(210):db.add(AssistantMessage(session_id=sid,owner_id=owner,role='user',text=f'主题{n}'+('资料'*600)))
        db.commit()
    result=call(client,'POST',f'/api/conversations/{sid}/summaries',json={'client_request_id':'long'})
    assert result['result']['coverage']['bounded'] and sum(len(m['text']) for m in summarize[0]['messages'])<=18000
    assert len(summarize[0]['messages'])<=80
    latest=call(client,'GET',f'/api/conversations/{sid}/messages?latest=true&limit=30');assert len(latest['items'])==30 and latest['next_before_id']
    meta=call(client,'GET',f'/api/conversations/{sid}')
    call(client,'DELETE',f"/api/conversations/{sid}?expected_version={meta['version']}")
    assert client.get(f'/api/conversations/{sid}/summaries').status_code==410
    assert client.get(f'/api/conversations/{sid}/messages').status_code==410


def test_old_v4_cannot_erase_memory_summary_and_v5_roundtrip(client,summarize):
    old=call(client,'GET','/api/data/export');assert old['format_version']==5
    old['format_version']=4;del old['tables']['memory_entries']
    assert client.post('/api/data/import',json=old).status_code==200
    call(client,'POST','/api/memories',json={'client_request_id':'protect','text':'喜欢先看例子','scope':'study'})
    assert client.post('/api/data/import',json=old).json()['detail']['code']=='LEGACY_RESTORE_SECRETARY_PRESENT'
    sid=conversation(client);call(client,'POST',f'/api/conversations/{sid}/messages',json={'client_message_id':'u','text':'讨论学习'})
    call(client,'POST',f'/api/conversations/{sid}/summaries',json={'client_request_id':'summary'})
    snapshot=call(client,'GET','/api/data/export');assert client.post('/api/data/import',json=snapshot).status_code==200
    identity=call(client,'GET','/api/data/export')['tables']['workspace_metadata'][0]
    assert identity['workspace_id']!=snapshot['tables']['workspace_metadata'][0]['workspace_id']
    assert identity['owner_id']==snapshot['tables']['workspace_metadata'][0]['owner_id']
    assert len(call(client,'GET','/api/memories')['items'])==1
    assert len(call(client,'GET',f'/api/conversations/{sid}/summaries')['items'])==1
    invalid=deepcopy(snapshot);invalid['tables']['memory_entries'][0]['owner_id']='forged'
    assert client.post('/api/data/import',json=invalid).status_code==422


def test_v5_migration_rollback_repeat_and_frozen_v4_upgrade(tmp_path,monkeypatch):
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    from app.database import create_sqlite_engine
    from app.services.schema_migrations import upgrade_database
    monkeypatch.setenv('SGA_BACKUP_DIR',str(tmp_path/'backups'))
    engine=create_sqlite_engine(f'sqlite:///{tmp_path/"v4.db"}')
    config=Config();config.set_main_option('script_location',str(Path(__file__).parents[1]/'alembic'))
    with engine.connect() as c:config.attributes['connection']=c;command.upgrade(config,'0004_review_records')
    def fail(connection,cursor,statement,*args):
        if 'CREATE INDEX memory_active' in statement:raise RuntimeError('injected stage3 failure')
    event.listen(engine,'before_cursor_execute',fail)
    try:
        with pytest.raises(RuntimeError,match='injected stage3'):upgrade_database(engine)
    finally:event.remove(engine,'before_cursor_execute',fail)
    assert 'memory_entries' not in inspect(engine).get_table_names()
    with engine.connect() as c:assert c.execute(text('SELECT version_num FROM alembic_version')).scalar()=='0004_review_records'
    upgrade_database(engine);upgrade_database(engine)
    with engine.connect() as c:assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
    engine.dispose()


def test_context_retrieves_older_named_message_with_full_recent_history(client,test_engine):
    sid=conversation(client)
    from app.models import AssistantSession
    with Session(test_engine) as db:
        owner=db.get(AssistantSession,sid).owner_id
        original=AssistantMessage(session_id=sid,owner_id=owner,role='user',text='蓝鲸项目还有未决定的问题')
        db.add(original);db.flush();original_id=original.id
        for _ in range(45):db.add(AssistantMessage(session_id=sid,owner_id=owner,role='user',text='近期无关话题'*300))
        current=AssistantMessage(session_id=sid,owner_id=owner,role='user',text='之前蓝鲸项目说了什么')
        db.add(current);db.flush()
        run=AssistantRun(session_id=sid,text=current.text,payload={'user_message_id':current.id})
        data,_=context_for(db,run)
        assert original_id in [m['id'] for m in data['history']]
        assert sum(len(m['text']) for m in data['history'])<=6500


def test_context_hard_budget_never_mutates_persisted_draft_or_silently_sends_oversize():
    draft={'id':1,'kind':'breakdown','version':'v1','status':'ready','content':{'text':'资料'*30000}}
    source=deepcopy(draft)
    selected=bounded_drafts([draft]);assert selected[0]['content_omitted'] and draft==source
    request={'message':'解释已有内容','context':{'now':'2026-10-14','tasks':['x'*2000]*50},
        'history':[{'text':'h'*1600} for _ in range(12)],'current_drafts':[draft],
        'tool_results':[{'tool':'tasks','items':['q'*3000]*40} for _ in range(4)]}
    result=bounded_request(request)
    assert len(json.dumps(result,ensure_ascii=False))<=26000
    assert result['context_budget']['truncated'] and request['current_drafts']==[source]
    with pytest.raises(claude_client.AIServiceError) as rejected:
        bounded_request({'message':'x'*30000,'context':{'now':'today'}})
    assert rejected.value.code=='AI_CONTEXT_TOO_LARGE'


def test_summary_restored_run_rejects_late_provider_result(client,test_engine,monkeypatch,summarize):
    sid=conversation(client)
    call(client,'POST',f'/api/conversations/{sid}/messages',json={'client_message_id':'u','text':'待整理主题'})
    original=claude_client.request_claude
    async def invalidated(*args):
        with Session(test_engine) as db:
            run=db.scalar(select(AssistantRun).where(AssistantRun.session_id==sid))
            run.status='interrupted';db.commit()
        return await original(*args)
    monkeypatch.setattr(claude_client,'request_claude',invalidated)
    response=client.post(f'/api/conversations/{sid}/summaries',json={'client_request_id':'interrupted'})
    assert response.status_code==409 and response.json()['detail']['code']=='SUMMARY_INTERRUPTED'
    assert call(client,'GET',f'/api/conversations/{sid}/summaries')['items']==[]


def test_memory_source_owner_and_deleted_suggestion_cannot_be_confirmed(client,test_engine,reply,monkeypatch):
    sid=conversation(client)
    async def choose(request):return ToolPlan(calls=[{'name':'memory_suggestion','arguments':{'text':'以后喜欢例子','scope':'study'}}])
    monkeypatch.setattr(conversation_tools,'plan',choose)
    result=send(client,sid,'以后请多给例子','m');memory=result['content']['tools'][0]['memory']
    meta=call(client,'GET',f'/api/conversations/{sid}')
    call(client,'DELETE',f"/api/conversations/{sid}?expected_version={meta['version']}")
    assert client.post(f"/api/memories/{memory['id']}/actions",json={'action':'confirm','expected_version':1}).json()['detail']['code']=='SOURCE_UNAVAILABLE'
    with Session(test_engine) as db:
        row=db.get(MemoryEntry,memory['id']);row.owner_id='other';db.commit()
    assert client.get(f"/api/memories/{memory['id']}").status_code==404
    assert call(client,'GET','/api/memories')['items']==[]


def test_summary_missing_provider_key_is_real_error_not_template(client,monkeypatch):
    sid=conversation(client)
    call(client,'POST',f'/api/conversations/{sid}/messages',json={'client_message_id':'u','text':'讨论学习'})
    def missing():raise claude_client.AIServiceError('AI_NOT_CONFIGURED')
    monkeypatch.setattr(claude_client,'get_claude_config',missing)
    response=client.post(f'/api/conversations/{sid}/summaries',json={'client_request_id':'no-key'})
    assert response.status_code==503 and response.json()['detail']['code']=='AI_NOT_CONFIGURED'
    assert call(client,'GET',f'/api/conversations/{sid}/summaries')['items']==[]
    operation=call(client,'GET',f'/api/conversations/{sid}/summaries/requests/no-key')
    assert operation['status']=='failed' and operation['error_code']=='AI_NOT_CONFIGURED'

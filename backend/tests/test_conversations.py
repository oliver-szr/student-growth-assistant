"""Anonymous conversation API/lifecycle tests; never execute a provider."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.models import AssistantSession, AssistantMessage, AssistantProposal, AssistantRun, GrowthChangeDraft, WorkspaceMetadata
from app.services.conversations import automatic_title
from app.services.planning_state import planning_transaction


def create(client, **fields):
    response = client.post('/api/conversations', json={'client_request_id': str(uuid4()), **fields})
    assert response.status_code == 201, response.text
    return response.json()


def append(client, conversation, text='一条真实持久消息', key=None):
    response = client.post(f"/api/conversations/{conversation['id']}/messages", json={
        'client_message_id': key or str(uuid4()), 'text': text})
    assert response.status_code == 201, response.text
    return response.json()


def change(client, conversation, **fields):
    response = client.patch(f"/api/conversations/{conversation['id']}", json={
        'expected_version': conversation['version'], **fields})
    assert response.status_code == 200, response.text
    return response.json()


def test_full_lifecycle_and_create_retry_after_manual_rename(client, test_engine):
    first = create(client)
    second = create(client, title='手动标题', client_request_id='create-once')
    assert first['week_start'] is None and first['scope'] == 'conversation'
    assert first['title'] == '新对话' and first['title_source'] == 'default'
    message = append(client, second)
    second = change(client, second, title='改名后标题', pinned=True)
    assert client.get('/api/conversations').json()['items'][0]['id'] == second['id']
    retry = client.post('/api/conversations', json={'client_request_id':'create-once'}).json()
    assert retry['id'] == second['id'] and retry['title'] == '改名后标题'
    second = change(client, second, pinned=False, archived=True)
    assert [s['id'] for s in client.get('/api/conversations').json()['items']] == [first['id']]
    assert client.get('/api/conversations?archive=archived').json()['items'][0]['id'] == second['id']
    assert client.get(f"/api/conversations/{second['id']}/messages").json()['items'][0]['id'] == message['id']
    rejected = client.post(f"/api/conversations/{second['id']}/messages", json={'client_message_id':'archived','text':'不写入'})
    assert rejected.status_code == 409 and rejected.json()['detail']['code'] == 'CONVERSATION_ARCHIVED'
    second = change(client, second, archived=False)
    deleted = client.delete(f"/api/conversations/{second['id']}?expected_version={second['version']}")
    assert deleted.status_code == 200 and deleted.json()['deletion_mode'] == 'soft'
    assert client.delete(f"/api/conversations/{second['id']}?expected_version={second['version']}").json() == deleted.json()
    for suffix in ('', '/messages'):
        assert client.get(f"/api/conversations/{second['id']}{suffix}").status_code == 410
    assert client.get('/api/conversations?q=标题').json()['items'] == []
    assert client.post('/api/conversations', json={'client_request_id':'create-once'}).status_code == 410
    with Session(test_engine) as db:
        assert db.get(AssistantMessage, message['id']).text == message['text']


def test_cross_day_and_week_continuation_and_real_activity_order(client, monkeypatch):
    first, second = create(client), create(client)
    old = append(client, first, '跨天之前')
    later = datetime(2026, 10, 22, 11, tzinfo=timezone.utc)

    class LaterClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return later.astimezone(tz) if tz else later.replace(tzinfo=None)

    monkeypatch.setattr(models, 'datetime', LaterClock)
    current = append(client, first, '跨周后继续原会话')
    assert current['session_id'] == old['session_id']
    assert current['created_at'].startswith('2026-10-22')
    assert client.get(f"/api/conversations/{first['id']}").json()['last_activity_at'] == current['created_at']
    assert [s['id'] for s in client.get('/api/conversations').json()['items']] == [first['id'], second['id']]
    assert len(client.get(f"/api/conversations/{first['id']}/messages").json()['items']) == 2


def test_stable_keyset_messages_with_equal_times_and_new_inserts(client):
    session = create(client)
    saved = [append(client, session, f'第{i}条') for i in range(5)]
    base = f"/api/conversations/{session['id']}/messages"
    first = client.get(base+'?limit=2').json()
    extra = append(client, session, '分页期间追加')
    second = client.get(base+f"?limit=2&after_id={first['next_after_id']}").json()
    third = client.get(base+f"?limit=2&after_id={second['next_after_id']}").json()
    assert [m['id'] for page in (first, second, third) for m in page['items']] == [m['id'] for m in saved] + [extra['id']]
    assert third['has_more'] is False and third['next_after_id'] is None
    last = client.get(base+f"?before_id={extra['id']+1}&limit=2").json()
    previous = client.get(base+f"?before_id={last['next_before_id']}&limit=2").json()
    assert [m['id'] for m in last['items']] == [saved[-1]['id'], extra['id']]
    assert [m['id'] for m in previous['items']] == [saved[2]['id'], saved[3]['id']]
    assert client.get(base+'?after_id=1&before_id=2').status_code == 422


def test_title_and_literal_body_search_archives_and_original_message_references(client):
    title = create(client, title='中文主题报告')
    body = create(client, title='其他主题')
    saved = [append(client, body, '前文'*80+'中文主题 100%_ 字面搜索 '+str(i)+'后文'*80) for i in range(5)]
    body = change(client, body, archived=True)
    found = client.get('/api/conversations', params={'q':'中文主题','limit':1}).json()
    more = client.get('/api/conversations', params={'q':'中文主题','limit':1,'offset':found['next_offset']}).json()
    assert {s['id'] for s in found['items']+more['items']} == {title['id'], body['id']}
    result = next(s for s in found['items']+more['items'] if s['id'] == body['id'])
    assert result['archived_at'] is not None and result['more_message_matches'] is True
    assert [m['message_id'] for m in result['message_matches']] == [m['id'] for m in saved[:3]]
    assert all('中文主题' in m['snippet'] and len(m['snippet']) < 180 for m in result['message_matches'])
    assert client.get('/api/conversations', params={'q':'100%_'}).json()['items'][0]['id'] == body['id']
    assert client.get('/api/conversations', params={'q':"' OR 1=1 --"}).json()['items'] == []
    matches = client.get(f"/api/conversations/{body['id']}/messages", params={'q':'中文主题','limit':2}).json()
    assert len(matches['items']) == 2 and matches['has_more']


def test_manual_title_cannot_be_overwritten_by_future_automatic_title(client, test_engine):
    conversation = create(client)
    with Session(test_engine) as db, planning_transaction(db):
        assert automatic_title(db, db.get(AssistantSession, conversation['id']), '未来自动标题', 1)
    auto = client.get(f"/api/conversations/{conversation['id']}").json()
    manual = change(client, auto, title='用户决定的名称')
    with Session(test_engine) as db, planning_transaction(db):
        assert not automatic_title(db, db.get(AssistantSession, conversation['id']), '迟到自动标题', auto['version'])
        assert not automatic_title(db, db.get(AssistantSession, conversation['id']), '也不能覆盖', manual['version'])
    assert client.get(f"/api/conversations/{conversation['id']}").json()['title'] == '用户决定的名称'


def test_version_and_message_idempotency_conflicts(client):
    conversation = create(client)
    changed = change(client, conversation, title='手动更新')
    assert client.patch(f"/api/conversations/{conversation['id']}", json={'expected_version':1,'archived':True}).json()['detail']['code'] == 'CONVERSATION_VERSION_CONFLICT'
    assert client.delete(f"/api/conversations/{conversation['id']}?expected_version=1").status_code == 409
    first = append(client, changed, key='once')
    assert append(client, changed, key='once') == first
    response = client.post(f"/api/conversations/{conversation['id']}/messages", json={'client_message_id':'once','text':'不同输入'})
    assert response.status_code == 409 and response.json()['detail']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert len(client.get(f"/api/conversations/{conversation['id']}/messages").json()['items']) == 1


@pytest.mark.parametrize('blocker', ['run', 'proposal', 'draft', 'stale_draft'])
def test_archive_and_delete_refuse_running_or_unresolved_drafts_without_mutation(client, test_engine, blocker):
    conversation = create(client)
    with Session(test_engine) as db:
        values = dict(session_id=conversation['id'], source_revision=0)
        if blocker == 'run':
            row = AssistantRun(**values, client_message_id='running', text='等待', status='running', phase='understanding', payload={})
        elif blocker == 'proposal':
            row = AssistantProposal(**values, status='ready', payload={})
        else:
            row = GrowthChangeDraft(**values, scope='conversation', status='stale' if blocker == 'stale_draft' else 'ready', payload={})
        db.add(row)
        db.commit()
        model, row_id, status = type(row), row.id, row.status
    for response in (client.patch(f"/api/conversations/{conversation['id']}", json={'expected_version':1,'archived':True}),
                     client.delete(f"/api/conversations/{conversation['id']}?expected_version=1")):
        assert response.status_code == 409
        assert response.json()['detail']['code'] == ('CONVERSATION_BUSY' if blocker == 'run' else 'CONVERSATION_HAS_DRAFTS')
    with Session(test_engine) as db:
        assert db.get(model, row_id).status == status
        assert db.get(AssistantSession, conversation['id']).version == 1


def test_delete_legacy_chat_preserves_all_formal_data_and_receipts(client):
    sid = client.post('/api/assistant/sessions', json={}).json()['id']
    proposal = client.post(f'/api/assistant/sessions/{sid}/messages', json={'client_message_id':'manual', 'text':'匿名任务',
        'actions':[{'op':'add','fields':{'title':'正式任务保留','duration_minutes':30,'deadline':'2026-10-15T20:00:00+08:00'}}]}).json()
    assert client.post(f"/api/assistant/proposals/{proposal['id']}/confirm").status_code == 200
    task = client.get('/api/tasks').json()[0]
    assert client.post(f"/api/tasks/{task['id']}/feedback", json={'client_action_id':'feedback','outcome':'completed','actual_minutes':25}).status_code == 201
    client.post('/api/goals', json={'title':'正式目标','metric_kind':'count','weekly_target':1})
    before = client.get('/api/data/export').json()['tables']
    assert client.delete(f'/api/conversations/{sid}?expected_version=1').status_code == 200
    after = client.get('/api/data/export').json()['tables']
    assert {k:v for k,v in before.items() if k!='assistant_sessions'} == {k:v for k,v in after.items() if k!='assistant_sessions'}
    assert client.post(f"/api/assistant/proposals/{proposal['id']}/confirm").status_code == 410


def test_legacy_current_week_guards_cannot_be_bypassed_by_conversation_api(client, test_engine):
    sid = client.post('/api/assistant/sessions', json={}).json()['id']
    with Session(test_engine) as db:
        session = db.get(AssistantSession, sid)
        session.week_start -= timedelta(days=7)
        row = AssistantProposal(session_id=sid, source_revision=0, status='ready', payload={})
        db.add(row); db.flush(); session.latest_proposal_id = row.id; db.commit(); pid = row.id
        run = AssistantRun(session_id=sid, client_message_id='old-run', text='历史请求', status='failed',
            phase='finished', source_revision=0, payload={})
        db.add(run); db.commit(); rid=run.id
    assert client.get(f'/api/assistant/sessions/{sid}').status_code == 200
    assert client.get(f'/api/conversations/{sid}').status_code == 200
    response = client.post(f'/api/assistant/proposals/{pid}/confirm')
    assert response.status_code == 409 and response.json()['detail']['code'] == 'OUTSIDE_CURRENT_WEEK'
    retry = client.post(f'/api/assistant/runs/{rid}/retry')
    assert retry.status_code == 409 and retry.json()['detail']['code'] == 'OUTSIDE_CURRENT_WEEK'
    assert client.post(f'/api/conversations/{sid}/messages', json={'client_message_id':'no','text':'不能绕过'}).status_code == 409
    general = create(client)
    assert client.post(f"/api/assistant/sessions/{general['id']}/runs", json={'client_message_id':'no','text':'不能启动旧AI'}).status_code == 422
    assert client.post(f"/api/assistant/sessions/{general['id']}/messages", json={'client_message_id':'no','text':'不能规划'}).status_code == 422
    assert client.get('/api/tasks').json() == []


def test_workspace_owner_is_server_resolved_and_all_reads_filter_it(client, test_engine):
    own = create(client)
    with Session(test_engine) as db:
        identity = db.get(WorkspaceMetadata, 1)
        session = db.get(AssistantSession, own['id'])
        assert session.owner_id == identity.owner_id
        other = AssistantSession(scope='conversation', owner_id=str(uuid4()), title='其他归属', week_start=None)
        db.add(other); db.flush()
        db.add(AssistantMessage(session_id=other.id, role='user', text='不能搜索到的私有词'))
        db.commit(); other_id = other.id
    assert client.get(f'/api/conversations/{other_id}').status_code == 404
    assert client.get(f'/api/conversations/{other_id}/messages').status_code == 404
    assert client.get('/api/conversations?q=私有词').json()['items'] == []
    assert [s['id'] for s in client.get('/api/conversations', params={'owner_id':'any'}).json()['items']] == [own['id']]
    for field in ('owner_id','user_id','scope','week_start','title_source'):
        assert client.post('/api/conversations', json={'client_request_id':str(uuid4()),field:'untrusted'}).status_code == 422


@pytest.mark.parametrize('suffix', ['?limit=0','?limit=101','?offset=-1','?offset=10001','?q=','?q=%20%20','?archive=bad','?scope=bad'])
def test_bounded_search_and_listing_validation(client, suffix):
    assert client.get('/api/conversations'+suffix).status_code == 422


@pytest.mark.parametrize('fields', [{}, {'title':None}, {'title':'  '}, {'title':'a'*161}, {'pinned':'true'}, {'archived':None}, {'expected_version':True,'title':'bad'}])
def test_patch_validation(client, fields):
    conversation = create(client)
    assert client.patch(f"/api/conversations/{conversation['id']}", json={'expected_version':1, **fields}).status_code == 422


def test_missing_ids_and_cors_delete_contract(client):
    assert client.get('/api/conversations/99999').status_code == 404
    assert client.get('/api/conversations/0').status_code == 422
    assert client.get('/api/conversations/9999999999999999999999999999999').status_code == 422
    response = client.options('/api/conversations/1', headers={'Origin':'http://127.0.0.1:5187', 'Access-Control-Request-Method':'DELETE'})
    assert response.status_code == 200

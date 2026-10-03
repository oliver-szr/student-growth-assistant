from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Task,Plan
from tests.test_assistant_api import new_action,proposal,session


def test_duplicate_concurrent_messages_create_one_draft(client,monkeypatch):
    from app.services import assistant_clock
    monkeypatch.setattr(assistant_clock,'assistant_now',lambda:datetime.fromisoformat('2026-10-07T18:00:00+08:00'))
    sid=session(client)
    body=dict(client_message_id='concurrent',text='同一请求',actions=[new_action()])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:client.post(f'/api/assistant/sessions/{sid}/messages',json=body),range(2)))
    assert all(r.status_code==200 for r in results)
    assert results[0].json()['id']==results[1].json()['id']
    assert client.get('/api/tasks').json()==[]


def test_confirmation_rolls_back_every_write_on_failure(client,test_engine,monkeypatch):
    from app.services import assistant_clock
    from app.routers import assistant
    monkeypatch.setattr(assistant_clock,'assistant_now',lambda:datetime.fromisoformat('2026-10-07T18:00:00+08:00'))
    sid=session(client);p=proposal(client,sid,[new_action()])
    def fail(_):raise RuntimeError('controlled commit failure')
    monkeypatch.setattr(assistant,'bump_revision',fail)
    import pytest
    with pytest.raises(RuntimeError):client.post(f"/api/assistant/proposals/{p['id']}/confirm")
    with Session(test_engine) as db:
        assert list(db.scalars(select(Task)))==[]
        assert list(db.scalars(select(Plan)))==[]
    assert client.get(f'/api/assistant/sessions/{sid}').json()['proposal']['status']=='ready'

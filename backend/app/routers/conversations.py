"""Persistent conversations, messages and read-only AI replies."""
from typing import Literal, Annotated

from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AssistantSession, AssistantMessage, AssistantRun, utc_now
from ..assistant_schemas import ConversationCreate, ConversationPatch, ConversationMessageCreate, ConversationRunAttempt
from ..services import conversation_runs
from ..workspace_schemas import ConversationToolRun
from ..services.planning_state import planning_transaction
from ..services.conversations import error, local_owner, require_conversation, require_idle, summary, message_data, list_conversations

router = APIRouter(prefix='/api/conversations', tags=['Conversations'])
ConversationId = Annotated[int, Path(ge=1, le=9223372036854775807)]


@router.get('')
def listing(q: str | None = Query(default=None, min_length=1, max_length=100),
            archive: Literal['active', 'archived', 'all'] | None = None,
            scope: Literal['conversation', 'planning', 'review', 'profile', 'task_breakdown', 'all'] = 'conversation',
            limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0, le=10000),
            db: Session = Depends(get_db)):
    query = q.strip() if q is not None else None
    if q is not None and not query:
        error('INVALID_SEARCH', '搜索词不能为空。', 422)
    return list_conversations(db, query=query, archive=archive or ('all' if query else 'active'), scope=scope, limit=limit, offset=offset)


@router.post('', status_code=201)
def create(payload: ConversationCreate, db: Session = Depends(get_db)):
    with planning_transaction(db):
        owner = local_owner(db)
        session = db.scalar(select(AssistantSession).where(AssistantSession.owner_id == owner,
            AssistantSession.client_request_id == payload.client_request_id))
        if session is not None:
            require_conversation(db, session.id)
            # Creation identity is immutable; subsequent renames do not break retries.
            return summary(session)
        session = AssistantSession(scope='conversation', week_start=None, owner_id=owner,
            client_request_id=payload.client_request_id, title=payload.title or '新对话',
            title_source='manual' if payload.title else 'default')
        db.add(session)
        db.flush()
        return summary(session)


@router.get('/{id}')
def detail(id: ConversationId, db: Session = Depends(get_db)):
    return summary(require_conversation(db, id))


@router.patch('/{id}')
def change(id: ConversationId, payload: ConversationPatch, db: Session = Depends(get_db)):
    with planning_transaction(db):
        session = require_conversation(db, id)
        if session.version != payload.expected_version:
            error('CONVERSATION_VERSION_CONFLICT', '会话已修改，请重新读取后再提交。')
        changes = payload.model_dump(exclude_unset=True, exclude={'expected_version'})
        if changes.get('archived') and session.archived_at is None:
            require_idle(db, id)
        now = utc_now()
        if 'title' in changes:
            session.title, session.title_source = payload.title, 'manual'
        for field in ('pinned', 'archived'):
            if field in changes:
                name = field + '_at'
                setattr(session, name, (getattr(session, name) or now) if changes[field] else None)
        session.version += 1
        session.updated_at = now
        db.flush()
        return summary(session)


@router.delete('/{id}')
def remove(id: ConversationId, expected_version: int = Query(ge=1, le=9223372036854775807), db: Session = Depends(get_db)):
    with planning_transaction(db):
        session = require_conversation(db, id, include_deleted=True)
        if session.deleted_at is None:
            if session.version != expected_version:
                error('CONVERSATION_VERSION_CONFLICT', '会话已修改，请重新读取后再删除。')
            require_idle(db, id)
            session.deleted_at = session.updated_at = utc_now()
            session.version += 1
            db.flush()
        return {'id': id, 'version': session.version, 'deleted_at': session.deleted_at,
                'deletion_mode': 'soft', 'message': '会话已隐藏，正文保留于本地及整库备份；正式业务记录未删除。'}


@router.get('/{id}/messages')
def messages(id: ConversationId, after_id: int = Query(default=0, ge=0, le=9223372036854775807), before_id: int | None = Query(default=None, ge=1, le=9223372036854775807),latest:bool=False,
             limit: int = Query(default=50, ge=1, le=100), q: str | None = Query(default=None, min_length=1, max_length=100),
             db: Session = Depends(get_db)):
    session = require_conversation(db, id)
    if (before_id is not None and after_id) or latest and (before_id is not None or after_id):
        error('INVALID_PAGINATION', '不能同时使用前向和后向消息游标。', 422)
    conditions = [AssistantMessage.session_id == id, AssistantMessage.owner_id == session.owner_id]
    if q is not None:
        if not q.strip():
            error('INVALID_SEARCH', '搜索词不能为空。', 422)
        conditions.append(AssistantMessage.text.contains(q.strip(), autoescape=True))
    conditions.append(AssistantMessage.id < before_id if before_id is not None else AssistantMessage.id > after_id)
    reverse=before_id is not None or latest
    order = AssistantMessage.id.desc() if reverse else AssistantMessage.id.asc()
    rows = list(db.scalars(select(AssistantMessage).where(*conditions).order_by(order).limit(limit + 1)).all())
    more, rows = len(rows) > limit, rows[:limit]
    cursor = rows[-1].id if more else None
    if reverse:
        rows.reverse()
    return {'items': [message_data(m) for m in rows], 'has_more': more,
            'next_after_id': cursor if not reverse else None, 'next_before_id': cursor if reverse else None}


@router.post('/{id}/messages', status_code=201)
def append(id: ConversationId, payload: ConversationMessageCreate, db: Session = Depends(get_db)):
    with planning_transaction(db):
        session = require_conversation(db, id, write=True)
        if session.scope != 'conversation':
            error('LEGACY_CONVERSATION_READ_ONLY', '旧工具会话请继续使用原业务接口发送消息。')
        duplicate = db.scalar(select(AssistantMessage).where(AssistantMessage.session_id == id,
            AssistantMessage.owner_id == session.owner_id, AssistantMessage.client_message_id == payload.client_message_id))
        if duplicate is not None:
            if duplicate.text != payload.text or duplicate.role != 'user':
                error('IDEMPOTENCY_CONFLICT', '消息标识已用于另一条内容。')
            return message_data(duplicate)
        message = AssistantMessage(session_id=id, owner_id=session.owner_id,
            client_message_id=payload.client_message_id, role='user', text=payload.text)
        db.add(message)
        db.flush()
        return message_data(message)


@router.get('/{id}/runs')
def runs(id: ConversationId, limit: int = Query(default=20, ge=1, le=50), db: Session = Depends(get_db)):
    require_conversation(db, id)
    rows = db.scalars(select(AssistantRun).where(AssistantRun.session_id == id).order_by((AssistantRun.status == 'running').desc(), AssistantRun.id.desc()).limit(limit)).all()
    return {'items': [conversation_runs.run_data(db, r) for r in rows if r.payload.get('kind') == 'conversation']}


@router.post('/{id}/runs', status_code=202)
async def start(id: ConversationId, payload: ConversationToolRun, db: Session = Depends(get_db)):
    result, created = conversation_runs.create_run(db, id, payload)
    if created:
        conversation_runs.launch(db, result['id'])
    return result


@router.get('/{id}/runs/{run_id}')
def run(id: ConversationId, run_id: ConversationId, after: int = Query(default=0, ge=0, le=16000),
        attempt: int | None = Query(default=None, ge=1), db: Session = Depends(get_db)):
    return conversation_runs.run_data(db, conversation_runs.require_run(db, id, run_id), after, attempt)


@router.post('/{id}/runs/{run_id}/stop')
def stop_run(id: ConversationId, run_id: ConversationId, payload: ConversationRunAttempt, db: Session = Depends(get_db)):
    return conversation_runs.stop(db, id, run_id, payload.expected_attempt)


@router.post('/{id}/runs/{run_id}/retry', status_code=202)
async def retry_run(id: ConversationId, run_id: ConversationId, payload: ConversationRunAttempt, db: Session = Depends(get_db)):
    result, created = conversation_runs.retry(db, id, run_id, payload.expected_attempt)
    if created:
        conversation_runs.launch(db, result['id'])
    return result

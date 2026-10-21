"""Local conversation lifecycle. No AI, business writes, or client identity trust."""
from sqlalchemy import select, func, or_, exists, update
from fastapi import HTTPException

from ..models import AssistantSession, AssistantMessage, AssistantProposal, AssistantRun, GrowthChangeDraft, WorkspaceMetadata, utc_now


def error(code, message, status=409):
    raise HTTPException(status, detail={'code': code, 'message': message})


def local_owner(db):
    identity = db.get(WorkspaceMetadata, 1)
    if identity is None:
        error('WORKSPACE_UNAVAILABLE', '本地工作区尚未初始化。', 503)
    return identity.owner_id


def ensure_available(db, session, *, write=False, include_deleted=False):
    if session is None or session.owner_id != local_owner(db):
        error('CONVERSATION_NOT_FOUND', '会话不存在。', 404)
    if session.deleted_at is not None and not include_deleted:
        error('CONVERSATION_DELETED', '会话已删除；正式业务记录不受影响。', 410)
    if write and session.archived_at is not None:
        error('CONVERSATION_ARCHIVED', '请先恢复归档会话。')
    return session


def require_conversation(db, session_id, **options):
    return ensure_available(db, db.get(AssistantSession, session_id), **options)


def require_idle(db, session_id):
    if db.scalar(select(AssistantRun.id).where(AssistantRun.session_id == session_id, AssistantRun.status == 'running').limit(1)):
        error('CONVERSATION_BUSY', '会话仍有运行中的请求，请处理完成后重试。')
    proposal = db.scalar(select(AssistantProposal.id).where(AssistantProposal.session_id == session_id,
        AssistantProposal.status.notin_(['applied', 'discarded', 'superseded'])).limit(1))
    draft = db.scalar(select(GrowthChangeDraft.id).where(GrowthChangeDraft.session_id == session_id,
        GrowthChangeDraft.status.notin_(['applied', 'discarded', 'superseded'])).limit(1))
    if proposal is not None or draft is not None:
        error('CONVERSATION_HAS_DRAFTS', '会话仍有未处理草案，请显式处理后重试；本操作不会自动采用或放弃草案。')


def summary(session):
    return {key: getattr(session, key) for key in (
        'id', 'scope', 'week_start', 'title', 'title_source', 'version', 'created_at',
        'updated_at', 'last_activity_at', 'pinned_at', 'archived_at', 'deleted_at',
    )}


def message_data(message):
    return {key: getattr(message, key) for key in ('id', 'session_id', 'role', 'text', 'content', 'proposal_id', 'created_at')}


def snippet(text, query):
    # Plain text, never HTML. SQLite lower() folds ASCII; Chinese matches literally.
    start = text.lower().find(query.lower())
    start = max(0, start)
    left, right = max(0, start - 35), min(len(text), start + len(query) + 65)
    return ('…' if left else '') + text[left:right] + ('…' if right < len(text) else '')


def list_conversations(db, *, query, archive, scope, limit, offset):
    owner = local_owner(db)
    conditions = [AssistantSession.owner_id == owner, AssistantSession.deleted_at.is_(None)]
    if archive != 'all':
        conditions.append(AssistantSession.archived_at.is_(None) if archive == 'active' else AssistantSession.archived_at.is_not(None))
    if scope != 'all':
        conditions.append(AssistantSession.scope == scope)
    if query:
        message_match = exists(select(AssistantMessage.id).where(AssistantMessage.session_id == AssistantSession.id,
            AssistantMessage.owner_id == owner, AssistantMessage.text.contains(query, autoescape=True)))
        conditions.append(or_(AssistantSession.title.contains(query, autoescape=True), message_match))
    rows = list(db.scalars(select(AssistantSession).where(*conditions).order_by(
        AssistantSession.pinned_at.is_not(None).desc(),
        func.coalesce(AssistantSession.last_activity_at, AssistantSession.created_at).desc(),
        AssistantSession.id.desc()).limit(limit + 1).offset(offset)).all())
    more = len(rows) > limit
    hits = {}
    if query and rows:
        ranked = select(AssistantMessage.id, AssistantMessage.session_id, AssistantMessage.text,
            func.row_number().over(partition_by=AssistantMessage.session_id, order_by=AssistantMessage.id).label('rank')).where(
            AssistantMessage.owner_id == owner, AssistantMessage.session_id.in_([s.id for s in rows[:limit]]),
            AssistantMessage.text.contains(query, autoescape=True)).subquery()
        for hit in db.execute(select(ranked).where(ranked.c.rank <= 4).order_by(ranked.c.id)).mappings():
            hits.setdefault(hit['session_id'], []).append(hit)
    items = []
    for session in rows[:limit]:
        item = summary(session)
        if query:
            matches = hits.get(session.id, [])
            item.update(title_match=query.lower() in session.title.lower(),
                message_matches=[{'message_id': m['id'], 'session_id': session.id, 'snippet': snippet(m['text'], query)} for m in matches[:3]],
                more_message_matches=len(matches) > 3)
        items.append(item)
    return dict(items=items, next_offset=offset + limit if more and offset + limit <= 10000 else None)


def automatic_title(db, session, title, expected_version):
    """Future server-side title proposal contract; manual titles always win."""
    ensure_available(db, session, write=True)
    clean = title.strip()
    if not clean or len(clean) > 160:
        error('INVALID_TITLE', '标题应为1至160个字符。', 422)
    result = db.execute(update(AssistantSession).where(AssistantSession.id == session.id,
        AssistantSession.owner_id == local_owner(db), AssistantSession.version == expected_version,
        AssistantSession.title_source != 'manual', AssistantSession.deleted_at.is_(None),
        AssistantSession.archived_at.is_(None)).values(title=clean, title_source='auto',
            version=AssistantSession.version + 1, updated_at=utc_now()), execution_options={'synchronize_session': False})
    db.refresh(session)
    return result.rowcount == 1

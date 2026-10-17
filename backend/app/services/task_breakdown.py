"""Persistent task suggestions in the existing GrowthChangeDraft store."""
from datetime import timedelta
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from ..models import AssistantMessage, AssistantSession, GrowthChangeDraft, GrowthGoal, PlanningState, Task, TaskGrowthContext, utc_now
from ..task_breakdown_schemas import BreakdownContent, BreakdownCreate, BreakdownResponse, GeneratedBreakdown
from . import assistant_ai, assistant_clock
from .claude_client import AIServiceError
from .planning_state import bump_revision, planning_transaction
from .task_hierarchy import hierarchy_error

SCOPE = "task_breakdown"


def _revision(db):
    state = db.get(PlanningState, 1)
    return state.revision if state else 0


def _goal(db, goal_id):
    if goal_id is not None:
        goal = db.get(GrowthGoal, goal_id)
        if goal is None or goal.status != "active":
            hierarchy_error("INVALID_GOAL", "关联目标不存在或已停用，请重新选择。")


def _dates(content, now):
    if content.parent.deadline <= now or any(child.deadline <= now for child in content.children):
        hierarchy_error("BREAKDOWN_DEADLINE_INVALID", "父子任务截止时间必须在未来，请修改草案。")


def _response(db, draft):
    data = draft.payload
    content = BreakdownContent.model_validate(data["content"])
    original = BreakdownCreate.model_validate(data["input"])
    status = draft.status
    now = assistant_clock.assistant_now()
    if status == "ready" and (draft.source_revision != _revision(db) or content.parent.deadline <= now or any(child.deadline <= now for child in content.children)):
        status = "stale"
    total = sum(child.duration_minutes for child in content.children)
    ids = data.get("created_task_ids", [])
    tasks = list(db.scalars(select(Task).where(Task.id.in_(ids)).order_by(Task.id)).all()) if ids else []
    return BreakdownResponse(id=draft.id, status=status, source=original.source, source_revision=draft.source_revision,
                             version=data["version"], input=original, content=content, total_minutes=total,
                             difference_minutes=total-original.expected_duration_minutes, created_task_ids=ids, tasks=tasks)


def _existing(db, request):
    draft = db.scalar(select(GrowthChangeDraft).where(GrowthChangeDraft.scope == SCOPE,
                      GrowthChangeDraft.payload["input"]["client_request_id"].as_string() == request.client_request_id))
    if draft and draft.payload["input"] != request.model_dump(mode="json"):
        hierarchy_error("IDEMPOTENCY_CONFLICT", "此请求标识已用于另一份输入，请重新开始。", 409)
    return draft


async def create_draft(db, request):
    # No provider request holds a SQLite transaction or writer lock.
    with planning_transaction(db):
        existing = _existing(db, request)
        if existing:
            return _response(db, existing)
        source_revision = _revision(db)
        _goal(db, request.goal_id)
        _dates(BreakdownContent(parent={"title": request.title, "deadline": request.deadline}, children=[]), assistant_clock.assistant_now())
    if request.source == "ai":
        try:
            content = GeneratedBreakdown.model_validate(await assistant_ai.decompose_task(request.model_dump(mode="json"), assistant_clock.assistant_now()))
            _dates(content, assistant_clock.assistant_now())
            if content.parent.deadline != request.deadline:
                raise ValueError("AI changed user deadline")
        except (ValidationError, ValueError, HTTPException):
            raise AIServiceError("AI_RESPONSE_INVALID") from None
    else:
        content = BreakdownContent(parent={"title": request.title, "deadline": request.deadline}, children=[])
    with planning_transaction(db):
        existing = _existing(db, request)
        if existing:
            return _response(db, existing)
        if _revision(db) != source_revision:
            hierarchy_error("STALE_DRAFT", "生成期间资料已变化，请重新生成。", 409)
        session = db.scalar(select(AssistantSession).where(AssistantSession.scope == SCOPE).order_by(AssistantSession.id.desc()))
        if session is None:
            now = assistant_clock.assistant_now()
            session = AssistantSession(scope=SCOPE, week_start=now.date()-timedelta(days=now.weekday()))
            db.add(session)
            db.flush()
        draft = GrowthChangeDraft(session_id=session.id, scope=SCOPE, source_revision=source_revision, status="ready",
                                  payload={"input": request.model_dump(mode="json"), "content": content.model_dump(mode="json"), "version": 1})
        db.add(draft)
        db.flush()
        db.add(AssistantMessage(session_id=session.id, client_message_id=request.client_request_id, role="user", text=request.text,
                                content={"kind": SCOPE, "draft_id": draft.id}))
        return _response(db, draft)


def require_draft(db, draft_id):
    draft = db.get(GrowthChangeDraft, draft_id)
    if draft is None or draft.scope != SCOPE:
        hierarchy_error("DRAFT_NOT_FOUND", "任务拆解草案不存在。", 404)
    return draft


def _ready(db, draft, version):
    if draft.status != "ready":
        hierarchy_error("DRAFT_NOT_READY", "草案已确认或取消，不能再次修改。", 409)
    if draft.source_revision != _revision(db):
        hierarchy_error("STALE_DRAFT", "任务、目标或计划已变化，请重新生成草案。", 409)
    if draft.payload["version"] != version:
        hierarchy_error("DRAFT_VERSION_CONFLICT", "草案已在其他页面修改，请重新加载。", 409)


def edit_draft(db, draft_id, request):
    with planning_transaction(db):
        draft = require_draft(db, draft_id)
        _ready(db, draft, request.version)
        _dates(request.content, assistant_clock.assistant_now())
        draft.payload = {**draft.payload, "content": request.content.model_dump(mode="json"), "version": request.version+1}
        return _response(db, draft)


def confirm_draft(db, draft_id, request):
    with planning_transaction(db):
        draft = require_draft(db, draft_id)
        # A retry returns the same IDs even if the global revision has advanced.
        if draft.status == "applied":
            return _response(db, draft)
        _ready(db, draft, request.version)
        try:
            content = GeneratedBreakdown.model_validate(draft.payload["content"])
        except ValidationError:
            hierarchy_error("INVALID_BREAKDOWN", "请保留至少一个合法子任务，并检查标题、时长与DDL。")
        _dates(content, assistant_clock.assistant_now())
        original = BreakdownCreate.model_validate(draft.payload["input"])
        _goal(db, original.goal_id)
        parent = Task(title=content.parent.title, description=content.parent.description, deadline=content.parent.deadline,
                      duration_minutes=original.expected_duration_minutes, task_kind="container")
        db.add(parent)
        db.flush()
        db.add(TaskGrowthContext(task_id=parent.id, goal_id=original.goal_id, initial_estimate_minutes=original.expected_duration_minutes))
        ids = [parent.id]
        for child in sorted(content.children, key=lambda item: item.sort_order):
            task = Task(**child.model_dump(), parent_task_id=parent.id, task_kind="executable")
            db.add(task)
            db.flush()
            ids.append(task.id)
            db.add(TaskGrowthContext(task_id=task.id, goal_id=original.goal_id, initial_estimate_minutes=child.duration_minutes))
        draft.payload = {**draft.payload, "created_task_ids": ids}
        draft.status, draft.applied_at = "applied", utc_now()
        bump_revision(db)
        db.flush()
        return _response(db, draft)


def discard_draft(db, draft_id, request):
    with planning_transaction(db):
        draft = require_draft(db, draft_id)
        if draft.status == "applied":
            hierarchy_error("DRAFT_APPLIED", "已确认的任务不能通过取消草案撤销。", 409)
        if draft.payload["version"] != request.version:
            hierarchy_error("DRAFT_VERSION_CONFLICT", "草案已变化，请重新加载。", 409)
        draft.status = "discarded"
        return _response(db, draft)


def list_drafts(db):
    return [_response(db, draft) for draft in db.scalars(select(GrowthChangeDraft).where(
        GrowthChangeDraft.scope == SCOPE, GrowthChangeDraft.status.in_(["ready", "stale"])).order_by(GrowthChangeDraft.id.desc())).all()]


def get_draft(db, draft_id):
    return _response(db, require_draft(db, draft_id))

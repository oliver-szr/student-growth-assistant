"""Two-level Task invariants shared by CRUD, planning and backup validation."""
from collections import Counter
from fastapi import HTTPException
from sqlalchemy import select
from ..models import Plan, PlanItem, Task, TaskFeedback, TaskGrowthContext, TaskSchedulingProfile, TaskWorkSession


def hierarchy_error(code, message, status=422):
    raise HTTPException(status, detail={"code": code, "message": message})


def require_executable(task):
    if task.task_kind == "container":
        hierarchy_error("CONTAINER_NOT_EXECUTABLE", "父任务是汇总容器，请选择具体子任务执行或排程。")


def validate_task_change(db, values, task=None):
    """Validate the final state, inside the caller's reserved write transaction."""
    fields = ("task_kind", "parent_task_id", "deadline", "status")
    final = {key: values.get(key, getattr(task, key, None)) for key in fields}
    kind, parent_id = final["task_kind"], final["parent_task_id"]
    own_id = task.id if task else None
    if parent_id is not None:
        if parent_id == own_id:
            hierarchy_error("INVALID_TASK_HIERARCHY", "任务不能引用自身。")
        parent = db.get(Task, parent_id)
        if parent is None:
            hierarchy_error("PARENT_NOT_FOUND", "父任务不存在。")
        if kind != "executable" or parent.task_kind != "container" or parent.parent_task_id is not None:
            hierarchy_error("INVALID_TASK_HIERARCHY", "仅支持父容器与可执行子任务两级结构。")
        if final["deadline"] > parent.deadline:
            hierarchy_error("CHILD_DEADLINE_INVALID", "子任务截止时间不能晚于父任务。")
        count = len(db.scalars(select(Task.id).where(Task.parent_task_id == parent_id, Task.id != own_id)).all())
        if count >= 20:
            hierarchy_error("TOO_MANY_CHILDREN", "每个父任务最多20个子任务。")
    children = list(db.scalars(select(Task).where(Task.parent_task_id == own_id)).all()) if task else []
    if children and (kind != "container" or parent_id is not None):
        hierarchy_error("INVALID_TASK_HIERARCHY", "含子任务的父容器不能降级或嵌套。")
    if any(child.deadline > final["deadline"] for child in children):
        hierarchy_error("CHILD_DEADLINE_INVALID", "新的父任务截止时间会使现有子任务非法，请先调整子任务。")
    if kind == "container" and final["status"] not in (None, "todo"):
        hierarchy_error("CONTAINER_STATUS_DERIVED", "父任务进度由子任务汇总，请分别处理子任务。")
    if task and kind != task.task_kind:
        profile = db.get(TaskSchedulingProfile, task.id)
        facts = any(db.scalar(select(model.id).where(model.task_id == task.id).limit(1)) is not None
                    for model in (PlanItem, TaskFeedback, TaskWorkSession))
        referenced = any(task.id in (ids or []) for ids in db.scalars(select(Plan.task_ids)).all())
        if facts or referenced or (profile and (profile.settings or {}).get("locked")) or task.status != "todo":
            hierarchy_error("TASK_HAS_EXECUTION_FACTS", "任务已有计划、执行记录或锁定，不能直接转换类型；请另建父容器。", 409)


def inherit_context(db, task):
    parent_context = db.get(TaskGrowthContext, task.parent_task_id) if task.parent_task_id else None
    context = TaskGrowthContext(task_id=task.id, initial_estimate_minutes=task.duration_minutes,
                                goal_id=parent_context.goal_id if parent_context else None,
                                family=parent_context.family if parent_context else "",
                                family_confirmed=parent_context.family_confirmed if parent_context else False,
                                deadline_source="external")
    db.add(context)
    return context


def validate_backup_hierarchy(tables):
    tasks = {row["id"]: row for row in tables["tasks"]}
    counts = Counter(row["parent_task_id"] for row in tasks.values() if row["parent_task_id"] is not None)
    for row in tasks.values():
        kind, parent_id = row["task_kind"], row["parent_task_id"]
        if kind not in ("container", "executable") or row["sort_order"] < 0:
            hierarchy_error("INVALID_TASK_HIERARCHY", "备份中的任务类型或顺序无效。")
        if parent_id is not None:
            parent = tasks.get(parent_id)
            if (parent_id == row["id"] or not parent or kind != "executable" or
                    parent["task_kind"] != "container" or parent["parent_task_id"] is not None or
                    row["deadline"] > parent["deadline"] or counts[parent_id] > 20):
                hierarchy_error("INVALID_TASK_HIERARCHY", "备份含非法父任务引用、层级或截止时间。")
        if kind == "container" and row["status"] != "todo":
            hierarchy_error("INVALID_TASK_HIERARCHY", "备份中的父容器状态无效。")
    containers = {row["id"] for row in tasks.values() if row["task_kind"] == "container"}
    if any(row["task_id"] in containers for name in ("plan_items", "task_feedback", "task_work_sessions") for row in tables[name]):
        hierarchy_error("CONTAINER_NOT_EXECUTABLE", "备份将父容器用于排程或执行，已拒绝恢复。")
    if any(containers.intersection(row["task_ids"]) for row in tables["plans"]):
        hierarchy_error("CONTAINER_NOT_EXECUTABLE", "备份计划含父容器。")


def serialize_tasks(db, tasks, contexts=None, feedbacks=None):
    """Explainable counts from real children; never infer completion from the clock."""
    from ..schemas import TaskResponse
    result = [TaskResponse.model_validate(task) for task in tasks]
    parents = [task for task in result if task.task_kind == "container"]
    if not parents:
        return result
    contexts = contexts if contexts is not None else {c.task_id: c for c in db.scalars(select(TaskGrowthContext)).all()}
    feedbacks = feedbacks if feedbacks is not None else list(db.scalars(select(TaskFeedback).where(TaskFeedback.retracted_at.is_(None)).order_by(TaskFeedback.id)).all())
    scheduled = set(db.scalars(select(PlanItem.task_id).join(Plan).where(Plan.status == "confirmed", PlanItem.kind == "task")).all())
    latest, actual = {}, Counter()
    for row in sorted(feedbacks, key=lambda item: item.id):
        if row.retracted_at is None:
            latest[row.task_id] = row.outcome
            actual[row.task_id] += row.actual_minutes or 0
    from ..schemas import TaskProgress
    for parent in parents:
        children = [child for child in result if child.parent_task_id == parent.id]
        parent.progress = TaskProgress(
            total_children=len(children), completed_children=sum(c.status == "done" for c in children),
            cancelled_children=sum(c.status == "cancelled" for c in children),
            partial_children=sum(c.status == "todo" and latest.get(c.id) == "partial" for c in children),
            scheduled_children=sum(c.id in scheduled for c in children), executed_children=sum(actual[c.id] > 0 for c in children),
            total_estimate_minutes=sum(contexts[c.id].initial_estimate_minutes if c.id in contexts else c.duration_minutes for c in children),
            remaining_minutes=sum(c.duration_minutes for c in children if c.status == "todo"),
            actual_minutes=sum(actual[c.id] for c in children))
    return result

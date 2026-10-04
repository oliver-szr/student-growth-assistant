"""Evidence-first habit drafts. The LLM may select observations, never invent rules."""

import asyncio
import hashlib
import logging
import threading
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..models import GrowthInsight, TaskFeedback, TaskWorkSession
from . import assistant_ai, assistant_clock
from .claude_client import AIServiceError
from .planning_state import begin_planning_transaction
from .scheduling_types import SHANGHAI
from .assistant_state import preference_settings

_worker_lock = threading.Lock()
_time_buckets = {
    "morning": ("上午", "08:00", "12:00"),
    "afternoon": ("下午", "12:00", "18:00"),
    "evening": ("晚上", "18:00", "22:00"),
}


def collect_supported_observations(db: Session) -> list[dict]:
    now = assistant_clock.assistant_now().astimezone(SHANGHAI)
    cutoff = now - timedelta(days=28)
    completed = db.scalars(
        select(TaskFeedback)
        .where(
            TaskFeedback.outcome == "completed",
            TaskFeedback.retracted_at.is_(None),
            TaskFeedback.completed_at >= cutoff,
            TaskFeedback.completed_at <= now,
            TaskFeedback.family_confirmed_snapshot.is_(True),
        )
        .order_by(TaskFeedback.id.desc())
    ).all()
    completed_by_task = {}
    for row in completed:
        completed_by_task.setdefault(row.task_id, row)
    if not completed_by_task:
        return []

    sessions = db.scalars(
        select(TaskWorkSession)
        .where(TaskWorkSession.status == "stopped", TaskWorkSession.family_confirmed_snapshot.is_(True))
        .order_by(TaskWorkSession.started_at, TaskWorkSession.id)
    ).all()
    first_session_by_task = {}
    for session in sessions:
        feedback = completed_by_task.get(session.task_id)
        if not feedback or not session.family_snapshot or feedback.family_snapshot != session.family_snapshot:
            continue
        started = session.started_at.astimezone(SHANGHAI)
        if started < cutoff or started > now:
            continue
        first_session_by_task.setdefault(session.task_id, session)

    by_pattern: dict[tuple[str, str], list[tuple[int, str, int]]] = {}
    for task_id, session in first_session_by_task.items():
        started = session.started_at.astimezone(SHANGHAI)
        bucket = next((name for name, (_, start, end) in _time_buckets.items() if start <= started.strftime("%H:%M") < end), None)
        if bucket is None:
            continue
        day = started.date().isoformat()
        by_pattern.setdefault((session.family_snapshot, bucket), []).append((task_id, day, completed_by_task[task_id].id))

    observations = []
    for (family, bucket), rows in sorted(by_pattern.items()):
        task_ids = sorted({row[0] for row in rows})
        days = sorted({row[1] for row in rows})
        family_tasks = {task_id for task_id, session in first_session_by_task.items() if session.family_snapshot == family}
        if len(task_ids) < 5 or len(days) < 3:
            continue
        if len(task_ids) / max(1, len(family_tasks)) < 0.6:
            continue
        label, start, end = _time_buckets[bucket]
        task_label = {"writing": "写作", "reading": "阅读", "practice": "练习", "other": "其他"}.get(family, family)
        count = len(task_ids)
        candidate_id = f"{family}:{bucket}"
        feedback_ids = sorted({row[2] for row in rows})
        observations.append({
            "candidate_id": candidate_id,
            "family": family,
            "family_label": task_label,
            "bucket": bucket,
            "bucket_label": label,
            "start": start,
            "end": end,
            "sample_count": count,
            "family_sample_count": len(family_tasks),
            "active_days": len(days),
            "sample_days": days,
            "task_ids": task_ids,
            "source_feedback_ids": feedback_ids,
            "observation": f"最近28天，有 {count} 项不同的{task_label}任务记录了明确的计时开始时间；其中这一时段占同类计时任务的多数，分布在 {len(days)} 天。",
            "suggestion": f"是否把“{task_label}尽量安排在{label}（{start}–{end}）”保存为长期偏好？计时开始时间只说明你在何时开始记录，不代表该时段效率更高。",
        })
    return observations


def automatic_analysis_is_due(db: Session) -> bool:
    candidates = _without_confirmed_preferences(
        collect_supported_observations(db), preference_settings(db)["settings"]
    )
    if not candidates:
        return False
    for candidate in candidates:
        rows = db.scalars(
            select(GrowthInsight)
            .where(GrowthInsight.proposed_rule["candidate_id"].as_string() == candidate["candidate_id"])
            .order_by(GrowthInsight.id.desc())
        ).all()
        if not rows:
            return True
        latest = rows[0]
        if latest.status in ("draft", "accepted"):
            continue
        if latest.status == "ignored" and len(set(candidate["source_feedback_ids"]) - set(latest.source_feedback_ids)) >= 5:
            return True
    return False


def _without_confirmed_preferences(candidates: list[dict], preferences: dict) -> list[dict]:
    """Avoid asking the user to confirm a window they already chose."""
    windows = preferences.get("task_windows", {}) if isinstance(preferences, dict) else {}
    result = []
    for candidate in candidates:
        existing = windows.get(candidate["family"], []) if isinstance(windows, dict) else []
        same_window = any(
            item.get("start") == candidate["start"] and item.get("end") == candidate["end"]
            for item in existing if isinstance(item, dict)
        )
        if not same_window:
            result.append(candidate)
    return result


def _save_selected(db: Session, candidates: list[dict], chosen_ids: list[str]) -> list[dict]:
    by_id = {item["candidate_id"]: item for item in candidates}
    saved = []
    for candidate_id in chosen_ids:
        item = by_id[candidate_id]
        source_ids = item["source_feedback_ids"]
        signature = hashlib.sha256((candidate_id + ":" + ",".join(map(str, source_ids))).encode()).hexdigest()
        same = db.scalars(select(GrowthInsight).where(GrowthInsight.proposed_rule["candidate_id"].as_string() == candidate_id).order_by(GrowthInsight.id.desc())).all()
        if any(row.status in ("draft", "accepted") for row in same):
            continue
        ignored = next((row for row in same if row.status == "ignored"), None)
        if ignored and len(set(source_ids) - set(ignored.source_feedback_ids)) < 5:
            continue
        if db.scalar(select(GrowthInsight.id).where(GrowthInsight.basis_signature == signature)):
            continue
        rule = {"candidate_id": candidate_id, "family": item["family"], "start": item["start"], "end": item["end"]}
        row = GrowthInsight(
            kind="time_window",
            status="draft",
            observation=item["observation"],
            suggestion=item["suggestion"],
            evidence={key: item[key] for key in ("family_label", "bucket_label", "sample_count", "family_sample_count", "active_days", "sample_days", "task_ids")},
            proposed_rule=rule,
            source_feedback_ids=source_ids,
            basis_signature=signature,
        )
        db.add(row)
        db.flush()
        saved.append({"id": row.id, "status": row.status, "observation": row.observation, "suggestion": row.suggestion, "evidence": row.evidence, "proposed_rule": row.proposed_rule})
    return saved


async def analyze_and_save(db: Session) -> dict:
    observed = collect_supported_observations(db)
    if not observed:
        return {"status": "insufficient_data", "created": [], "message": "目前没有满足样本门槛的习惯观察。需要至少 5 项不同任务、跨 3 天的确认计时记录。"}
    preferences = preference_settings(db)["settings"]
    candidates = _without_confirmed_preferences(observed, preferences)
    if not candidates:
        return {"status": "no_new_suggestion", "created": [], "message": "记录中的时间规律已符合你确认的偏好，暂时没有需要重复确认的新建议。"}
    db.rollback()  # No database transaction or write lock is held during provider I/O.
    try:
        chosen_ids = await assistant_ai.select_growth_insights(candidates, preferences)
    except AIServiceError as error:
        return {"status": "ai_unavailable", "created": [], "error_code": error.code, "message": "有效记录已汇总，但 AI 暂时无法整理建议；可以稍后重试。"}
    begin_planning_transaction(db)
    latest_preferences = preference_settings(db)["settings"]
    latest_candidates = _without_confirmed_preferences(collect_supported_observations(db), latest_preferences)
    latest_ids = {item["candidate_id"] for item in latest_candidates}
    chosen_ids = [item for item in chosen_ids if item in latest_ids]
    created = _save_selected(db, latest_candidates, chosen_ids)
    db.commit()
    return {"status": "drafts_created" if created else "no_new_suggestion", "created": created, "message": "建议已保存为待确认草案；不会自行更改个人偏好。" if created else "没有新的偏好草案需要展示。"}


def launch_automatic_analysis(engine) -> None:
    """Queue a bounded background analysis after confirmed feedback; never blocks task saving."""
    if not _worker_lock.acquire(blocking=False):
        return

    def worker():
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        try:
            with factory() as db:
                asyncio.run(analyze_and_save(db))
        except Exception:
            logging.getLogger(__name__).exception("Automatic growth insight analysis failed")
        finally:
            _worker_lock.release()

    threading.Thread(target=worker, name="growth-insight-analysis", daemon=True).start()

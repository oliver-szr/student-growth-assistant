"""Idempotent, additive data migrations for the growth assistant."""

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..models import (
    AssistantPreference, GrowthGoal, GrowthGoalRevision, GrowthMigration,
    GrowthProfileRevision, GrowthUserProfile, Task, TaskGrowthContext, utc_now,
)
from .planning_state import begin_planning_transaction
from .taxonomy import migrate_taxonomy


def _goal_snapshot(goal: GrowthGoal) -> dict:
    return {
        "title": goal.title,
        "motivation": goal.motivation,
        "goal_type": goal.goal_type,
        "priority": goal.priority,
        "metric_kind": goal.metric_kind,
        "weekly_target": goal.weekly_target,
        "unit_label": goal.unit_label,
        "due_date": goal.due_date.isoformat() if goal.due_date else None,
        "status": goal.status,
    }


def apply_growth_migrations(db: Session) -> None:
    """Apply idempotent, additive V2 data migrations without altering old tables."""
    begin_planning_transaction(db)
    try:
        migrate_taxonomy(db)
        if db.get(GrowthUserProfile, 1) is None:
            db.add(GrowthUserProfile(id=1, direction="", version=1))
        if db.get(GrowthMigration, "growth_v2_baseline") is None:
            goals = list(db.scalars(select(GrowthGoal).order_by(GrowthGoal.id)).all())
            for goal in goals:
                existing = db.scalar(
                    select(GrowthGoalRevision.id).where(
                        GrowthGoalRevision.goal_id == goal.id,
                        GrowthGoalRevision.version == goal.version,
                    )
                )
                if existing is None:
                    db.add(GrowthGoalRevision(goal_id=goal.id, version=goal.version, snapshot=_goal_snapshot(goal)))
            db.add(GrowthMigration(name="growth_v2_baseline", applied_at=utc_now()))

        if db.get(GrowthMigration, "growth_v2_execution_context") is None:
            for task in db.scalars(select(Task).order_by(Task.id)).all():
                if db.get(TaskGrowthContext, task.id) is None:
                    db.add(TaskGrowthContext(
                        task_id=task.id,
                        initial_estimate_minutes=task.duration_minutes,
                        family="",
                        family_confirmed=False,
                        deadline_source="external",
                    ))
            profile = db.get(GrowthUserProfile, 1)
            saved_preferences = db.get(AssistantPreference, 1)
            db.add(GrowthProfileRevision(
                version=profile.version if profile else 1,
                direction=profile.direction if profile else "",
                confirmed_preferences=saved_preferences.settings if saved_preferences else {},
            ))
            db.add(GrowthMigration(name="growth_v2_execution_context", applied_at=utc_now()))
        db.commit()
    except Exception:
        db.rollback()
        raise


def _upgrade_feedback_snapshots(db: Session) -> None:
    """Evolve V2-created tables with additive SQLite columns for live local databases."""
    migration = "growth_v2_feedback_snapshots"
    if db.get(GrowthMigration, migration):
        return

    def add_column(table: str, name: str, definition: str) -> None:
        columns = {row[1] for row in db.execute(text(f"PRAGMA table_info({table})")).all()}
        if name not in columns:
            db.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))

    add_column("task_feedback", "title_snapshot", "VARCHAR NOT NULL DEFAULT ''")
    add_column("task_feedback", "deadline_snapshot", "DATETIME NOT NULL DEFAULT '1970-01-01 00:00:00'")
    add_column("task_feedback", "priority_snapshot", "VARCHAR(20) NOT NULL DEFAULT 'normal'")
    add_column("task_work_sessions", "family_snapshot", "VARCHAR(80) NOT NULL DEFAULT ''")
    add_column("task_work_sessions", "family_confirmed_snapshot", "BOOLEAN NOT NULL DEFAULT 0")
    db.execute(text("""
        UPDATE task_feedback
        SET title_snapshot = COALESCE((SELECT title FROM tasks WHERE tasks.id = task_feedback.task_id), ''),
            deadline_snapshot = COALESCE((SELECT deadline FROM tasks WHERE tasks.id = task_feedback.task_id), deadline_snapshot),
            priority_snapshot = COALESCE((SELECT priority FROM tasks WHERE tasks.id = task_feedback.task_id), priority_snapshot)
        WHERE title_snapshot = '' OR deadline_snapshot = '1970-01-01 00:00:00'
    """))
    db.execute(text("""
        UPDATE task_work_sessions
        SET family_snapshot = COALESCE((SELECT family FROM task_growth_contexts WHERE task_growth_contexts.task_id = task_work_sessions.task_id), ''),
            family_confirmed_snapshot = COALESCE((SELECT family_confirmed FROM task_growth_contexts WHERE task_growth_contexts.task_id = task_work_sessions.task_id), 0)
        WHERE family_snapshot = ''
    """))
    db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS one_running_work_session ON task_work_sessions(status) WHERE status = 'running'"))
    db.add(GrowthMigration(name=migration, applied_at=utc_now()))


def _upgrade_workspace_columns(db: Session) -> None:
    """Add scoped chat and event-time fields without rewriting existing conversations."""
    migration = "growth_v3_workspace_columns"
    if db.get(GrowthMigration, migration):
        return

    def add_column(table: str, name: str, definition: str) -> bool:
        columns = {row[1] for row in db.execute(text(f"PRAGMA table_info({table})")).all()}
        if name in columns:
            return False
        db.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
        return True

    add_column("assistant_sessions", "scope", "VARCHAR(20) NOT NULL DEFAULT 'planning'")
    add_column("assistant_messages", "content", "JSON")
    added_event_time = add_column("task_feedback", "occurred_at", "DATETIME NOT NULL DEFAULT '1970-01-01 00:00:00+00:00'")
    if added_event_time:
        db.execute(text("""
            UPDATE task_feedback
            SET occurred_at = COALESCE(completed_at, created_at)
            WHERE occurred_at = '1970-01-01 00:00:00+00:00'
        """))
    db.add(GrowthMigration(name=migration, applied_at=utc_now()))


def _upgrade_taxonomy_snapshots(db: Session) -> None:
    """Add immutable category display snapshots to feedback and timer records."""
    migration = "growth_v4_category_snapshots"
    if db.get(GrowthMigration, migration):
        return

    def add_column(table: str, name: str, definition: str) -> None:
        columns = {row[1] for row in db.execute(text(f"PRAGMA table_info({table})")).all()}
        if name not in columns:
            db.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))

    add_column("task_feedback", "category_name_snapshot", "VARCHAR(80) NOT NULL DEFAULT '未分类'")
    add_column("task_work_sessions", "category_name_snapshot", "VARCHAR(80) NOT NULL DEFAULT '未分类'")
    db.add(GrowthMigration(name=migration, applied_at=utc_now()))

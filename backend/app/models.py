"""Database tables for tasks, time rules, and persisted weekly plans."""

from datetime import date as DateValue, datetime, time, timezone
from enum import Enum

from sqlalchemy import (
    Boolean, CheckConstraint, Date, Enum as SqlEnum, ForeignKey, Index,
    Integer, JSON, String, Text, Time, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, UTCDateTime


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class TaskPriority(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"


class TaskStatus(str, Enum):
    todo = "todo"
    done = "done"
    cancelled = "cancelled"


class TimeRuleKind(str, Enum):
    course = "course"
    protected = "protected"


class Recurrence(str, Enum):
    weekly = "weekly"
    once = "once"


class PlanStatus(str, Enum):
    candidate = "candidate"
    confirmed = "confirmed"
    superseded = "superseded"


class PlanItemKind(str, Enum):
    task = "task"
    course = "course"


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("task_kind IN ('executable', 'container')", name="task_kind_valid"),
        CheckConstraint("sort_order >= 0", name="task_order_nonnegative"),
        CheckConstraint("parent_task_id IS NULL OR (parent_task_id != id AND task_kind = 'executable')", name="task_parent_not_self"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=True, index=True)
    task_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="executable", server_default="executable")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    deadline: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    priority: Mapped[TaskPriority] = mapped_column(
        SqlEnum(TaskPriority, native_enum=False, create_constraint=True),
        nullable=False,
        default=TaskPriority.normal,
    )
    status: Mapped[TaskStatus] = mapped_column(
        SqlEnum(TaskStatus, native_enum=False, create_constraint=True),
        nullable=False,
        default=TaskStatus.todo,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)


class TimeRule(Base):
    __tablename__ = "time_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[TimeRuleKind] = mapped_column(
        SqlEnum(TimeRuleKind, native_enum=False, create_constraint=True), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    recurrence: Mapped[Recurrence] = mapped_column(
        SqlEnum(Recurrence, native_enum=False, create_constraint=True), nullable=False
    )
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date: Mapped[DateValue | None] = mapped_column(Date, nullable=True)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint("source_revision >= 0", name="plan_revision_nonnegative"),
        Index(
            "one_confirmed_plan_per_week", "week_start", unique=True,
            sqlite_where=text("status = 'confirmed'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    week_start: Mapped[DateValue] = mapped_column(Date, nullable=False)
    status: Mapped[PlanStatus] = mapped_column(
        SqlEnum(PlanStatus, native_enum=False, create_constraint=True), nullable=False,
        default=PlanStatus.candidate,
    )
    based_on_plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    task_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class PlanItem(Base):
    __tablename__ = "plan_items"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'task' AND task_id IS NOT NULL AND time_rule_id IS NULL) OR "
            "(kind = 'course' AND task_id IS NULL AND time_rule_id IS NOT NULL)",
            name="plan_item_reference_kind",
        ),
        CheckConstraint("end_at > start_at", name="plan_item_positive_interval"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"), nullable=False, index=True)
    kind: Mapped[PlanItemKind] = mapped_column(
        SqlEnum(PlanItemKind, native_enum=False, create_constraint=True), nullable=False,
    )
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    time_rule_id: Mapped[int | None] = mapped_column(ForeignKey("time_rules.id"), nullable=True)
    title_snapshot: Mapped[str] = mapped_column(String, nullable=False)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class PlanningState(Base):
    __tablename__ = "planning_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="planning_state_singleton"),
        CheckConstraint("revision >= 0", name="planning_revision_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CourseImport(Base):
    __tablename__ = 'course_imports'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_hash: Mapped[str] = mapped_column(String, unique=True)
    rule_ids: Mapped[list] = mapped_column(JSON)
    warnings: Mapped[list] = mapped_column(JSON)


class TaskSchedulingProfile(Base):
    __tablename__ = 'task_scheduling_profiles'
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id'), primary_key=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)


class AssistantSession(Base):
    __tablename__ = 'assistant_sessions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_start: Mapped[DateValue] = mapped_column(Date)
    latest_proposal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default='planning')
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)


class AssistantProposal(Base):
    __tablename__ = 'assistant_proposals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('assistant_sessions.id'))
    source_revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey('plans.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)


class AssistantMessage(Base):
    __tablename__ = 'assistant_messages'
    __table_args__ = (Index('assistant_message_once', 'session_id', 'client_message_id', unique=True),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('assistant_sessions.id'))
    client_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey('assistant_proposals.id'), nullable=True)
    content: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class GrowthChangeDraft(Base):
    """User-confirmed profile or execution changes proposed through scoped chats."""
    __tablename__ = 'growth_change_drafts'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('assistant_sessions.id'), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='ready')
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class AssistantPreference(Base):
    __tablename__ = 'assistant_preferences'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    settings: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AssistantRun(Base):
    __tablename__ = 'assistant_runs'
    __table_args__ = (Index('assistant_run_idempotency', 'session_id', 'client_message_id', unique=True),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('assistant_sessions.id'), nullable=False)
    client_message_id: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default='running')
    phase: Mapped[str] = mapped_column(String, nullable=False, default='understanding')
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)


class GrowthUserProfile(Base):
    __tablename__ = "growth_user_profiles"
    __table_args__ = (CheckConstraint("id = 1", name="growth_user_profile_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    direction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)


class GrowthProfileRevision(Base):
    __tablename__ = "growth_profile_revisions"
    __table_args__ = (Index("growth_profile_revision_once", "version", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confirmed_preferences: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)


class GrowthInsight(Base):
    __tablename__ = "growth_insights"
    __table_args__ = (Index("growth_insight_signature", "basis_signature"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    observation: Mapped[str] = mapped_column(Text, nullable=False)
    suggestion: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    proposed_rule: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_feedback_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    basis_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class GrowthWeeklyReview(Base):
    __tablename__ = "growth_weekly_reviews"
    __table_args__ = (Index("growth_weekly_review_version", "week_start", "version", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    week_start: Mapped[DateValue] = mapped_column(Date, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    facts: Mapped[dict] = mapped_column(JSON, nullable=False)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)


class GrowthGoal(Base):
    __tablename__ = "growth_goals"
    __table_args__ = (
        CheckConstraint("priority BETWEEN 1 AND 3", name="growth_goal_priority_range"),
        CheckConstraint("weekly_target > 0", name="growth_goal_weekly_target_positive"),
        CheckConstraint("version > 0", name="growth_goal_version_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    motivation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    goal_type: Mapped[str] = mapped_column(String(20), nullable=False, default="long_term")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    metric_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    weekly_target: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_label: Mapped[str] = mapped_column(String(30), nullable=False, default="项")
    due_date: Mapped[DateValue | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)


class GrowthGoalRevision(Base):
    __tablename__ = "growth_goal_revisions"
    __table_args__ = (Index("growth_goal_revision_once", "goal_id", "version", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("growth_goals.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)


class GrowthMigration(Base):
    __tablename__ = "growth_migrations"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)


class TaskGrowthContext(Base):
    """User-confirmed learning context and immutable original estimate per task."""
    __tablename__ = "task_growth_contexts"

    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("growth_goals.id"), nullable=True)
    family: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    family_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    initial_estimate_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    deadline_source: Mapped[str] = mapped_column(String(20), nullable=False, default="external")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)


class TaskFeedback(Base):
    """Append-only, user-confirmed execution feedback; corrections supersede prior rows."""
    __tablename__ = "task_feedback"
    __table_args__ = (
        Index("task_feedback_action_once", "task_id", "client_action_id", unique=True),
        Index("task_feedback_task_created", "task_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    client_action_id: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    actual_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remaining_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title_snapshot: Mapped[str] = mapped_column(String, nullable=False)
    deadline_snapshot: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    priority_snapshot: Mapped[str] = mapped_column(String(20), nullable=False)
    difficulty: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    family_snapshot: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    category_name_snapshot: Mapped[str] = mapped_column(String(80), nullable=False, default="未分类")
    family_confirmed_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    initial_estimate_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    goal_id_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    goal_title_snapshot: Mapped[str | None] = mapped_column(String(160), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("task_feedback.id"), nullable=True)
    retracted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)


class TaskWorkSession(Base):
    """Optional persisted timer. Stopping a timer never completes a task."""
    __tablename__ = "task_work_sessions"
    __table_args__ = (
        Index("work_session_action_once", "task_id", "client_action_id", unique=True),
        Index("one_running_work_session", "status", unique=True, sqlite_where=text("status = 'running'")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    client_action_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    family_snapshot: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    category_name_snapshot: Mapped[str] = mapped_column(String(80), nullable=False, default="未分类")
    family_confirmed_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    accumulated_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    segment_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)


class TaskCategory(Base):
    """Stable task-family identity with a user-editable display name."""
    __tablename__ = "task_categories"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)


class PreferenceRule(Base):
    """One named, editable personal scheduling rule."""
    __tablename__ = "preference_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    category_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    weekdays: Mapped[list | None] = mapped_column(JSON, nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)


class WorkspaceMetadata(Base):
    """Stable browser-cache identity for this database, rotated after restore."""
    __tablename__ = "workspace_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    workspace_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)

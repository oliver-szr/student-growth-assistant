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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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

"""Database tables for Phase 2."""

from datetime import date as DateValue, datetime, time, timezone
from enum import Enum

from sqlalchemy import Boolean, Date, Enum as SqlEnum, Integer, String, Text, Time
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

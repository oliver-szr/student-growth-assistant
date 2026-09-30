"""Small SQLite transaction and global revision helpers; callers own commit."""

from sqlalchemy import text, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from ..models import PlanningState


def begin_planning_transaction(session: Session) -> None:
    """Reserve the SQLite writer before any planning-state or business reads.

    Call first on a fresh request Session. This serializes candidate snapshots,
    CRUD writes, and confirmation, avoiding read-then-write transaction races.
    """
    session.execute(text("BEGIN IMMEDIATE"))


def get_or_create_planning_state(session: Session) -> PlanningState:
    """Initialize id=1 safely, including concurrent first access, without commit."""
    session.execute(
        insert(PlanningState).values(id=1, revision=0).on_conflict_do_nothing(
            index_elements=[PlanningState.id]
        )
    )
    state = session.get(PlanningState, 1, populate_existing=True)
    assert state is not None
    return state


def bump_revision(session: Session) -> int:
    """Increment in SQL in the caller's business transaction, without commit."""
    state = get_or_create_planning_state(session)
    session.execute(
        update(PlanningState).where(PlanningState.id == 1).values(
            revision=PlanningState.revision + 1
        )
    )
    session.refresh(state)
    return state.revision

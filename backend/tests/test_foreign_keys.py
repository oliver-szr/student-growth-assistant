"""SQLite foreign keys are enabled on new connections and reject orphan rows."""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Plan, PlanItem, PlanItemKind, Task, TimeRule
from .test_plans import candidate, create_task
from .test_time_rules import COURSE


def test_foreign_keys_enabled_on_each_connection_and_after_dispose(test_engine: Engine) -> None:
    # Hold both checkouts at once so they cannot reuse the same DBAPI connection.
    with test_engine.connect() as first, test_engine.connect() as second:
        first_dbapi = first.connection.driver_connection
        second_dbapi = second.connection.driver_connection
        assert first_dbapi is not second_dbapi
        assert first.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert second.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1

    test_engine.dispose()
    with test_engine.connect() as replacement:
        replacement_dbapi = replacement.connection.driver_connection
        assert replacement_dbapi is not first_dbapi and replacement_dbapi is not second_dbapi
        assert replacement.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


@pytest.mark.parametrize("reference", ["based_on_plan_id", "plan_id", "task_id", "time_rule_id"])
def test_missing_foreign_key_rejected_and_session_can_write_after_rollback(
    client, test_engine: Engine, reference: str,
) -> None:
    task_id = create_task(client)
    rule = client.post("/api/time-rules", json={**COURSE, "active": False})
    assert rule.status_code == 201
    rule_id = rule.json()["id"]
    saved = candidate(client, [task_id])
    missing_id = 999

    def make_row(reference_id: int) -> Plan | PlanItem:
        if reference == "based_on_plan_id":
            return Plan(
                week_start=date(2026, 10, 5), based_on_plan_id=reference_id,
                source_revision=saved["source_revision"], task_ids=[task_id],
            )
        is_course = reference == "time_rule_id"
        return PlanItem(
            plan_id=reference_id if reference == "plan_id" else saved["id"],
            kind=PlanItemKind.course if is_course else PlanItemKind.task,
            task_id=None if is_course else reference_id if reference == "task_id" else task_id,
            time_rule_id=reference_id if is_course else None,
            title_snapshot="FK test snapshot",
            start_at=datetime(2026, 10, 5, 3, tzinfo=timezone.utc),
            end_at=datetime(2026, 10, 5, 4, tzinfo=timezone.utc),
        )

    target_model, valid_id = {
        "based_on_plan_id": (Plan, saved["id"]),
        "plan_id": (Plan, saved["id"]),
        "task_id": (Task, task_id),
        "time_rule_id": (TimeRule, rule_id),
    }[reference]
    row_model = Plan if reference == "based_on_plan_id" else PlanItem
    with Session(test_engine) as session:
        assert session.connection().exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert session.get(target_model, missing_id) is None
        before = session.scalar(select(func.count()).select_from(row_model))
        session.add(make_row(missing_id))
        with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
            session.commit()
        session.rollback()

        assert session.scalar(select(func.count()).select_from(row_model)) == before
        assert session.get(Plan, saved["id"]) is not None
        # The same Session must accept and commit a row with a real reference.
        valid_row = make_row(valid_id)
        session.add(valid_row)
        session.commit()
        assert session.get(row_model, valid_row.id) is not None
        assert session.scalar(select(func.count()).select_from(row_model)) == before + 1
        assert session.connection().exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1

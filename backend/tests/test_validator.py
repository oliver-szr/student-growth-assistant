from dataclasses import replace
from datetime import date, datetime, time, timezone
import subprocess
import sys

import pytest

from app.services.scheduling_types import SHANGHAI, Assignment, TaskInput, TimeRuleInput
from app.services.validator import validate_schedule


WEEK = date(2026, 10, 5)


def at(day: int = 5, hour: int = 8, minute: int = 0, **changes) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=SHANGHAI, **changes)


def task(task_id: int = 1, **changes) -> TaskInput:
    return replace(TaskInput(task_id, f"Task {task_id}", 30, at(11, 22)), **changes)


def assignment(task_id: int = 1, **changes) -> Assignment:
    return replace(Assignment(task_id, f"Task {task_id}", at(), at(hour=8, minute=30)), **changes)


def rule(rule_id: int = 1, **changes) -> TimeRuleInput:
    return replace(TimeRuleInput(
        rule_id, "course", f"Rule {rule_id}", "weekly", time(8), time(10), weekday=1,
    ), **changes)


def codes(result) -> set[str]:
    assert not result.valid
    return {item.code for item in result.violations}


def test_valid_manual_assignment() -> None:
    item = assignment(start_at=at(hour=9, minute=7), end_at=at(hour=9, minute=24))
    result = validate_schedule(WEEK, [task(duration_minutes=17)], [], [item])
    assert result.valid
    assert result.violations == ()


def test_missing_task() -> None:
    result = validate_schedule(WEEK, [task()], [], [])
    assert codes(result) == {"MISSING_TASK"}
    assert result.violations[0].task_ids == (1,)


def test_duplicate_task_even_when_its_assignments_do_not_overlap() -> None:
    items = [assignment(), assignment(start_at=at(hour=8, minute=30), end_at=at(hour=9))]
    assert codes(validate_schedule(WEEK, [task()], [], items)) == {"DUPLICATE_TASK"}


def test_unselected_task_is_not_accepted() -> None:
    items = [assignment(), assignment(2, start_at=at(hour=9), end_at=at(hour=9, minute=30))]
    result = validate_schedule(WEEK, [task()], [], items)
    assert codes(result) == {"UNSELECTED_TASK"}
    assert result.violations[0].task_ids == (2,)


def test_wrong_duration() -> None:
    result = validate_schedule(WEEK, [task()], [], [assignment(end_at=at(hour=9))])
    assert "WRONG_DURATION" in codes(result)


def test_deadline_violation() -> None:
    result = validate_schedule(WEEK, [task(deadline=at(hour=8, minute=15))], [], [assignment()])
    assert "DEADLINE_VIOLATION" in codes(result)


@pytest.mark.parametrize("day", [4, 12])
def test_outside_selected_week(day) -> None:
    item = assignment(start_at=at(day), end_at=at(day, 8, 30))
    assert "OUTSIDE_WEEK" in codes(validate_schedule(WEEK, [task()], [], [item]))


@pytest.mark.parametrize("start,end", [
    (at(hour=7, minute=30), at(hour=8)),
    (at(hour=22), at(hour=22, minute=30)),
    (at(hour=21, minute=30), at(hour=22, minute=30)),
    (at(hour=21, minute=30), at(6, 8, 30)),
])
def test_working_hours_and_cross_day(start, end) -> None:
    result = validate_schedule(WEEK, [task()], [], [assignment(start_at=start, end_at=end)])
    assert "OUTSIDE_WORKING_HOURS" in codes(result)


@pytest.mark.parametrize("start,end", [
    (at(hour=9, minute=7, second=30), at(hour=9, minute=37, second=30)),
    (at(second=1), at(hour=8, minute=30, second=1)),
    (at(microsecond=1), at(hour=8, minute=30, microsecond=1)),
])
def test_off_grid_including_seconds_and_microseconds(start, end) -> None:
    result = validate_schedule(WEEK, [task()], [], [assignment(start_at=start, end_at=end)])
    assert "OFF_GRID" in codes(result)


def test_task_task_overlap() -> None:
    tasks = [task(1, duration_minutes=60), task(2, duration_minutes=60)]
    items = [assignment(1, end_at=at(hour=9)), assignment(2, start_at=at(hour=8, minute=30), end_at=at(hour=9, minute=30))]
    result = validate_schedule(WEEK, tasks, [], items)
    assert codes(result) == {"TASK_OVERLAP"}
    assert result.violations[0].task_ids == (1, 2)


def test_task_course_overlap() -> None:
    item = assignment(start_at=at(hour=9, minute=6), end_at=at(hour=9, minute=8))
    course = rule(start_time=time(9, 7), end_time=time(9, 23))
    assert "TASK_COURSE_OVERLAP" in codes(validate_schedule(WEEK, [task(duration_minutes=2)], [course], [item]))


@pytest.mark.parametrize("recurrence", ["weekly", "once"])
def test_task_protected_overlap(recurrence) -> None:
    protected = rule(kind="protected", recurrence=recurrence, weekday=1 if recurrence == "weekly" else None, date=WEEK if recurrence == "once" else None)
    assert "TASK_PROTECTED_OVERLAP" in codes(validate_schedule(WEEK, [task()], [protected], [assignment()]))


def test_adjacent_tasks_are_valid_half_open_intervals() -> None:
    tasks = [task(1, duration_minutes=60), task(2, duration_minutes=60)]
    items = [assignment(1, end_at=at(hour=9)), assignment(2, start_at=at(hour=9), end_at=at(hour=10))]
    assert validate_schedule(WEEK, tasks, [], items).valid


def test_task_can_touch_course_and_protected_boundaries() -> None:
    rules = [rule(1, start_time=time(9, 7), end_time=time(9, 23)),
             rule(2, kind="protected", start_time=time(9, 40), end_time=time(10))]
    item = assignment(start_at=at(hour=9, minute=23), end_at=at(hour=9, minute=40))
    assert validate_schedule(WEEK, [task(duration_minutes=17)], rules, [item]).valid


@pytest.mark.parametrize("minute,valid", [(43, True), (44, False)])
def test_seventeen_minutes_must_finish_by_2200(minute, valid) -> None:
    start = at(hour=21, minute=minute)
    item = assignment(start_at=start, end_at=at(hour=22, minute=minute - 43))
    result = validate_schedule(WEEK, [task(duration_minutes=17, deadline=at(hour=22))], [], [item])
    assert result.valid is valid
    if not valid:
        assert {"OUTSIDE_WORKING_HOURS", "DEADLINE_VIOLATION"} <= codes(result)


@pytest.mark.parametrize("changes", [
    {"active": False},
    {"kind": "protected", "recurrence": "once", "weekday": None, "date": date(2026, 10, 4)},
    {"kind": "protected", "recurrence": "once", "weekday": None, "date": date(2026, 10, 12)},
])
def test_inactive_and_out_of_week_rules_are_ignored(changes) -> None:
    assert validate_schedule(WEEK, [task()], [rule(**changes)], [assignment()]).valid


def test_wednesday_course_remains_on_local_wednesday() -> None:
    item = assignment(start_at=at(7, 10).astimezone(timezone.utc), end_at=at(7, 10, 30).astimezone(timezone.utc))
    course = rule(weekday=3, start_time=time(10), end_time=time(12))
    assert "TASK_COURSE_OVERLAP" in codes(validate_schedule(WEEK, [task()], [course], [item]))


def test_utc_assignments_and_deadlines_are_compared_as_instants() -> None:
    item = assignment(start_at=at().astimezone(timezone.utc), end_at=at(hour=8, minute=30).astimezone(timezone.utc))
    selected = task(deadline=item.end_at)
    assert validate_schedule(WEEK, [selected], [], [item]).valid


def test_sunday_2200_is_legal_in_utc_representation() -> None:
    item = assignment(start_at=at(11, 21, 30).astimezone(timezone.utc), end_at=at(11, 22).astimezone(timezone.utc))
    assert validate_schedule(WEEK, [task()], [], [item]).valid


@pytest.mark.parametrize("field,value", [
    ("start_at", datetime(2026, 10, 5, 8)),
    ("end_at", datetime(2026, 10, 5, 8, 30)),
    ("start_at", "2026-10-05T08:00:00+08:00"),
])
def test_rejects_naive_or_non_datetime_assignment(field, value) -> None:
    assert "INVALID_DATETIME" in codes(validate_schedule(WEEK, [task()], [], [assignment(**{field: value})]))


@pytest.mark.parametrize("end", [at(), at(hour=7, minute=30)])
def test_zero_or_reversed_interval_is_invalid(end) -> None:
    assert "INVALID_INTERVAL" in codes(validate_schedule(WEEK, [task()], [], [assignment(end_at=end)]))


@pytest.mark.parametrize("task_id", [True, 0, "1"])
def test_malformed_assignment_id_is_a_violation(task_id) -> None:
    assert "INVALID_ASSIGNMENT" in codes(validate_schedule(WEEK, [task()], [], [assignment(task_id)]))


@pytest.mark.parametrize("status", ["done", "cancelled"])
def test_non_todo_input_is_a_violation(status) -> None:
    assert codes(validate_schedule(WEEK, [task(status=status)], [], [assignment()])) == {"INVALID_TASKS"}


def test_duplicate_selected_ids_are_invalid_inputs() -> None:
    assert codes(validate_schedule(WEEK, [task(), task()], [], [assignment()])) == {"INVALID_TASKS"}


def test_invalid_week_is_a_structured_violation() -> None:
    assert codes(validate_schedule(date(2026, 10, 6), [], [], [])) == {"INVALID_WEEK"}


@pytest.mark.parametrize("rules", [
    [rule(1), rule(2, start_time=time(9), end_time=time(11))],
    [rule(weekday=None)],
    [rule(recurrence="once", weekday=None, date=WEEK)],
])
def test_invalid_or_overlapping_courses_are_structured_violations(rules) -> None:
    assert codes(validate_schedule(WEEK, [], rules, [])) == {"INVALID_TIME_RULES"}


def test_empty_selection_and_assignments_are_valid() -> None:
    assert validate_schedule(WEEK, [], [rule()], []).valid


def test_validator_import_does_not_import_scheduler() -> None:
    check = subprocess.run([
        sys.executable, "-c",
        "import sys; import app.services.validator; assert 'app.services.scheduler' not in sys.modules; assert 'sqlalchemy' not in sys.modules",
    ], capture_output=True, text=True)
    assert check.returncode == 0, check.stderr

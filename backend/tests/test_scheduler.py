from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
import subprocess
import sys

import pytest

from app.services.scheduler import schedule_week
from app.services.scheduling_types import (
    SHANGHAI, Assignment, SchedulingInputError, TaskInput, TimeRuleInput,
)
from app.services.validator import expand_time_rules, validate_schedule


WEEK = date(2026, 10, 5)


def at(day: int = 5, hour: int = 8, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=SHANGHAI)


def task(task_id: int = 1, **changes) -> TaskInput:
    return replace(TaskInput(task_id, f"Task {task_id}", 30, at(11, 22)), **changes)


def rule(rule_id: int = 1, **changes) -> TimeRuleInput:
    return replace(TimeRuleInput(
        rule_id, "course", f"Rule {rule_id}", "weekly", time(8), time(10), weekday=1,
    ), **changes)


def test_single_task_gets_monday_0800_and_passes_validator() -> None:
    tasks = [task()]
    result = schedule_week(WEEK, tasks, [])
    assert result.status == "feasible"
    assert result.assignments == (Assignment(1, "Task 1", at(), at(hour=8, minute=30)),)
    assert result.unscheduled_tasks == ()
    assert validate_schedule(WEEK, tasks, [], result.assignments).valid


def test_deterministic_result_and_immutable_inputs() -> None:
    tasks = [task(3), task(1), task(2)]
    rules = [rule(2, kind="protected", weekday=2), rule(1)]
    before = deepcopy((tasks, rules))
    result = schedule_week(WEEK, tasks, rules)
    assert result == schedule_week(WEEK, tasks, rules)
    assert result == schedule_week(WEEK, list(reversed(tasks)), list(reversed(rules)))
    assert (tasks, rules) == before


def test_earlier_deadline_precedes_priority() -> None:
    tasks = [task(1, priority="high", deadline=at(hour=12)), task(2, priority="low", deadline=at(hour=9))]
    result = schedule_week(WEEK, tasks, [])
    assert [item.task_id for item in result.assignments] == [2, 1]
    assert result.assignments[0].start_at == at()


def test_priority_tie_break_and_low_priority_still_scheduled() -> None:
    tasks = [task(1, priority="low"), task(2, priority="normal"), task(3, priority="high")]
    result = schedule_week(WEEK, tasks, [])
    assert result.status == "feasible"
    assert [item.task_id for item in result.assignments] == [3, 2, 1]


def test_task_id_tie_break() -> None:
    result = schedule_week(WEEK, [task(20), task(5), task(9)], [])
    assert [item.task_id for item in result.assignments] == [5, 9, 20]


def test_equal_instants_with_different_offsets_use_id_tie_break() -> None:
    tasks = [task(2, deadline=at(hour=9)), task(1, deadline=at(hour=9).astimezone(timezone.utc))]
    result = schedule_week(WEEK, tasks, [])
    assert [item.task_id for item in result.assignments] == [1, 2]
    assert all(item.start_at.utcoffset() == timedelta(hours=8) for item in result.assignments)


def test_course_blocks_monday_until_1000() -> None:
    tasks, rules = [task()], [rule()]
    result = schedule_week(WEEK, tasks, rules)
    assert result.assignments[0].start_at == at(hour=10)
    assert validate_schedule(WEEK, tasks, rules, result.assignments).valid


@pytest.mark.parametrize("tasks", [[], [task()]])
def test_overlapping_active_courses_are_rejected_even_without_tasks(tasks) -> None:
    rules = [rule(1, start_time=time(10), end_time=time(12)), rule(2, start_time=time(11), end_time=time(13))]
    with pytest.raises(SchedulingInputError) as error:
        schedule_week(WEEK, tasks, rules)
    assert error.value.code == "INVALID_TIME_RULES"
    assert "overlap" in str(error.value)


def test_adjacent_courses_are_allowed() -> None:
    rules = [rule(1, end_time=time(9)), rule(2, start_time=time(9), end_time=time(10))]
    assert schedule_week(WEEK, [task()], rules).assignments[0].start_at == at(hour=10)


def test_protected_time_blocks_until_0900() -> None:
    result = schedule_week(WEEK, [task()], [rule(kind="protected", end_time=time(9))])
    assert result.assignments[0].start_at == at(hour=9)


def test_weekly_course_and_protected_rules_expand_on_local_weekday() -> None:
    rules = [
        rule(1, kind="protected", end_time=time(22), weekday=1),
        rule(2, kind="protected", end_time=time(22), weekday=2),
        rule(3, weekday=3),
    ]
    result = schedule_week(WEEK, [task()], rules)
    assert result.assignments[0].start_at == at(7, 10)
    midnight_course = rule(4, weekday=3, start_time=time(0), end_time=time(1))
    interval = expand_time_rules(WEEK, [midnight_course])[0]
    assert interval.start_at == at(7, 0)
    assert interval.start_at.isoweekday() == 3
    assert interval.start_at.astimezone(timezone.utc).date() == date(2026, 10, 6)


@pytest.mark.parametrize("occurrence,expected_hour", [(date(2026, 10, 4), 8), (WEEK, 10), (date(2026, 10, 12), 8)])
def test_once_rule_applies_only_inside_local_week(occurrence, expected_hour) -> None:
    rules = [rule(kind="protected", recurrence="once", weekday=None, date=occurrence)]
    assert schedule_week(WEEK, [task()], rules).assignments[0].start_at == at(hour=expected_hour)


@pytest.mark.parametrize("kind", ["course", "protected"])
def test_inactive_rule_does_not_block(kind) -> None:
    assert schedule_week(WEEK, [task()], [rule(kind=kind, active=False)]).assignments[0].start_at == at()


def test_protected_overlap_with_courses_and_other_protected_rules_is_allowed() -> None:
    rules = [rule(1), rule(2, kind="protected"), rule(3, kind="protected", start_time=time(9), end_time=time(11))]
    assert schedule_week(WEEK, [task()], rules).assignments[0].start_at == at(hour=11)


def test_non_grid_rule_end_is_not_rounded_into_available_time() -> None:
    result = schedule_week(WEEK, [task()], [rule(end_time=time(9, 15, 1))])
    assert result.assignments[0].start_at == at(hour=9, minute=30)


def test_task_may_end_exactly_at_aware_utc_deadline() -> None:
    tasks = [task(deadline=at(hour=8, minute=30).astimezone(timezone.utc))]
    result = schedule_week(WEEK, tasks, [])
    assert result.status == "feasible"
    assert result.assignments[0].end_at == tasks[0].deadline


@pytest.mark.parametrize("deadline", [at(hour=9), at(4, 22)])
def test_early_or_pre_week_deadline_is_unschedulable(deadline) -> None:
    result = schedule_week(WEEK, [task(duration_minutes=120, deadline=deadline)], [])
    assert result.status == "unschedulable"
    assert result.assignments == ()
    assert result.unscheduled_tasks[0].task_id == 1
    assert result.unscheduled_tasks[0].reason_code == "NO_SLOT_FOUND"
    assert "under the current MVP scheduling rules" in result.unscheduled_tasks[0].message


def test_long_task_requires_one_continuous_interval() -> None:
    rules = [rule(start_time=time(9), end_time=time(10))]
    result = schedule_week(WEEK, [task(duration_minutes=120)], rules)
    assert result.assignments[0].start_at == at(hour=10)
    assert result.assignments[0].end_at == at(hour=12)


def test_total_free_time_is_not_enough_when_it_is_fragmented() -> None:
    rules = [rule(index + 1, kind="protected", start_time=time(hour), end_time=time(hour + 1)) for index, hour in enumerate(range(9, 22, 2))]
    # Seven free hours remain on Monday, but every free interval is only 60 minutes.
    result = schedule_week(WEEK, [task(duration_minutes=120, deadline=at(hour=22))], rules)
    assert result.status == "unschedulable"
    assert [item.task_id for item in result.unscheduled_tasks] == [1]


def test_later_tasks_skip_occupied_slots_and_can_fill_an_earlier_gap() -> None:
    tasks = [task(1, duration_minutes=60), task(2, duration_minutes=90), task(3)]
    rules = [rule(start_time=time(10), end_time=time(11))]
    result = schedule_week(WEEK, tasks, rules)
    assert [item.start_at for item in result.assignments] == [at(), at(hour=11), at(hour=9)]
    assert validate_schedule(WEEK, tasks, rules, result.assignments).valid


def test_task_at_2100_cannot_cross_day_and_searches_next_day() -> None:
    rules = [rule(kind="protected", end_time=time(21))]
    result = schedule_week(WEEK, [task(duration_minutes=120)], rules)
    assert result.assignments[0].start_at == at(6, 8)
    assert result.assignments[0].end_at == at(6, 10)


@pytest.mark.parametrize("available_day", range(7))
def test_searches_every_day_through_sunday_and_allows_2200_end(available_day) -> None:
    rules = [rule(day + 1, kind="protected", weekday=day + 1, end_time=time(22)) for day in range(available_day)]
    result = schedule_week(WEEK, [task(duration_minutes=840)], rules)
    assert result.status == "feasible"
    assert result.assignments[0].start_at == at(5 + available_day, 8)
    assert result.assignments[0].end_at == at(5 + available_day, 22)


def test_no_available_day_reports_unschedulable() -> None:
    rules = [rule(day + 1, kind="protected", weekday=day + 1, end_time=time(22)) for day in range(7)]
    assert schedule_week(WEEK, [task()], rules).status == "unschedulable"


@pytest.mark.parametrize("status", ["done", "cancelled"])
def test_non_todo_task_is_rejected(status) -> None:
    with pytest.raises(SchedulingInputError) as error:
        schedule_week(WEEK, [task(status=status)], [])
    assert error.value.code == "INVALID_TASKS"


@pytest.mark.parametrize("changes", [
    {"duration_minutes": 45}, {"duration_minutes": 0}, {"duration_minutes": -30},
    {"duration_minutes": 30.0}, {"duration_minutes": True}, {"deadline": datetime(2026, 10, 5, 9)},
    {"deadline": "2026-10-05T09:00:00Z"}, {"priority": "urgent"}, {"id": True}, {"id": 0}, {"title": " "},
])
def test_invalid_task_input_is_rejected_without_rounding(changes) -> None:
    with pytest.raises(SchedulingInputError) as error:
        schedule_week(WEEK, [task(**changes)], [])
    assert error.value.code == "INVALID_TASKS"


def test_duplicate_task_ids_are_rejected() -> None:
    with pytest.raises(SchedulingInputError) as error:
        schedule_week(WEEK, [task(), task()], [])
    assert error.value.code == "INVALID_TASKS"


@pytest.mark.parametrize("week_start", [date(2026, 10, 6), at(), "2026-10-05", date(9999, 12, 27)])
def test_invalid_week_is_rejected(week_start) -> None:
    with pytest.raises(SchedulingInputError) as error:
        schedule_week(week_start, [], [])
    assert error.value.code == "INVALID_WEEK"


@pytest.mark.parametrize("changes", [
    {"weekday": None}, {"weekday": 0}, {"weekday": True}, {"date": WEEK},
    {"recurrence": "once", "weekday": None, "date": WEEK},
    {"kind": "protected", "recurrence": "once", "weekday": None, "date": None},
    {"start_time": time(10)}, {"end_time": time(7)},
    {"start_time": time(8, tzinfo=timezone.utc)}, {"end_time": "10:00"},
    {"kind": "unknown"}, {"active": 1},
])
def test_invalid_rule_input_is_rejected(changes) -> None:
    with pytest.raises(SchedulingInputError) as error:
        schedule_week(WEEK, [], [rule(**changes)])
    assert error.value.code == "INVALID_TIME_RULES"


def test_collects_all_failures_and_discards_partial_assignments() -> None:
    tasks = [task(1, duration_minutes=870), task(2, duration_minutes=30 * 10**30), task(3)]
    result = schedule_week(WEEK, tasks, [])
    assert result.status == "unschedulable"
    assert [item.task_id for item in result.unscheduled_tasks] == [1, 2]
    assert result.assignments == ()


def test_greedy_failure_does_not_prove_that_no_schedule_exists() -> None:
    tasks = [task(1, deadline=at(hour=11, minute=30)), task(2, duration_minutes=90, deadline=at(hour=12))]
    rules = [rule(kind="protected", start_time=time(9, 30), end_time=time(11))]
    result = schedule_week(WEEK, tasks, rules)
    assert result.status == "unschedulable"
    assert [item.task_id for item in result.unscheduled_tasks] == [2]
    alternative = [Assignment(2, "Task 2", at(), at(hour=9, minute=30)), Assignment(1, "Task 1", at(hour=11), at(hour=11, minute=30))]
    assert validate_schedule(WEEK, tasks, rules, alternative).valid


@pytest.mark.parametrize("durations", [[], [30, 60, 120], [840] * 7])
def test_feasible_results_always_pass_independent_validation(durations) -> None:
    tasks = [task(index + 1, duration_minutes=duration) for index, duration in enumerate(durations)]
    result = schedule_week(WEEK, tasks, [])
    assert result.status == "feasible"
    assert validate_schedule(WEEK, tasks, [], result.assignments).valid


def test_services_import_without_database_or_fastapi_dependencies() -> None:
    check = subprocess.run([
        sys.executable, "-c",
        "import sys; import app.services.scheduler; assert 'sqlalchemy' not in sys.modules; assert 'fastapi' not in sys.modules",
    ], capture_output=True, text=True)
    assert check.returncode == 0, check.stderr

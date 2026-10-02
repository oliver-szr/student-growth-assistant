"""Deterministic snapshot facts, identity, ordering and interval boundaries."""

from copy import deepcopy
from datetime import date

import pytest

from app.services.plan_diff import plan_diff


def item(task_id=1, start=8, end=9, title="Read paper", **changes):
    return {"kind": "task", "task_id": task_id, "title_snapshot": title,
            "start_at": f"2026-10-05T{start:02d}:00:00+08:00",
            "end_at": f"2026-10-05T{end:02d}:00:00+08:00", **changes}


def snapshot(items, plan_id=1):
    return {"id": plan_id, "week_start": "2026-10-05", "items": items}


@pytest.mark.parametrize("new_item,category", [
    (item(), "unchanged"), (item(start=10, end=11), "moved"),
    (item(start=7, end=8), "moved"), (item(end=10), "moved"),
    (item(start=7, end=9), "moved"),
])
def test_same_identity_and_both_endpoints(new_item, category):
    result = plan_diff(snapshot([item()]), snapshot([new_item], 2))
    assert result["summary"][f"{category}_count"] == 1
    assert sum(result["summary"].values()) == 1
    if category == "moved":
        assert result["moved"][0]["from_start"] == "2026-10-05T00:00:00Z"
        assert result["moved"][0]["from_end"] == "2026-10-05T01:00:00Z"
        assert set(result["moved"][0]) == {"task_id", "title", "from_start", "from_end", "to_start", "to_end"}


def test_mixed_categories_identity_and_display_snapshots():
    old = snapshot([item(1), item(2, 9, 10), item(3, 10, 11)])
    new = snapshot([item(1, title="Renamed"), item(2, 11, 12), item(4, title="Read paper")], 2)
    before = deepcopy((old, new))
    result = plan_diff(old, new)
    assert result["summary"] == {"added_count": 1, "removed_count": 1, "moved_count": 1, "unchanged_count": 1}
    for category, task_id in (("added", 4), ("removed", 3), ("moved", 2), ("unchanged", 1)):
        assert result[category][0]["task_id"] == task_id
    assert result["unchanged"][0]["title"] == "Renamed"
    assert result["removed"][0]["title"] == "Read paper"
    assert (old, new) == before
    assert "reason" not in str(result)


@pytest.mark.parametrize("old", [None, snapshot([])])
def test_absent_or_empty_baseline(old):
    result = plan_diff(old, snapshot([item()], 2))
    assert result["added"] == [{"task_id": 1, "title": "Read paper", "start_at": "2026-10-05T00:00:00Z", "end_at": "2026-10-05T01:00:00Z"}]
    assert result["confirmed_plan_id"] == (None if old is None else 1)
    assert result["candidate_plan_id"] == 2


@pytest.mark.parametrize("category", ["added", "removed", "moved", "unchanged"])
def test_stable_order_uses_instant_then_task_id(category):
    unordered = [item(5, 10, 11), item(3), item(2)]
    old = [] if category == "added" else unordered
    new = [] if category == "removed" else unordered
    if category == "moved":
        old = [item(entry["task_id"], 12, 13) for entry in unordered]
    result = plan_diff(snapshot(old), snapshot(new, 2))
    assert [entry["task_id"] for entry in result[category]] == [2, 3, 5]
    assert result == plan_diff(snapshot(list(reversed(old))), snapshot(list(reversed(new)), 2))


def test_courses_are_ignored_adjacent_half_open_intervals_and_offsets():
    course = {"kind": "course", "task_id": None}  # need not parse non-task intervals
    protected = {"kind": "protected", "task_id": None}
    old = snapshot([course, protected, item(1), item(2, 9, 10)])
    new = snapshot([item(1, start_at="2026-10-05T00:00:00Z", end_at="2026-10-05T01:00:00Z"), item(2, 9, 10)], 2)
    new["week_start"] = date(2026, 10, 5)
    result = plan_diff(old, new)
    assert result["summary"] == {"added_count": 0, "removed_count": 0, "moved_count": 0, "unchanged_count": 2}


@pytest.mark.parametrize("entries", [
    [item(), item()], [item(task_id=True)], [item(task_id=None)],
    [item(task_id=0)], [item(task_id="1")], [item(start=9, end=9)],
    [item(start=10, end=9)], [item(start_at="2026-10-05T08:00:00")],
])
def test_invalid_task_snapshots_fail(entries):
    with pytest.raises(ValueError):
        plan_diff(None, snapshot(entries))


def test_different_weeks_are_not_comparable():
    new = snapshot([item()], 2)
    new["week_start"] = "2026-10-12"
    with pytest.raises(ValueError, match="same week"):
        plan_diff(snapshot([item()]), new)

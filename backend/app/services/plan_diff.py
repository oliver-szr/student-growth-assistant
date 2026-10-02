"""Pure snapshot comparison. No ORM, provider, scheduler, or inferred causes."""

from collections.abc import Mapping
from datetime import date, datetime, timezone


def instant(value: str | datetime) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("snapshot times must include timezone offsets")
    return result.astimezone(timezone.utc)


def timestamp(value: str | datetime) -> str:
    return instant(value).isoformat().replace("+00:00", "Z")


def tasks_by_id(snapshot: Mapping) -> dict[int, dict]:
    tasks = {}
    for item in snapshot["items"]:
        if item["kind"] != "task":
            continue
        task_id = item["task_id"]
        if type(task_id) is not int or task_id <= 0 or task_id in tasks:
            raise ValueError("task snapshots must have unique positive task IDs")
        start, end = timestamp(item["start_at"]), timestamp(item["end_at"])
        if instant(start) >= instant(end):
            raise ValueError("snapshot interval must have positive length")
        tasks[task_id] = {
            "task_id": task_id, "title": item["title_snapshot"],
            "start_at": start, "end_at": end,
        }
    return tasks


def plan_diff(confirmed: Mapping | None, candidate: Mapping) -> dict:
    """Compare task IDs and saved intervals only, preserving display snapshots."""
    week_start = candidate["week_start"]
    week_start = week_start.isoformat() if isinstance(week_start, date) else week_start
    if confirmed is not None:
        old_week = confirmed["week_start"]
        old_week = old_week.isoformat() if isinstance(old_week, date) else old_week
        if old_week != week_start:
            raise ValueError("plan snapshots must belong to the same week")
    old = tasks_by_id(confirmed) if confirmed is not None else {}
    new = tasks_by_id(candidate)
    added, removed, moved, unchanged = [], [], [], []
    for task_id, item in new.items():
        previous = old.get(task_id)
        if previous is None:
            added.append(item)
        elif (previous["start_at"], previous["end_at"]) == (item["start_at"], item["end_at"]):
            unchanged.append(item)
        else:
            moved.append({
                "task_id": task_id, "title": item["title"],
                "from_start": previous["start_at"], "from_end": previous["end_at"],
                "to_start": item["start_at"], "to_end": item["end_at"],
            })
    removed = [item for task_id, item in old.items() if task_id not in new]
    for items in (added, removed, unchanged):
        items.sort(key=lambda item: (instant(item["start_at"]), item["task_id"]))
    moved.sort(key=lambda item: (instant(item["to_start"]), item["task_id"]))
    return {
        "confirmed_plan_id": confirmed["id"] if confirmed is not None else None,
        "candidate_plan_id": candidate["id"], "week_start": week_start,
        "summary": {
            "added_count": len(added), "removed_count": len(removed),
            "moved_count": len(moved), "unchanged_count": len(unchanged),
        },
        "added": added, "removed": removed, "moved": moved, "unchanged": unchanged,
    }

"""Expand reviewed local course records without guessing ambiguous weeks."""
import hashlib
import json
import re
from datetime import date, timedelta
from sqlalchemy import select
from ..models import TimeRule, CourseImport
from ..schemas import TimeRuleCreate
from .planning_state import bump_revision


def parse_weeks(raw: str) -> list[int]:
    result = set()
    for segment in raw.replace('，', ',').split(','):
        match = re.fullmatch(r'第?(\d+)(?:-(\d+))?周(?:[（(]([单双])[）)])?', segment.strip())
        if not match:
            raise ValueError(f'不能解读周次：{raw}')
        start, end = int(match[1]), int(match[2] or match[1])
        if not 1 <= start <= end <= 30:
            raise ValueError('教学周超出支持范围。')
        result.update(w for w in range(start, end+1) if not match[3] or w % 2 == (1 if match[3] == '单' else 0))
    return sorted(result)


def expand_source(source: dict) -> tuple[list[dict], list[str]]:
    anchor = date.fromisoformat(source['semester_week_1_monday'])
    if anchor.weekday() != 0:
        raise ValueError('第1周起始日期必须是周一。')
    rows, warnings = [], []
    for entry in source['course_entries']:
        if entry['weeks_raw'] == '1-2周,7-8周,11-13周(单)':
            warnings.append(f"{entry['course']}：{entry['weeks_raw']}的限定范围待核对，未导入该条。")
            continue
        for week in parse_weeks(entry['weeks_raw']):
            row = dict(kind='course', title=entry['course'], recurrence='once',
                       date=(anchor+timedelta(weeks=week-1, days=entry['weekday']-1)).isoformat(),
                       start_time=entry['start_time'], end_time=entry['end_time'])
            TimeRuleCreate.model_validate(row)
            rows.append(row)
    warnings.extend(f"{p['course']}：每日时间待补充，未锁定全天。" for p in source.get('practice_entries', []))
    # Validate date-specific course overlaps before any writes.
    ordered = sorted(rows, key=lambda r: (r['date'], r['start_time']))
    for left, right in zip(ordered, ordered[1:]):
        if left['date'] == right['date'] and left['end_time'] > right['start_time']:
            raise ValueError(f"课程冲突：{left['title']} / {right['title']}，{left['date']}")
    return rows, warnings


def import_source(db, source: dict, dry_run: bool = False) -> dict:
    rows, warnings = expand_source(source)
    digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    existing = db.scalar(select(CourseImport).where(CourseImport.source_hash == digest))
    if existing:
        return {'count': len(existing.rule_ids), 'warnings': existing.warnings, 'duplicate': True}
    courses=db.scalars(select(TimeRule).where(TimeRule.kind=='course',TimeRule.active.is_(True))).all()
    for row in rows:
        values=TimeRuleCreate.model_validate(row).model_dump()
        day=values['date']
        for old in courses:
            occurs=(old.recurrence.value=='once' and old.date==day) or (old.recurrence.value=='weekly' and old.weekday==day.isoweekday())
            duplicate=old.recurrence.value=='once' and old.title==values['title'] and old.start_time==values['start_time'] and old.end_time==values['end_time']
            if occurs and not duplicate and old.start_time<values['end_time'] and values['start_time']<old.end_time:
                raise ValueError(f"课程冲突：{old.title} / {row['title']}，{day}")
    if not dry_run:
        ids = []
        for row in rows:
            values = TimeRuleCreate.model_validate(row).model_dump()
            old = db.scalar(select(TimeRule).where(TimeRule.kind == 'course', TimeRule.date == values['date'], TimeRule.title == values['title'], TimeRule.start_time == values['start_time'], TimeRule.end_time == values['end_time']))
            rule = old or TimeRule(**values)
            if not old:
                db.add(rule)
                db.flush()
            ids.append(rule.id)
        db.add(CourseImport(source_hash=digest, rule_ids=ids, warnings=warnings))
        bump_revision(db)
    return {'count': len(rows), 'warnings': warnings, 'duplicate': False}

"""Bounded, read-only calendar and review projections over existing facts."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from sqlalchemy import select, text, exists

from ..models import Task, Plan, PlanItem, TimeRule, GrowthGoal, TaskFeedback, TaskCategory, PlanningState
from .assistant_clock import assistant_now, SHANGHAI
from .assistant_state import time_rules
from .validator import expand_time_rules
from .conversations import error
from .growth_tracking import valid_execution_feedback, unique_completed_feedback, feedback_completion_time


def bounds(start, end, maximum=370):
    if not date(2000, 1, 1) <= start < end <= date(2101, 1, 1) or (end-start).days > maximum:
        error('INVALID_RANGE', f'日期范围应在2000–2100年内，最多{maximum}天，结束日期不包含在范围内。', 422)
    return datetime.combine(start, time.min, SHANGHAI), datetime.combine(end, time.min, SHANGHAI)


def revision(db):
    row = db.get(PlanningState, 1)
    return row.revision if row else 0


def read_snapshot(db):
    # sqlite3 legacy transaction mode does not begin a snapshot for SELECT.
    # Reuse an existing caller transaction; never commit a caller's writes.
    connection=db.connection()
    if not connection.connection.driver_connection.in_transaction:
        connection.execute(text('BEGIN'))


def calendar_events(db, start, end):
    read_snapshot(db)
    a, b = bounds(start, end)
    events, busy = [], []
    rows = db.execute(select(PlanItem, Plan.week_start).join(Plan).where(Plan.status == 'confirmed',
        PlanItem.start_at < b, PlanItem.end_at > a).order_by(PlanItem.id).limit(6001)).all()
    if len(rows) > 6000:
        error('RANGE_TOO_LARGE', '此范围事项过多，请缩小日历范围。', 413)
    current = assistant_now().date(); current_week = current-timedelta(days=current.weekday())
    seen = set()
    for item, week in rows:
        if item.kind == 'course' and week >= current_week:
            continue  # Current courses come from the current rule, never twice.
        kind = 'formal_task' if item.kind == 'task' else 'course_snapshot'
        events.append(dict(id=f'plan:{item.id}', title=item.title_snapshot, start=item.start_at.isoformat(),
            end=item.end_at.isoformat(), allDay=False, kind=kind, task_id=item.task_id, plan_item_id=item.id,
            rule_id=item.time_rule_id, source='正式已保存快照'))
        busy.append((item.start_at.astimezone(SHANGHAI), item.end_at.astimezone(SHANGHAI)))
        seen.add((item.time_rule_id, item.start_at.astimezone(SHANGHAI).date()))
    rules = time_rules(db); names = {r.id: r.title for r in rules}
    week = start-timedelta(days=start.weekday())
    while week < end:
        for item in expand_time_rules(week, rules):
            if not item.start_at < b or not item.end_at > a:
                continue
            if item.kind == 'course' and (item.time_rule_id, item.start_at.date()) in seen:
                continue
            key = f'rule:{item.time_rule_id}:{item.start_at.isoformat()}'
            events.append(dict(id=key, title=names[item.time_rule_id], start=item.start_at.isoformat(),
                end=item.end_at.isoformat(), allDay=False, kind='course' if item.kind=='course' else 'protected',
                rule_id=item.time_rule_id, source='当前周期规则（不推断学期或历史变更）'))
            busy.append((item.start_at, item.end_at))
        if len(events)>6000:error('RANGE_TOO_LARGE','此范围事项过多，请缩小日历范围。',413)
        week += timedelta(days=7)
    tasks = db.scalars(select(Task).where(Task.deadline >= a, Task.deadline < b).order_by(Task.id).limit(6001)).all()
    for task in tasks:
        events.append(dict(id=f'deadline:{task.id}', title='截止 · '+task.title,
            start=task.deadline.astimezone(SHANGHAI).date().isoformat(), allDay=True, kind='deadline',
            task_id=task.id, deadline=task.deadline.isoformat(), source='真实截止日期，不占用时段'))
    for goal in db.scalars(select(GrowthGoal).where(GrowthGoal.due_date>=start, GrowthGoal.due_date<end).order_by(GrowthGoal.id)).all():
        events.append(dict(id=f'goal:{goal.id}', title='目标 · '+goal.title, start=goal.due_date.isoformat(),
            allDay=True, kind='goal', goal_id=goal.id, source='已保存目标日期，不占用时段'))
    if len(events) > 6000:
        error('RANGE_TOO_LARGE', '此范围事项过多，请缩小日历范围。', 413)
    # Free windows only describe 08:00–22:00 after real occupied/protected blocks.
    free = []
    for n in range((end-start).days):
        day=start+timedelta(days=n); left=datetime.combine(day,time(8),SHANGHAI); right=datetime.combine(day,time(22),SHANGHAI)
        cursor=left
        for begin,finish in sorted((max(left,x),min(right,y)) for x,y in busy if x<right and y>left):
            if begin>cursor:free.append(dict(start=cursor.isoformat(),end=begin.isoformat()))
            cursor=max(cursor,finish)
        if cursor<right:free.append(dict(start=cursor.isoformat(),end=right.isoformat()))
    overlaps = []
    active=[]
    for event in sorted((e for e in events if not e['allDay']),key=lambda e:datetime.fromisoformat(e['start'])):
        begin=datetime.fromisoformat(event['start']); finish=datetime.fromisoformat(event['end'])
        active=[e for e in active if datetime.fromisoformat(e['end'])>begin]
        if len(overlaps)<1000:overlaps.extend([e['id'],event['id']] for e in active[:1000-len(overlaps)])
        active.append(event)
    scheduled=exists(select(PlanItem.id).join(Plan).where(Plan.status=='confirmed',PlanItem.task_id==Task.id,PlanItem.end_at>assistant_now()))
    unscheduled=db.scalars(select(Task).where(Task.task_kind=='executable',Task.status=='todo',Task.deadline>=a,Task.deadline<b,~scheduled).order_by(Task.deadline,Task.id).limit(101)).all()
    return dict(start=start,end_exclusive=end,events=events,free=free,conflicts=overlaps,
        unscheduled_tasks=[dict(id=t.id,title=t.title,deadline=t.deadline.isoformat()) for t in unscheduled[:100]],unscheduled_has_more=len(unscheduled)>100,
        revision=revision(db),note='浏览只读，不扩大本周及下周排程范围；截止与目标节点不计入占用。')


def review_facts(db, start, end):
    read_snapshot(db)
    a,b=bounds(start,end,366); now=assistant_now(); as_of=min(now,b)
    tasks={t.id:t for t in db.scalars(select(Task)).all()}
    rows=db.scalars(select(TaskFeedback).where(TaskFeedback.retracted_at.is_(None),
        TaskFeedback.occurred_at<=as_of).order_by(TaskFeedback.id).limit(20001)).all()
    if len(rows)>20000:error('RANGE_TOO_LARGE','执行记录较多，请先整理记录或缩小查询。',413)
    valid=[r for r in rows if r.task_id in tasks and tasks[r.task_id].task_kind=='executable' and valid_execution_feedback(r)]
    completed=[r for r in unique_completed_feedback(valid,as_of) if a<=feedback_completion_time(r)<b]
    effort=[r for r in valid if a<=r.occurred_at<b]
    segments=db.execute(select(PlanItem).join(Plan).join(Task,Task.id==PlanItem.task_id).where(
        Plan.status=='confirmed', PlanItem.kind=='task', Task.task_kind=='executable',PlanItem.start_at<b,PlanItem.end_at>a)).scalars().all()
    latest={}
    for row in valid:latest[row.task_id]=max(latest.get(row.task_id,a-timedelta(days=100000)),row.occurred_at)
    pending={s.task_id for s in segments if s.end_at<=as_of and latest.get(s.task_id,datetime.min.replace(tzinfo=SHANGHAI))<s.end_at}
    done_ids={r.task_id for r in completed}; partial_ids={r.task_id for r in effort if r.outcome=='partial'}
    # A completion is explicit evidence for this task; never mark it pending too.
    pending-={r.task_id for r in unique_completed_feedback(valid,as_of)}
    grouped=defaultdict(list); by_day=defaultdict(list); by_category=defaultdict(list)
    categories={c.key:c.name for c in db.scalars(select(TaskCategory)).all()}
    for r in effort:
        grouped[r.task_id].append(r);by_day[r.occurred_at.astimezone(SHANGHAI).date().isoformat()].append(r)
        by_category[(r.family_snapshot,categories.get(r.family_snapshot) or r.category_name_snapshot or '未分类')].append(r)
    def totals(items):
        known=sum(r.actual_minutes for r in items if r.actual_minutes is not None);unknown=sum(r.actual_minutes is None for r in items)
        return dict(known_minutes=known,unknown_count=unknown,minutes=known if items and not unknown else None,
            feedback_ids=[r.id for r in items],task_ids=sorted({r.task_id for r in items}))
    sources=[]
    for tid in sorted(set(grouped)|done_ids|pending):
        t=tasks[tid]; flags=[]
        if tid in done_ids:flags.append('completed')
        if tid in partial_ids:flags.append('partial')
        if tid in pending:flags.append('pending')
        sources.append(dict(task_id=tid,title=t.title,states=flags or ['recorded'],**totals(grouped[tid]),
            completion_feedback_ids=[r.id for r in completed if r.task_id==tid]))
    goals=[]
    for g in db.scalars(select(GrowthGoal).order_by(GrowthGoal.priority,GrowthGoal.id)).all():
        selected=[r for r in effort if r.goal_id_snapshot==g.id]
        done={r.task_id for r in completed if r.goal_id_snapshot==g.id}
        if selected or done:
            goals.append(dict(id=g.id,title=g.title,metric_kind=g.metric_kind,
                value=sum(r.actual_minutes or 0 for r in selected) if g.metric_kind=='time' else len(done),
                unknown_count=sum(r.actual_minutes is None for r in selected),unit=g.unit_label,
                weekly_target=g.weekly_target, note='范围内已记录进展；周目标仅供参考，不推断历史目标'))
    return dict(start_date=start.isoformat(),end_date_exclusive=end.isoformat(),as_of=as_of.isoformat(),revision=revision(db),
        completed_count=len(done_ids),partial_count=len(partial_ids),pending_count=len(pending),
        **totals(effort),sources=sources,
        by_day=[dict(date=day,**totals(items)) for day,items in sorted(by_day.items())],
        by_category=[dict(key=key,name=name,**totals(items)) for (key,name),items in by_category.items()],goals=goals,
        note='完成按有效完成时间去重，投入按反馈发生时间；待反馈按已结束安排且其后无有效反馈判断，不等于未完成。未知耗时不按零，父容器和计时器不重复计入。')

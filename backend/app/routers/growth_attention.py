"""Task attention ranking and evidence-based duration advice endpoints."""

from datetime import date, datetime, time, timedelta
from math import ceil
import hashlib
import json
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import GrowthGoal, Plan, PlanItem, PlanningState, Task, TaskFeedback, TaskGrowthContext, TaskStatus, TaskSchedulingProfile
from ..services import assistant_clock
from ..services.assistant_state import time_rules
from ..services.scheduling_types import SHANGHAI
from ..services.planning_window import GRID_MINUTES, WINDOW_DAYS, expand_window_rules
from ..services.assistant_scheduler import allowed, old_segments, _split_options

router = APIRouter(prefix="/api/growth", tags=["Personal Growth"])

_URGENCY_ORDER = {"overdue": 0, "critical": 1, "urgent": 2, "soon": 3, "at_risk": 1, "normal": 5}
_IMPORTANCE_ORDER = {"high": 0, "normal": 1, "low": 2}


def _duration_advice(db: Session, task: Task, context: TaskGrowthContext, now: datetime, samples_snapshot=None) -> dict:
    if not context.family_confirmed or not context.family.strip():
        return {"task_id": task.id, "status": "needs_task_type", "suggestion": None, "evidence": {"sample_count": 0}}
    cutoff = now - timedelta(days=28)
    rows = samples_snapshot if samples_snapshot is not None else db.scalars(
        select(TaskFeedback)
        .where(
            TaskFeedback.outcome == "completed",
            TaskFeedback.retracted_at.is_(None),
            TaskFeedback.family_confirmed_snapshot.is_(True),
            TaskFeedback.family_snapshot == context.family,
            TaskFeedback.completed_at >= cutoff,
            TaskFeedback.completed_at <= now,
            TaskFeedback.actual_minutes.is_not(None),
        )
        .order_by(TaskFeedback.id.desc())
    ).all()
    seen: set[int] = set()
    samples = []
    for row in rows:
        if row.family_snapshot != context.family or row.task_id in seen:
            continue
        seen.add(row.task_id)
        baseline = row.initial_estimate_minutes
        if not baseline or not 0.75 * task.duration_minutes <= baseline <= 1.25 * task.duration_minutes:
            continue
        if not row.actual_minutes or row.actual_minutes <= 0 or not row.completed_at:
            continue
        samples.append(row)
    days = sorted({row.completed_at.date().isoformat() for row in samples})
    if len(samples) < 5 or len(days) < 3:
        return {
            "task_id": task.id,
            "status": "insufficient_data",
            "suggestion": None,
            "evidence": {"sample_count": len(samples), "active_days": len(days), "window_days": 28, "family": context.family},
        }
    ratios = sorted(row.actual_minutes / row.initial_estimate_minutes for row in samples)
    q_index = max(0, ceil(0.75 * len(ratios)) - 1)
    conservative_ratio = ratios[q_index]
    raw_minutes = task.duration_minutes * conservative_ratio
    if conservative_ratio < 1:
        raw_minutes = max(raw_minutes, task.duration_minutes * 0.75)
    suggested = ceil(raw_minutes / 30) * 30
    if suggested == task.duration_minutes:
        suggestion = None
        status = "keep_current"
    else:
        suggestion = suggested
        status = "suggested"
    return {
        "task_id": task.id,
        "status": status,
        "current_minutes": task.duration_minutes,
        "suggested_minutes": suggestion,
        "suggestion": suggestion,
        "evidence": {
            "sample_count": len(samples),
            "active_days": len(days),
            "window_days": 28,
            "family": context.family,
            "conservative_actual_estimate_ratio": round(conservative_ratio, 3),
            "sample_task_ids": [row.task_id for row in samples],
            "sample_days": days,
            "reduction_cap_percent": 25,
            "rounding_minutes": 30,
        },
    }


def _availability(task, now, week_start, fixed_busy, assigned, profile):
    """Exact contiguous counts, distinct from bounded representative suggestions.

    Read only: candidates never occupy time. A task's own formal slots are left
    available for its replan; other formal tasks and all fixed rules stay busy.
    Reuse the engine's hard-constraint predicate, never its boolean as a count.
    """
    deadline=task.deadline.astimezone(SHANGHAI)
    end=min(deadline,datetime.combine(week_start+timedelta(days=WINDOW_DAYS),time.min,SHANGHAI))
    busy=sorted(set(fixed_busy+[(a,b) for tid,slots in assigned.items() if tid!=task.id for a,b in slots]))
    spans=[]
    for offset in range(WINDOW_DAYS):
        day=week_start+timedelta(days=offset)
        left=max(now,datetime.combine(day,time(8),SHANGHAI));right=min(end,datetime.combine(day,time(22),SHANGHAI))
        if left>=right:continue
        cursor=left
        for a,b in busy:
            if a>=right:break
            if b<=cursor:continue
            if a>cursor:spans.append((cursor,min(a,right)))
            cursor=max(cursor,b)
            if cursor>=right:break
        if cursor<right:spans.append((cursor,right))
    t=dict(ref=f'task:{task.id}',title=task.title,duration_minutes=task.duration_minutes,
        deadline=deadline.isoformat(),priority=task.priority.value,profile=profile)
    previous=[dict(ref=t['ref'],title=task.title,start_at=a.isoformat(),end_at=b.isoformat()) for a,b in assigned.get(task.id,[]) if b>now]
    old=old_segments(previous);starts=[];grid=[];fitting=0
    for left,right in spans:
        first=left.replace(second=0,microsecond=0)
        if first<left:first+=timedelta(minutes=1)
        first+=timedelta(minutes=(-first.minute)%GRID_MINUTES)
        cursor=first;fit=False
        while cursor+timedelta(minutes=GRID_MINUTES)<=right:
            grid.append(cursor)
            stop=cursor+timedelta(minutes=task.duration_minutes)
            if stop<=right and allowed(t,cursor,stop,week_start,now,busy,old):starts.append(cursor);fit=True
            cursor+=timedelta(minutes=GRID_MINUTES)
        fitting+=fit
    choices=[]
    # Prefer different gaps, then representative early/middle/late starts; no
    # claim that these three UI suggestions enumerate all possible schedules.
    firsts=[next((s for s in starts if a<=s<b),None) for a,b in spans]
    representatives=[s for s in firsts if s is not None]
    if starts:representatives += [starts[0],starts[len(starts)//2],starts[-1]]
    for start in dict.fromkeys(representatives):
        choices.append([dict(ref=t['ref'],title=task.title,start_at=start.isoformat(),end_at=(start+timedelta(minutes=task.duration_minutes)).isoformat())])
        if len(choices)==3:break
    in_progress=any(a<=now<b for a,b in assigned.get(task.id,[]))
    if not choices and profile.get('splittable') and not in_progress:
        choices=_split_options(t,grid,week_start,now,busy,old,{},'balanced')[:3]
    if in_progress:state='in_progress';choices=[]
    elif profile.get('locked') and previous:state='locked';choices=[]
    elif deadline<=now:state='overdue'
    elif choices:state='scheduled' if previous else 'available' if starts else 'split_possible'
    else:state='outside_window' if deadline>end else 'unavailable'
    recommendations=[]
    for items in choices:
        key=hashlib.sha256(json.dumps(items,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:20]
        recommendations.append({'key':key,'items':items})
    return dict(free_interval_count=len(spans),free_minutes=int(sum((b-a).total_seconds()/60 for a,b in spans)),
        free_intervals=[dict(start_at=a.isoformat(),end_at=b.isoformat(),minutes=int((b-a).total_seconds()/60)) for a,b in spans],
        fitting_interval_count=fitting,available_start_count=len(starts),recommendation_count=len(recommendations),recommendations=recommendations,
        availability_state=state,window_end=end.isoformat(),constraints={k:profile[k] for k in ('allowed_windows','fixed_start','locked','splittable','min_block_minutes','max_segments') if profile.get(k)},
        count_note='空闲段只扣除课程、保护时间和其他正式任务；合法起点另检查此任务的指定时段、锁定与5分钟网格。建议只展示最多3种，不是方案总数。')


@router.get("/attention")
def attention_items(db: Session = Depends(get_db)) -> dict:
    from ..services.workspace_views import read_snapshot
    read_snapshot(db)
    now = assistant_clock.assistant_now().astimezone(SHANGHAI)
    week_start = now.date() - timedelta(days=now.weekday())
    rules=time_rules(db)
    expanded = expand_window_rules(week_start, rules)
    fixed_busy = [(entry.start_at, entry.end_at) for entry in expanded]

    confirmed = list(db.scalars(select(Plan).where(Plan.week_start.in_([week_start, week_start+timedelta(days=7)]), Plan.status == "confirmed")).all())
    assigned: dict[int, list[tuple[datetime, datetime]]] = {}
    if confirmed:
        for item in db.scalars(select(PlanItem).where(PlanItem.plan_id.in_([p.id for p in confirmed]))).all():
            if item.kind=='task' and item.task_id:
                assigned.setdefault(item.task_id, []).append((
                    item.start_at.astimezone(SHANGHAI), item.end_at.astimezone(SHANGHAI),
                ))
            elif item.kind!='task':fixed_busy.append((item.start_at.astimezone(SHANGHAI),item.end_at.astimezone(SHANGHAI)))

    profiles={p.task_id:p.settings for p in db.scalars(select(TaskSchedulingProfile)).all()}
    contexts = {item.task_id: item for item in db.scalars(select(TaskGrowthContext)).all()}
    goals = {item.id: item for item in db.scalars(select(GrowthGoal)).all() if item.status == "active"}
    items = []
    for task in db.scalars(select(Task).where(Task.status == TaskStatus.todo, Task.task_kind == 'executable')).all():
        deadline = task.deadline.astimezone(SHANGHAI)
        hours_left = (deadline - now).total_seconds() / 3600
        profile=profiles.get(task.id,{})
        availability=_availability(task,now,week_start,fixed_busy,assigned,profile)
        slots=availability['available_start_count']
        if deadline <= now:
            urgency = "overdue"
            reason = "已经超过你设定的截止时间；截止时间没有被自动修改。"
        elif hours_left <= max(2,task.duration_minutes/60*2) or slots==1:
            urgency = "critical"
            reason = '离截止不远，或可选择的开始时间很少，请尽快核对安排。'
        elif hours_left <= 24:
            urgency = 'urgent'
            reason = ('今天截止' if deadline.date()==now.date() else '24小时内截止')+'，可以先选一个合适的时段。'
        elif hours_left <= 72:
            urgency = "urgent"
            reason = f"三天内截止，预计还需 {task.duration_minutes} 分钟。"
        elif hours_left <= 168:
            urgency = "soon"
            reason = "7天内截止，适合尽早留出一段连续时间。"
        else:
            urgency = "normal"
            reason = "截止时间较远，可以和更紧急的任务一起规划。"
        state=availability['availability_state']
        if state=='in_progress':urgency='normal';reason='任务已经开始，保留原安排；完成后请补充反馈。'
        elif state=='locked':urgency='normal';reason='正式安排已锁定，这里不提供移动建议。可在任务详情中核对。'
        elif state=='scheduled':
            reason='已有正式安排。这里的空闲时间计算不把任务自身重复算作占用。'
        elif state=='split_possible':reason='没有足够长的连续空档，但按已有分段设置可以排下；请先看草案。'
        elif state=='unavailable':urgency='at_risk';reason='截止前的合法时段排不下剩余工作，请检查课程、其他任务或指定时段。'
        elif state=='outside_window':reason='截止较远；这里只检查本周和下周，不代表更远日期没有空闲。'
        elif slots==1 and deadline>now:
            reason='按课程、正式任务和指定条件，只有这段时间能连续完成。'
        elif slots>1 and state!='scheduled':
            reason+=f" 有{availability['fitting_interval_count']}段空闲能连续排下，下面列出少量建议。"
        if profile.get('allowed_windows') or profile.get('fixed_start'):
            reason+=' 此任务已指定可安排时段，其他空闲时间不会自动用于它。'

        context = contexts.get(task.id)
        goal = goals.get(context.goal_id) if context and context.goal_id else None
        items.append({
            "task_id": task.id,
            "title": task.title,
            "deadline": deadline.isoformat(),
            "remaining_minutes": task.duration_minutes,
            "importance": task.priority.value,
            "urgency": urgency,
            "reason": reason,
            **availability,
            "has_confirmed_time": task.id in assigned,
            "goal": {"id": goal.id, "title": goal.title, "priority": goal.priority} if goal else None,
        })

    items.sort(key=lambda item: (
        _URGENCY_ORDER[item["urgency"]],
        _IMPORTANCE_ORDER[item["importance"]],
        (item["goal"]["priority"] if item["goal"] else 4),
        item["deadline"],
        item["task_id"],
    ))
    state = db.get(PlanningState, 1)
    result = {
        "now": now.isoformat(),
        "week_start": week_start.isoformat(),
        "revision": state.revision if state else 0,
        "items": items[:3],
        "overdue_count": sum(item["urgency"] == "overdue" for item in items),
    }
    db.rollback()  # Release this read snapshot before the response is delivered.
    return result


class AttentionDraftRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    client_request_id: str=Field(min_length=1,max_length=100)
    expected_revision: int=Field(strict=True,ge=0)
    recommendation_key: str=Field(pattern=r'^[a-f0-9]{20}$')


@router.post('/tasks/{task_id}/schedule-draft')
def attention_draft(task_id:int,payload:AttentionDraftRequest,db:Session=Depends(get_db)):
    """Explicitly preview one revalidated suggestion via the original pipeline.

    No AI, no formal writes and no confirmation shortcut. Original planning
    scope/Validator/versions apply; the request identity survives a lost reply.
    """
    from ..models import AssistantSession, AssistantProposal, AssistantMessage
    from ..services.conversations import local_owner,error,ensure_available
    from ..services.planning_state import planning_transaction
    from ..services.workspace_drafts import envelope
    from ..assistant_schemas import MessageRequest
    from .assistant import message
    request=payload.model_dump();owner=local_owner(db)
    key='attention:'+hashlib.sha256(f'{task_id}:{payload.client_request_id}'.encode()).hexdigest()
    message_key='attention-preview:'+hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
    session=db.scalar(select(AssistantSession).where(AssistantSession.owner_id==owner,AssistantSession.client_request_id==key))
    if session and session.latest_proposal_id:
        ensure_available(db,session,write=True)
        prior=db.get(AssistantProposal,session.latest_proposal_id)
        original=db.scalar(select(AssistantMessage).where(AssistantMessage.session_id==session.id,AssistantMessage.client_message_id==message_key))
        if prior.payload.get('attention_request')!=request and not original:error('IDEMPOTENCY_CONFLICT','这次请求已经用于另一份建议，请先读取原草案。')
        return envelope(db,'planning',prior.id)
    state=db.get(PlanningState,1)
    if not state or state.revision!=payload.expected_revision:error('STALE_CANDIDATE','安排已变化，请刷新可用时间后重新选择。')
    now=assistant_clock.assistant_now().astimezone(SHANGHAI);week=now.date()-timedelta(days=now.weekday())
    task=db.get(Task,task_id)
    if not task or task.status!=TaskStatus.todo or task.task_kind!='executable':error('TASK_NOT_TODO','任务已完成、取消或不存在，请刷新列表。',422)
    # Reuse the same read calculation without relying on the top-three UI list.
    rules=time_rules(db);busy=[(x.start_at,x.end_at) for x in expand_window_rules(week,rules)]
    assigned={}
    rows=db.execute(select(PlanItem).join(Plan).where(Plan.status=='confirmed',Plan.week_start.in_([week,week+timedelta(days=7)]))).scalars()
    for item in rows:
        if item.kind=='task' and item.task_id:assigned.setdefault(item.task_id,[]).append((item.start_at.astimezone(SHANGHAI),item.end_at.astimezone(SHANGHAI)))
        elif item.kind!='task':busy.append((item.start_at.astimezone(SHANGHAI),item.end_at.astimezone(SHANGHAI)))
    row=db.get(TaskSchedulingProfile,task_id);profile=dict(row.settings or {}) if row else {}
    available=_availability(task,now,week,busy,assigned,profile)
    chosen=next((r for r in available['recommendations'] if r['key']==payload.recommendation_key),None)
    if not chosen:error('STALE_CANDIDATE','这个时间已不可用，请刷新后重新选择。')
    segments=chosen['items'];profile['fixed_start']=segments[0]['start_at']
    if len(segments)>1:profile['allowed_windows']=[{'start_at':x['start_at'],'end_at':x['end_at']} for x in segments]
    db.rollback()
    with planning_transaction(db):
        if db.get(PlanningState,1).revision!=payload.expected_revision:error('STALE_CANDIDATE','安排已变化，请刷新后重新选择。')
        session=db.scalar(select(AssistantSession).where(AssistantSession.owner_id==owner,AssistantSession.client_request_id==key))
        if not session:
            session=AssistantSession(owner_id=owner,scope='planning',week_start=week,client_request_id=key,title='任务日程建议')
            db.add(session);db.flush()
        sid=session.id
    # FastAPI runs this route in a worker. SQLite writer waits must never block
    # the ASGI loop that releases concurrent calendar/attention read snapshots.
    # The old deterministic message coroutine has no Provider work on this path.
    result=asyncio.run(message(sid,MessageRequest(client_message_id=message_key,text=f'为「{task.title}」生成待审核安排。',
        replan=True,actions=[{'op':'update','target':f'task:{task_id}','fields':{'title':task.title,'duration_minutes':task.duration_minutes,
            'deadline':task.deadline.isoformat(),'priority':task.priority.value,'profile':profile}}]),db))
    with planning_transaction(db):
        draft=db.get(AssistantProposal,result['id']);draft.payload={**draft.payload,'attention_request':request}
    return envelope(db,'planning',result['id'])


@router.get("/tasks/{task_id}/duration-advice")
def duration_advice(task_id: int, db: Session = Depends(get_db)) -> dict:
    task = db.get(Task, task_id)
    if task is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="任务不存在")
    from ..services.task_hierarchy import require_executable
    require_executable(task)
    context = db.get(TaskGrowthContext, task_id)
    if context is None:
        context = TaskGrowthContext(task_id=task_id, initial_estimate_minutes=task.duration_minutes)
    return _duration_advice(db, task, context, assistant_clock.assistant_now().astimezone(SHANGHAI))

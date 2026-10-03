"""Build a proposed world without writing Task or Plan rows."""
from copy import deepcopy
from datetime import date, timedelta
from uuid import uuid4
from sqlalchemy import select
from ..models import Task, TimeRule, TaskSchedulingProfile, Plan, PlanItem, CourseImport
from ..schemas import TaskResponse
from .scheduling_types import TimeRuleInput
from .assistant_scheduler import arrange, dt, interval
from . import assistant_clock


def task_library(db):
    profiles={x.task_id:x.settings for x in db.scalars(select(TaskSchedulingProfile)).all()}
    tasks=[]
    for t in db.scalars(select(Task).order_by(Task.id)).all():
        data=TaskResponse.model_validate(t).model_dump(mode='json')
        data['deadline']=t.deadline.astimezone(assistant_clock.SHANGHAI).isoformat()
        tasks.append(dict(ref=f'task:{t.id}',**data,profile=profiles.get(t.id,{})))
    return tasks


def time_rules(db):
    return [TimeRuleInput(id=r.id,kind=r.kind.value,title=r.title,recurrence=r.recurrence.value,start_time=r.start_time,end_time=r.end_time,weekday=r.weekday,date=r.date,active=r.active) for r in db.scalars(select(TimeRule)).all()]


def baseline(db,week):
    p=db.scalar(select(Plan).where(Plan.week_start==week,Plan.status=='confirmed'))
    if not p: return None,[]
    return p.id,[dict(ref=f'task:{x.task_id}',title=x.title_snapshot,start_at=x.start_at.astimezone(assistant_clock.SHANGHAI).isoformat(),end_at=x.end_at.astimezone(assistant_clock.SHANGHAI).isoformat()) for x in db.scalars(select(PlanItem).where(PlanItem.plan_id==p.id,PlanItem.kind=='task')).all()]


def merge_actions(base,incoming):
    result=deepcopy(base)
    for raw in incoming:
        a=deepcopy(raw)
        if a['op']=='add' and not a.get('target'): a['target']='draft:'+str(uuid4())
        existing=next((x for x in result if x.get('target')==a.get('target') and a.get('target')),None)
        if existing:
            for k,v in a['fields'].items():
                if k=='profile' and isinstance(v,dict):
                    existing['fields']['profile']={**(existing['fields'].get('profile') or {}),**v}
                else: existing['fields'][k]=v
        else: result.append(a)
    return result


def proposed_world(db,week,actions):
    tasks={t['ref']:deepcopy(t) for t in task_library(db)}
    questions=[]; focus=set()
    for a in actions:
        ref=a.get('target'); focus.add(ref)
        if a['op']=='add':
            t=tasks.setdefault(ref,dict(ref=ref,title='',duration_minutes=None,deadline=None,priority='normal',status='todo',profile={}))
        elif ref not in tasks:
            questions.append('请选择要修改的具体任务。'); continue
        else: t=tasks[ref]
        for k,v in a['fields'].items():
            if k=='profile': t[k]={**(t.get(k) or {}),**(v or {})}
            else: t[k]=v
    now=assistant_clock.assistant_now()
    current,previous=baseline(db,week)
    byold={x['ref']:x for x in previous}
    relevant=[]; retained=[]; notices=[]
    for ref,t in tasks.items():
        old=byold.get(ref)
        if old and interval(old)[1]<=now:
            retained.append(old)
            if t['status']=='todo': notices.append(f"{t['title']}：过去安排已结束，请核对完成进度。")
            if ref not in focus: continue
        if old and interval(old)[0]<=now<interval(old)[1] and t['status']!='todo':
            retained.append(old)
        if ref in focus:
            missing=[label for key,label in [('title','任务名称'),('duration_minutes','预计剩余时长'),('deadline','具体截止时间')] if not t.get(key)]
            questions.extend(f"{t.get('title') or '新任务'}：请补充{label}。" for label in missing)
        if t['status']!='todo': continue
        if not t.get('deadline') or not t.get('duration_minutes'): continue
        if t['duration_minutes']%30:
            questions.append(f"{t['title']}：请确认30分钟整数倍的时长，不会自动取整。"); continue
        p=t.get('profile') or {}
        if p.get('fixed_start') and (dt(p['fixed_start']).minute%30 or dt(p['fixed_start']).second):
            questions.append(f"{t['title']}：请确认整点或半点的安排时间。"); continue
        if p.get('locked') and not old:
            questions.append(f"{t['title']}：先安排并采用后，才能锁定既有时段。"); continue
        if dt(t['deadline'])<=now:
            notices.append(f"{t['title']}：已逾期，需要处理，未自动修改DDL。")
            if ref in focus: questions.append(f"{t['title']}：请明确新的有效截止时间或标记完成/取消。")
            continue
        if (old and interval(old)[1]>now) or dt(t['deadline']).date()<week+timedelta(days=7) or ref in focus:
            relevant.append(t)
        else: notices.append(f"{t['title']}：后续待安排，尚未保证跨周DDL。")
    return dict(tasks=list(tasks.values()),selected=relevant,previous=previous,retained=retained,current_plan_id=current,questions=questions,notices=notices,now=now)


def world_rules(db,world):
    rules=time_rules(db);next_id=max((r.id for r in rules),default=0)+1
    for x in world['retained']:
        a,b=interval(x)
        if a<=world['now']<b:
            rules.append(TimeRuleInput(id=next_id,kind='protected',title=x['title'],recurrence='once',date=a.date(),start_time=a.time().replace(tzinfo=None),end_time=b.time().replace(tzinfo=None)))
            next_id+=1
    return rules


def build_proposal(db,week,actions,questions=None):
    world=proposed_world(db,week,actions)
    qs=list(dict.fromkeys((questions or [])+world['questions']))
    payload=dict(actions=actions,tasks=world['tasks'],questions=qs,notices=world['notices'],items=[],alternatives=[],diagnostics=[],changes=[],summary='',selected_refs=[t['ref'] for t in world['selected']],retained=world['retained'],removed_refs=[],unmet_preferences=[])
    if qs or not actions:
        payload['status']='needs_input'
        if not qs: payload['questions']=['请输入任务，或使用手动任务卡片。']
        return payload
    result=arrange(week,world['now'],world['selected'],world_rules(db,world),world['previous'])
    payload.update(result)
    old={x['ref']:x for x in world['previous']}
    for x in result['items']:
        before=old.get(x['ref'])
        if before and interval(before)==interval(x): continue
        t=next(t for t in world['selected'] if t['ref']==x['ref'])
        payload['changes'].append(dict(ref=x['ref'],title=x['title'],kind='moved' if before else 'added',before=before,after=x,deadline=t['deadline'],priority=t['priority']))
    for x in result['items']:
        t=next(t for t in world['selected'] if t['ref']==x['ref'])
        windows=(t.get('profile') or {}).get('preferred_windows') or []
        a,b=interval(x)
        if windows and not any(dt(w['start_at'])<=a and b<=dt(w['end_at']) for w in windows):
            payload['unmet_preferences'].append(dict(ref=t['ref'],title=t['title'],requested_windows=windows,assigned=x))
            payload['notices'].append(f"{t['title']}：尽量安排的时间偏好未满足；此方案采用了其他可行时段，可以继续聊天调整。")
    if result['status']=='ready':
        remaining={x['ref'] for x in result['items']+world['retained']}
        for before in world['previous']:
            if before['ref'] not in remaining:
                t=next(t for t in world['tasks'] if t['ref']==before['ref'])
                payload['removed_refs'].append(before['ref'])
                payload['changes'].append(dict(ref=t['ref'],title=t['title'],kind='removed',before=before,after=None,deadline=t['deadline'],priority=t['priority']))
    for a in actions:
        if any(k not in ('profile',) for k in a['fields']):
            payload['notices'].append('任务资料修改将与日程一起在采用时保存。'); break
    if result['status']=='ready':
        lines=[f"{c['title']}：从未来日程移除；任务状态修改会在采用时保存。" if c['kind']=='removed' else f"{c['title']}：{'调整' if c['before'] else '新增'}到{c['after']['start_at'][5:16].replace('T',' ')}，结束不晚于DDL {c['deadline'][5:16].replace('T',' ')}。" for c in payload['changes']]
        payload['summary']='\n'.join(lines) or '任务资料已更新，现有安排可以保留。'
        payload['summary']+='\n所有本轮任务已通过课程冲突、截止时间和锁定校验；优先减少重要任务的移动。'
    else: payload['summary']='\n'.join(x['message'] for x in result['diagnostics'])
    return payload

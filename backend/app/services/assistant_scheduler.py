"""Bounded deterministic replanning. No database or model access."""
from copy import deepcopy
from datetime import datetime, date, time, timedelta
from .scheduling_types import SHANGHAI
from .validator import expand_time_rules

WEIGHTS = {'high':9,'normal':3,'low':1}


def dt(value):
    result = datetime.fromisoformat(value) if isinstance(value,str) else value
    if result.tzinfo is None:
        raise ValueError('时间必须带时区。')
    return result.astimezone(SHANGHAI)


def overlaps(a,b,c,d):
    return a < d and c < b


def interval(item):
    return dt(item['start_at']), dt(item['end_at'])


def item_for(task,start):
    return dict(ref=task['ref'],title=task['title'],start_at=start.isoformat(),end_at=(start+timedelta(minutes=task['duration_minutes'])).isoformat())


def allowed(task,start,end,week,now,busy,old):
    p=task.get('profile') or {}
    before=old.get(task['ref'])
    preserved = bool(before and interval(before)==(start,end))
    if start < now and not (preserved and start <= now < end):
        return False
    if not week <= start.date() < week+timedelta(days=7) or start.date()!=end.date():
        return False
    if start.time()<time(8) or end.time()>time(22) or start.minute%30 or start.second or start.microsecond:
        return False
    if end>dt(task['deadline']) or (end-start).total_seconds()!=task['duration_minutes']*60:
        return False
    if p.get('locked') and not preserved:
        return False
    if before and interval(before)[0] <= now < interval(before)[1] and not preserved:
        return False
    if p.get('fixed_start') and start != dt(p['fixed_start']):
        return False
    windows=p.get('allowed_windows') or []
    if windows and not any(dt(w['start_at'])<=start and end<=dt(w['end_at']) for w in windows):
        return False
    return not any(overlaps(start,end,a,b) for a,b in busy)


def validate_assistant(week,now,tasks,rules,items,previous):
    """Check the claimed complete solution independently of beam search."""
    old={x['ref']:x for x in previous}
    busy=[(x.start_at,x.end_at) for x in expand_time_rules(week,rules)]
    expected={t['ref']:t for t in tasks}
    seen=set(); errors=[]
    for x in items:
        ref=x['ref']
        if ref not in expected or ref in seen:
            errors.append('任务重复或不属于本轮'); continue
        seen.add(ref)
        start,end=interval(x)
        if not allowed(expected[ref],start,end,week,now,busy,old):
            errors.append(f"{expected[ref]['title']}违反时间、截止、冲突或锁定要求")
        busy.append((start,end))
    if seen!=set(expected):
        errors.append('候选遗漏任务')
    return errors


def score(items,tasks,old,week):
    cost=miss=distance=early=0
    for x in items:
        t=tasks[x['ref']]; start,end=interval(x); before=old.get(x['ref'])
        if before and interval(before)!=(start,end):
            cost+=WEIGHTS[t['priority']]
            distance+=abs((start-interval(before)[0]).total_seconds())/60
        preference=(t.get('profile') or {}).get('preferred_windows') or []
        if preference and not any(dt(w['start_at'])<=start and end<=dt(w['end_at']) for w in preference):
            miss+=WEIGHTS[t['priority']]
        early+=(start-datetime.combine(week,time.min,SHANGHAI)).total_seconds()/60
    return cost,miss,distance,early,tuple((x['ref'],x['start_at']) for x in items)


def arrange(week,now,tasks,rules,previous,allow_alternatives=True):
    old={x['ref']:x for x in previous}
    intervals=expand_time_rules(week,rules)
    busy=[(x.start_at,x.end_at) for x in intervals]
    tasks_by_ref={t['ref']:t for t in tasks}
    choices={}; diagnostics=[]
    for t in tasks:
        candidates=[]
        if t['duration_minutes']<=840:
            starts=[datetime.combine(week+timedelta(days=d),time(8),SHANGHAI)+timedelta(minutes=30*s) for d in range(7) for s in range(28)]
            if t['ref'] in old:
                starts.insert(0,interval(old[t['ref']])[0])
            for start in dict.fromkeys(starts):
                x=item_for(t,start)
                if allowed(t,*interval(x),week,now,busy,old): candidates.append(x)
        choices[t['ref']]=candidates
        if not candidates:
            fixed=(t.get('profile') or {}).get('fixed_start')
            message=f"{t['title']}：当前约束下没有可用连续时段。"
            code='NO_CONTINUOUS_SLOT'
            if fixed:
                a=dt(fixed); b=a+timedelta(minutes=t['duration_minutes'])
                names={r.id:r.title for r in rules}
                conflicts=[names[x.time_rule_id] for x in intervals if overlaps(a,b,x.start_at,x.end_at)]
                if conflicts:
                    code='FIXED_TIME_CONFLICT'; message=f"{t['title']}指定的时间与{'、'.join(conflicts)}冲突。"
            diagnostics.append(dict(ref=t['ref'],code=code,message=message))
    empty=dict(items=[],alternatives=[],diagnostics=diagnostics)
    if diagnostics:
        alternatives=[]
        if allow_alternatives:
            for t in tasks:
                if not choices[t['ref']] and (t.get('profile') or {}).get('fixed_start') and not (t.get('profile') or {}).get('locked'):
                    relaxed=deepcopy(tasks)
                    next(x for x in relaxed if x['ref']==t['ref'])['profile'].pop('fixed_start',None)
                    r=arrange(week,now,relaxed,rules,previous,False)
                    if r['status']=='ready':
                        for solution in [r['items']]+r['alternatives']:
                            found=next(x for x in solution if x['ref']==t['ref'])
                            alternatives.append(dict(ref=t['ref'],start_at=found['start_at'],end_at=found['end_at'],requires_time_change=True))
                    break
        empty['alternatives']=alternatives[:2]
        return dict(status='conflict' if alternatives or any(x['code']=='FIXED_TIME_CONFLICT' for x in diagnostics) else 'no_plan',**empty)
    ordered=sorted(tasks,key=lambda t:(len(choices[t['ref']]),max(x['start_at'] for x in choices[t['ref']]) if choices[t['ref']] else '',-WEIGHTS[t['priority']],t['deadline'],t['ref']))
    beam=[[]]; expansions=0; capped=False
    for t in ordered:
        expanded=[]
        for state in beam:
            occupied=[interval(x) for x in state]
            for x in choices[t['ref']]:
                expansions+=1
                if expansions>50000:
                    capped=True; break
                a,b=interval(x)
                if not any(overlaps(a,b,c,d) for c,d in occupied): expanded.append(state+[x])
            if capped: break
        if capped or not expanded:
            return dict(status='no_plan',items=[],alternatives=[],diagnostics=[dict(code='SEARCH_LIMIT' if capped else 'NO_PLAN_FOUND',message='有界搜索未找到完整方案，请调整时间要求或任务范围；这不等于证明无解。')])
        expanded.sort(key=lambda s:score(s,tasks_by_ref,old,week))
        beam=expanded[:64]
    solutions=[]; seen=set()
    for state in beam:
        key=tuple(sorted((x['ref'],x['start_at']) for x in state))
        if key in seen: continue
        seen.add(key)
        if validate_assistant(week,now,tasks,rules,state,previous): raise RuntimeError('排程未通过独立校验')
        solutions.append(sorted(state,key=lambda x:(x['start_at'],x['ref'])))
        if len(solutions)==3: break
    return dict(status='ready',items=solutions[0] if solutions else [],alternatives=solutions[1:],diagnostics=[])

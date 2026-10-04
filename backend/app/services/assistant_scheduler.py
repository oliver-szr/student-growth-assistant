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


def score(items,tasks,old,week,preferences=None,strategy='balanced'):
    moved=miss=avoid=temporary_avoid=buffer=distance=early=goal_penalty=0
    preferences=preferences or {}
    total_weight=sum(WEIGHTS[t['priority']] for t in tasks.values()) or 1
    for x in items:
        t=tasks[x['ref']]; start,end=interval(x); before=old.get(x['ref'])
        if before and interval(before)!=(start,end):
            moved+=WEIGHTS[t['priority']]
            distance+=abs((start-interval(before)[0]).total_seconds())/60
        profile=(t.get('profile') or {})
        preference=profile.get('preferred_windows') or []
        category=(t.get('task_type') or 'other')
        preference_map=preferences.get('task_windows') or {}
        personal=(preference_map.get(category) or [])+(preference_map.get('*') or [])
        start_min=start.hour*60+start.minute; end_min=end.hour*60+end.minute
        weekday=start.isoweekday()
        matches=any(dt(w['start_at'])<=start and end<=dt(w['end_at']) for w in preference) if preference else any(
            start_min>=_clock(w['start']) and end_min<=_clock(w['end']) and (not w.get('weekdays') or weekday in w['weekdays']) for w in personal)
        if (preference or personal) and not matches: miss+=WEIGHTS[t['priority']]
        avoided_windows=(preferences.get('avoid_windows',[]) or [])+(preferences.get('avoid_windows_by_category',{}).get(category,[]) or [])
        if any(start_min<_clock(w['end']) and _clock(w['start'])<end_min and (not w.get('weekdays') or weekday in w['weekdays']) for w in avoided_windows):
            avoid+=WEIGHTS[t['priority']]
        if any(overlaps(start,end,dt(w['start_at']),dt(w['end_at'])) for w in preferences.get('temporary_avoid_windows',[])):
            temporary_avoid+=WEIGHTS[t['priority']]
        desired=float((preferences.get('deadline_buffer_by_category',{}).get(category)
                       if category in preferences.get('deadline_buffer_by_category',{})
                       else preferences.get('deadline_buffer_hours',0)) or 0)
        if t['priority']=='high' and desired:
            remaining=max(0,(dt(t['deadline'])-end).total_seconds()/3600)
            buffer+=WEIGHTS[t['priority']]*max(0,desired-remaining)/desired
        start_minutes=(start-datetime.combine(week,time.min,SHANGHAI)).total_seconds()/60
        early+=start_minutes
        goal=(t.get('goal') or {})
        goal_priority=int(goal.get('priority',3)) if goal else 3
        goal_penalty+=(goal_priority-1)*WEIGHTS[t['priority']]*start_minutes
    mode=preferences.get('adjustment_mode','balanced')
    weights={'balanced':(4,3,3),'preference':(6,2,2),'stable':(2,6,2)}[strategy if strategy in ('preference','stable') else mode]
    preference_penalty=(miss+avoid+temporary_avoid)/(3*total_weight)
    movement_penalty=moved/total_weight
    buffer_penalty=buffer/total_weight
    composite=(weights[0]*preference_penalty+weights[1]*movement_penalty+weights[2]*buffer_penalty)/sum(weights)
    return composite,movement_penalty,preference_penalty,buffer_penalty,goal_penalty,distance,early,tuple((x['ref'],x['start_at']) for x in items)


def _clock(value):
    hour,minute=map(int,value.split(':')[:2])
    return hour*60+minute


def _arrange_single(week,now,tasks,rules,previous,allow_alternatives=True,preferences=None,strategy='balanced'):
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
    ordered=sorted(tasks,key=lambda t:(len(choices[t['ref']]),max(x['start_at'] for x in choices[t['ref']]) if choices[t['ref']] else '',-WEIGHTS[t['priority']],(t.get('goal') or {}).get('priority',3),t['deadline'],t['ref']))
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
        expanded.sort(key=lambda s:score(s,tasks_by_ref,old,week,preferences,strategy))
        beam=expanded[:64]
    solutions=[]; seen=set()
    beam.sort(key=lambda s:score(s,tasks_by_ref,old,week,preferences,strategy))
    for state in beam:
        key=tuple(sorted((x['ref'],x['start_at']) for x in state))
        if key in seen: continue
        seen.add(key)
        if validate_assistant(week,now,tasks,rules,state,previous): raise RuntimeError('排程未通过独立校验')
        solutions.append(sorted(state,key=lambda x:(x['start_at'],x['ref'])))
        if len(solutions)==3: break
    return dict(status='ready',items=solutions[0] if solutions else [],alternatives=solutions[1:],diagnostics=[])


def arrange(week,now,tasks,rules,previous,allow_alternatives=True,preferences=None,include_strategies=False):
    """Return verified schedules; personal preferences only affect soft ranking."""
    if not include_strategies:
        return _arrange_single(week,now,tasks,rules,previous,allow_alternatives,preferences)
    options=[]; errors=[]; seen=set()
    for strategy in ('balanced','preference','stable'):
        result=_arrange_single(week,now,tasks,rules,previous,allow_alternatives,preferences,strategy)
        if result['status']!='ready':
            errors.extend(result.get('diagnostics',[])); continue
        for items in [result['items']]+result['alternatives']:
            key=tuple(sorted((x['ref'],x['start_at']) for x in items))
            if key in seen: continue
            if validate_assistant(week,now,tasks,rules,items,previous):
                raise RuntimeError('排程未通过独立校验')
            seen.add(key)
            options.append({'candidate_id':strategy+':'+str(len(options)),'strategy':strategy,'items':items,'metrics':_metrics(items,tasks,previous,week,preferences)})
            break
    if not options:
        fallback=_arrange_single(week,now,tasks,rules,previous,allow_alternatives,preferences)
        return {**fallback,'candidate_options':[],'search_diagnostics':errors}
    preferred=next((x for x in options if x['strategy']=='balanced'),options[0])
    return {'status':'ready','items':preferred['items'],'alternatives':[x['items'] for x in options if x is not preferred][:2],'candidate_options':options,'diagnostics':[],'search_diagnostics':errors}


def _metrics(items,tasks,previous,week,preferences):
    old={x['ref']:x for x in previous}; by_ref={x['ref']:x for x in tasks}
    total=sum(WEIGHTS[t['priority']] for t in tasks) or 1
    moved=preference_misses=avoided=temporary_avoided=buffer_hours=0
    for item in items:
        task=by_ref[item['ref']]; a,b=interval(item); weight=WEIGHTS[task['priority']]
        if item['ref'] in old and interval(old[item['ref']])!=(a,b): moved+=weight
        category=task.get('task_type') or 'other'; preference_map=(preferences or {}).get('task_windows',{}); windows=(preference_map.get(category) or [])+(preference_map.get('*') or [])
        weekday=a.isoweekday()
        if windows and not any(a.hour*60+a.minute>=_clock(w['start']) and b.hour*60+b.minute<=_clock(w['end']) and (not w.get('weekdays') or weekday in w['weekdays']) for w in windows): preference_misses+=weight
        avoided_windows=((preferences or {}).get('avoid_windows',[]) or [])+((preferences or {}).get('avoid_windows_by_category',{}).get(category,[]) or [])
        if any(a.hour*60+a.minute<_clock(w['end']) and _clock(w['start'])<b.hour*60+b.minute and (not w.get('weekdays') or weekday in w['weekdays']) for w in avoided_windows):avoided+=weight
        if any(overlaps(a,b,dt(w['start_at']),dt(w['end_at'])) for w in (preferences or {}).get('temporary_avoid_windows',[])):temporary_avoided+=weight
        prefs=preferences or {}; buffers=prefs.get('deadline_buffer_by_category',{})
        desired=float((buffers.get(category) if category in buffers else prefs.get('deadline_buffer_hours',0)) or 0)
        if task['priority']=='high' and desired: buffer_hours+=max(0,desired-(dt(task['deadline'])-b).total_seconds()/3600)
    return {'changed_tasks_weight':moved,'total_tasks_weight':total,'preference_misses_weight':preference_misses,'avoided_tasks_weight':avoided,'temporary_avoided_tasks_weight':temporary_avoided,'deadline_buffer_shortfall_hours':round(buffer_hours,1)}

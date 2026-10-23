"""Identify a repair scope and explain facts around the existing scheduler."""

from collections import Counter
from copy import deepcopy
import hashlib
import json

from .assistant_scheduler import dt, interval, old_segments, overlaps, validate_assistant
from .planning_window import expand_window_rules


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def snapshot_signature(items):
    return signature(sorted((x['ref'], x['title'], dt(x['start_at']).isoformat(), dt(x['end_at']).isoformat()) for x in items))


def guard_content(payload):
    scope = payload.get('replanning')
    return {'replanning_guard': signature(scope)} if scope else None


def identify_scope(week, now, tasks, rules, previous, actions, expanded=False, expansion_from=None):
    """Unchanged legal tasks are frozen only in the in-memory local input."""
    old = old_segments(previous)
    focused = {a.get('target'): a.get('fields', {}) for a in actions}
    expanded_rules = expand_window_rules(week, rules)
    names = {r.id: r.title for r in rules}
    preserved, affected, protected, diagnostics = [], [], [], []
    for task in tasks:
        ref = task['ref']
        segments = [x for x in old.get(ref, []) if dt(x['end_at']) > now]
        profile = task.get('profile') or {}
        frozen = bool(profile.get('locked') or any(interval(x)[0] <= now < interval(x)[1] for x in segments))
        if frozen:
            protected.append(ref)
        valid = bool(segments) and not validate_assistant(week, now, [task], rules, segments, previous)
        facts = []
        for segment in segments:
            start, end = interval(segment)
            for rule in expanded_rules:
                if overlaps(start, end, rule.start_at, rule.end_at):
                    facts.append(dict(
                        code='TIME_RULE_CONFLICT', ref=ref, task_id=task.get('id'), constraint=rule.kind,
                        time_rule_id=rule.time_rule_id, blocking_ref=f'rule:{rule.time_rule_id}',
                        original_interval=segment,
                        conflict_interval=dict(start_at=rule.start_at.isoformat(), end_at=rule.end_at.isoformat()),
                        message=f"{task['title']}的原安排与{names[rule.time_rule_id]}（{rule.start_at:%m-%d %H:%M}–{rule.end_at:%H:%M}）重叠。",
                        options=['edit_task', 'review_time_rule'],
                    ))
            if end > dt(task['deadline']):
                facts.append(dict(code='DEADLINE_VIOLATION', ref=ref, constraint='deadline', original_interval=segment,
                                  deadline=task['deadline'], message=f"{task['title']}的原安排晚于当前截止时间。", options=['edit_task', 'review_deadline']))
        if frozen and not valid:
            facts.append(dict(code='LOCKED_SEGMENT', ref=ref, constraint='locked_or_started',
                              original_intervals=segments, message=f"{task['title']}已锁定或已经开始，不能通过扩大范围移动。", options=['edit_task', 'review_time_rule']))
        if not frozen and (expanded or ref in focused or not valid):
            affected.append(ref)
            if not facts:
                code = ('CURRENT_TIME_ADVANCED' if not segments and ref in old else 'NEW_TASK' if not segments else 'EXPLICIT_REPLAN' if ref in focused and not focused[ref]
                        else 'TASK_UPDATED' if ref in focused else 'SCOPE_EXPANDED' if expanded else 'WORK_REQUIREMENTS_CHANGED')
                text = {'NEW_TASK': '需要安排确认过的剩余工作', 'EXPLICIT_REPLAN': '本轮明确请求重新安排',
                        'CURRENT_TIME_ADVANCED': '原安排已结束，本轮仅重新安排明确确认的剩余工作',
                        'TASK_UPDATED': '本轮任务资料已修改', 'SCOPE_EXPANDED': '经你允许参与扩大范围的调整',
                        'WORK_REQUIREMENTS_CHANGED': '原片段不满足当前时长、分段或时段要求'}[code]
                facts.append(dict(code=code, ref=ref, constraint='task', original_intervals=old.get(ref,[]), message=f"{task['title']}：{text}。", options=['edit_task']))
        elif valid:
            preserved.append(ref)
        diagnostics.extend(facts)
    return dict(mode='expanded' if expanded else 'local', affected_refs=sorted(affected),
                preserved_refs=sorted(preserved), protected_refs=sorted(protected),
                formal_snapshot_signature=snapshot_signature(previous), expansion_from=expansion_from,
                requires_expansion=False), diagnostics


def constrained_tasks(tasks, scope):
    result = deepcopy(tasks)
    frozen = set(scope['preserved_refs']) | set(scope['protected_refs'])
    for task in result:
        if task['ref'] in frozen:
            task['profile'] = {**(task.get('profile') or {}), 'locked': True}
    return result


def planning_previous(world):
    formal = world.get('formal_previous', world['previous'])
    refs = {x['ref'] for x in formal}
    return formal + [x for x in world['previous'] if x['ref'] not in refs]


def movement_metrics(items, previous):
    old, new = old_segments(previous), old_segments(items)
    moved, segments, shift, overlap, total = 0, 0, 0, 0, 0
    for ref in old.keys() & new.keys():
        before, after = sorted(map(interval, old[ref])), sorted(map(interval, new[ref]))
        if before != after:
            moved += 1
            segments += max(sum((Counter(before) - Counter(after)).values()), sum((Counter(after) - Counter(before)).values()))
            shift += sum(abs((a[0] - b[0]).total_seconds()) / 60 for a, b in zip(before, after))
        total += max(sum((b-a).total_seconds()/60 for a,b in before), sum((b-a).total_seconds()/60 for a,b in after))
        overlap += sum(max(0, (min(b,d)-max(a,c)).total_seconds()/60) for a,b in before for c,d in after)
    return dict(moved_task_count=moved, moved_segment_count=segments, total_shift_minutes=round(shift, 2),
                overlap_minutes=round(overlap, 2), overlap_ratio=round(overlap/total, 4) if total else None)


def change_groups(items, world, scope, diagnostics, ready):
    old = old_segments(world.get('formal_previous', world['previous']))
    new = old_segments(items + world['retained']) if ready else {ref: old[ref] for ref in scope['preserved_refs'] if ref in old}
    tasks = {t['ref']: t for t in world['tasks']}
    groups = dict(preserved=[], moved=[], added=[], pending=[], removed=[])
    for ref in sorted(old.keys() | new.keys()):
        before, after = old.get(ref, []), new.get(ref, [])
        if not ready and ref not in new:
            continue
        kind = ('preserved' if sorted(map(interval, before)) == sorted(map(interval, after)) else
                'added' if not before else 'removed' if not after else 'moved')
        groups[kind].append(dict(ref=ref, title=tasks.get(ref, {}).get('title') or (after or before)[0]['title'],
                                 before_segments=before, after_segments=after,
                                 reasons=[d for d in diagnostics if d.get('ref') == ref]))
    if not ready:
        for task in world['selected']:
            if task['ref'] not in scope['preserved_refs']:
                groups['pending'].append(dict(ref=task['ref'], title=task['title'], remaining_minutes=task['duration_minutes'],
                                              reasons=[d for d in diagnostics if d.get('ref') == task['ref']]))
    for pending in world.get('pending_work',[]):
        ref=pending['ref']
        groups['preserved']=[x for x in groups['preserved'] if x['ref']!=ref]
        groups['pending'].append({**pending,'before_segments':old.get(ref,[]),'reasons':[dict(code=pending['code'],message=pending['message'])]})
    groups['counts'] = {key: len({x['ref'] for x in groups[key]}) for key in ('preserved', 'moved', 'added', 'pending')}
    return groups


def finish_scope(payload, world, rules, facts):
    scope = payload['replanning']
    solver = payload.get('diagnostics', [])
    budget_hit = any(d.get('code') == 'SEARCH_LIMIT' for d in solver + payload.get('search_diagnostics', []))
    movable_preserved=set(scope['preserved_refs'])-set(scope['protected_refs'])
    can_expand = (scope['mode'] == 'local' and payload['status'] == 'no_plan' and bool(movable_preserved)
                  and bool(scope['affected_refs']) and not budget_hit and any(d.get('code') == 'NO_PLAN_FOUND' for d in solver))
    scope['requires_expansion'] = can_expand
    diagnostics = facts + solver
    if can_expand:
        diagnostics.append(dict(code='LOCAL_SCOPE_LIMIT', constraint='scope', options=['expand_scope', 'keep_current'],
                                message='当前局部搜索未找到完整方案，尚未允许移动其他合法安排。可明确允许扩大范围后再计算；这不等于证明无解。'))
    if payload['status'] != 'ready':
        for ref in scope['protected_refs']:
            if not any(d.get('ref') == ref and d.get('code') == 'LOCKED_SEGMENT' for d in diagnostics):
                diagnostics.append(dict(code='LOCKED_SEGMENT', ref=ref, constraint='locked_or_started', options=['edit_task'],
                                        message=f"{next(t['title'] for t in world['tasks'] if t['ref']==ref)}已锁定或已经开始，扩大范围仍会保留原时段。"))
    # Deduplicate strategy diagnostics while keeping the program's exact facts.
    payload['diagnostics'] = list({signature(d): d for d in diagnostics}.values())
    formal_refs={x['ref'] for x in world.get('formal_previous',[])}
    payload['formal_plan_needs_review'] = any(x['ref'] in formal_refs for x in world.get('pending_work',[])) or any(d.get('code') in ('TIME_RULE_CONFLICT', 'DEADLINE_VIOLATION', 'WORK_REQUIREMENTS_CHANGED', 'CURRENT_TIME_ADVANCED') for d in facts)
    payload['change_groups'] = change_groups(payload['items'], world, scope, payload['diagnostics'], payload['status'] == 'ready')
    for option in payload.get('candidate_options', []):
        option['change_groups'] = change_groups(option['items'], world, scope, payload['diagnostics'], True)
        option['metrics'].update(movement_metrics(option['items'], world.get('formal_previous', world['previous'])))
    selected = next((x for x in payload.get('candidate_options', []) if x['candidate_id'] == payload.get('selected_candidate_id')), None)
    if selected:
        payload['selected_metrics'] = selected['metrics']
        payload['change_groups'] = selected['change_groups']
    return payload


def validate_scope(payload, world, rules):
    """Independently enforce frozen slots against the current formal snapshot."""
    scope=payload.get('replanning')
    if not scope:
        return
    if snapshot_signature(world['formal_previous']) != scope['formal_snapshot_signature']:
        raise ValueError('正式计划快照已变化，请重新生成。')
    old=old_segments(world['formal_previous'])
    new=old_segments(payload['items']+world['retained'])
    fresh,_=identify_scope(world['week'],world['now'],world['selected'],rules,world['formal_previous'],payload['actions'],scope['mode']=='expanded',scope.get('expansion_from'))
    frozen=set(scope['preserved_refs']) | set(scope['protected_refs']) | set(fresh['preserved_refs']) | set(fresh['protected_refs'])
    for ref in frozen:
        # Draft-only locks use the existing Stage 0 full validator and cannot
        # assert that a new draft slot was part of the formal snapshot.
        if ref in old and sorted(map(interval,old[ref])) != sorted(map(interval,new.get(ref,[]))):
            raise ValueError('局部范围之外或受保护的正式片段被修改，请重新生成。')

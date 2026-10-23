"""Partial planning drafts on AssistantProposal; original engine and confirmation.

An internal solver bound is only a completion window, never a fabricated Task
deadline. Partial drafts cannot enter the original confirmation transaction.
"""
from copy import deepcopy
from types import SimpleNamespace
from datetime import datetime, time, timedelta
from sqlalchemy import select
from ..models import AssistantProposal, AssistantSession, AssistantMessage, AssistantRun, Task
from ..workspace_schemas import SchedulePreview
from . import assistant_clock
from .assistant_scheduler import dt
from .assistant_state import build_proposal, preference_settings
from .planning_state import planning_transaction
from .workspace_views import revision
from .conversations import error
from . import draft_defaults


def record_guard(db,row):
    from .scoped_replanning import guard_content
    markers=db.scalars(select(AssistantMessage).where(AssistantMessage.proposal_id==row.id,AssistantMessage.role=='assistant')).all()
    guarded=[m for m in markers if (m.content or {}).get('replanning_guard')]
    if guarded:
        for message in guarded:message.content=guard_content(row.payload)
    else:db.add(AssistantMessage(session_id=row.session_id,role='assistant',text=row.payload['summary'],proposal_id=row.id,content=guard_content(row.payload)))


def calculate(db, session, value, sources, target):
    now=assistant_clock.assistant_now();week=session.week_start
    if not week<=value.day<week+timedelta(days=14):
        error('OUTSIDE_PLANNING_WINDOW','初稿日期须在本周与下周；不会自动改到其他日期。',422)
    start=datetime.combine(value.day,time.fromisoformat(value.start_time),assistant_clock.SHANGHAI)
    end=datetime.combine(value.day,time(22),assistant_clock.SHANGHAI)
    # Never expand the original 08:00–22:00/grid constraints. Past suggested
    # starts are advanced by the engine; the original preference stays visible.
    earliest=max(start,now)
    earliest=earliest.replace(second=0,microsecond=0)+timedelta(minutes=bool(earliest.second or earliest.microsecond))
    earliest+=timedelta(minutes=(-earliest.minute)%5)
    window_start=min(start,end-timedelta(minutes=5))
    fields={'title':value.title,'duration_minutes':value.duration_minutes,'priority':value.priority,
        'deadline':(value.deadline or end).isoformat(),
        'profile':{'allowed_windows':[{'start_at':window_start.isoformat(),'end_at':end.isoformat()}],
            'preferred_windows':[{'start_at':window_start.isoformat(),'end_at':end.isoformat()}],
            'splittable':value.segments>1,'max_segments':value.segments,'min_block_minutes':max(5,value.duration_minutes//value.segments)}}
    if value.start_exact:fields['profile']['fixed_start']=max(start,earliest).isoformat()
    if value.task_id:
        task=db.get(Task,value.task_id)
        if not task or task.task_kind!='executable':error('TASK_NOT_FOUND','原任务已不存在或不是可执行任务。',404)
        # Existing real deadlines remain authoritative unless explicitly edited.
        fields['deadline']=(value.deadline or task.deadline).isoformat()
    action={'op':'update' if value.task_id else 'add','target':target,'fields':fields}
    prefs=preference_settings(db)['settings']
    if value.segments>1:
        # Ask the existing engine to locate a continuous footprint including
        # breaks, then ask it again with exact work-only windows. No rest is
        # counted as work and no direct formal writes or parallel scheduler.
        footprint=deepcopy(action)
        footprint['fields']['duration_minutes']+=value.break_minutes*(value.segments-1)
        footprint['fields']['profile'].update(splittable=False,max_segments=1)
        located=build_proposal(db,week,[footprint],preferences=prefs)
        item=next((x for x in located['items'] if x['ref']==target),None)
        if item:
            cursor=dt(item['start_at']);windows=[]
            for _ in range(value.segments):
                stop=cursor+timedelta(minutes=value.duration_minutes//value.segments)
                windows.append({'start_at':cursor.isoformat(),'end_at':stop.isoformat()})
                cursor=stop+timedelta(minutes=value.break_minutes)
            fields['profile']['allowed_windows']=windows
    payload=build_proposal(db,week,[action],preferences=prefs)
    payload['preview_input']=value.model_dump(mode='json')
    payload['field_sources']=sources
    payload['suggested_not_before']=earliest.isoformat()
    payload['unresolved']=[]
    if value.title=='待命名任务':payload['unresolved'].append('请填写并确认任务名称。')
    if not value.deadline and not value.task_id:
        payload['unresolved'].append('现有正式任务必须填写真实截止时间；当前仅按完成窗口预览，未设置硬截止。')
        # Remove the transient solver bound from every persisted business fact
        # field. It remains explicit only as window_end, never as a Task DDL.
        payload['actions'][0]['fields'].pop('deadline',None)
        for task in payload['tasks']:
            if task['ref']==target:task['deadline']=None
        for change in payload['changes']:
            if change['ref']==target:change['deadline']=None
        payload['candidate_options']=[];payload['alternatives']=[]
    if payload['status']=='ready' and payload['unresolved']:payload['status']='needs_input'
    if not any(x['ref']==target for x in payload['items']):
        payload['notices'].append('所选日期的剩余合法时段无法放下完整工作时长；可缩短、拆分或另选日期，未自动延到明天。')
    if earliest>start:payload['notices'].append('建议起点已过；只在当前时间之后的合法5分钟网格寻找安排。')
    payload['summary']=value.title+' · 可编辑初稿，尚未写入正式任务或日程。'
    payload['questions']=payload.get('questions',[])+payload['unresolved']
    return payload


def create(db, run, request, key, session_factory, *, base_ref=None):
    from . import workspace_drafts
    now=assistant_clock.assistant_now()
    run_token=run.payload.get('token')
    source_revision=revision(db)
    base=None;sources=None;row=None
    if base_ref:
        row=workspace_drafts.require(db,'planning',base_ref['id'])
        if row.payload.get('preview_edit_receipt')=={'key':key,'message':request['message']}:
            return workspace_drafts.envelope(db,'planning',row.id)
        workspace_drafts.check(db,row,base_ref['version'])
        if not draft_defaults.user_values(request['message'],now) and request['message'].startswith(('就用','按这个','就这样')):
            return workspace_drafts.envelope(db,'planning',row.id)
        session=db.get(AssistantSession,row.session_id)
        if session.latest_proposal_id!=row.id or row.status not in ('ready','needs_input','conflict','no_plan'):
            error('STALE_DRAFT','这份草案不可继续修改，请读取最新状态。')
        if row.source_revision!=revision(db):error('STALE_DRAFT','正式资料已变化，请保留输入并重新生成。')
        base=row.payload['preview_input'];sources=row.payload['field_sources']
    saved=preference_settings(db)
    value,origins=draft_defaults.schedule(request,now,base=base,sources=sources,
        preferences=None if saved['is_sample'] else saved['settings'])
    matches=db.scalars(select(Task).where(Task.title==value.title,Task.task_kind=='executable')).all() if not value.task_id else []
    if len(matches)>1:error('AMBIGUOUS_TASK','存在多个同名正式任务，请先在工作区选择具体任务。',422)
    if matches:
        task=matches[0]
        if task.status.value!='todo':error('TASK_UNAVAILABLE','同名任务已完成或取消，请明确选择或修改名称。',422)
        updates={'task_id':task.id}
        for field,formal in [('deadline',task.deadline),('duration_minutes',task.duration_minutes),('priority',task.priority.value)]:
            if origins.get(field) in ('unresolved','system_default'):updates[field]=formal;origins[field]='formal_task'
        value=value.model_copy(update=updates);origins['task_id']='formal_task'
    target=row.payload['actions'][0]['target'] if row else f'task:{value.task_id}' if value.task_id else f'draft:preview-{run.id}'
    calculation_session=session if row else SimpleNamespace(week_start=now.date()-timedelta(days=now.weekday()))
    payload=calculate(db,calculation_session,value,origins,target)
    # Solve outside the writer lock; recheck the complete source revision and
    # optimistic draft version before persisting this calculated snapshot.
    db.rollback()
    with planning_transaction(db):
        live=db.get(AssistantRun,run.id,populate_existing=True)
        if live.status!='running' or live.payload.get('token')!=run_token:error('RUN_STOPPED','回复已停止，未保存新的初稿。')
        if revision(db)!=source_revision:error('STALE_DRAFT','读取期间正式资料已变化，请重新读取。')
        if base_ref:
            row=workspace_drafts.require(db,'planning',base_ref['id'])
            receipt={'key':key,'message':request['message']}
            if row.payload.get('preview_edit_receipt')==receipt:return workspace_drafts.envelope(db,'planning',row.id)
            workspace_drafts.check(db,row,base_ref['version'])
            if row.source_revision!=revision(db):error('STALE_DRAFT','正式资料已变化，请重新读取。')
            session=db.get(AssistantSession,row.session_id)
        else:
            session=session_factory(db,run.session_id,'planning')
            previous=db.scalar(select(AssistantProposal).where(AssistantProposal.session_id==session.id,AssistantProposal.payload['preview_key'].as_string()==key))
            if previous:return workspace_drafts.envelope(db,'planning',previous.id)
        payload['preview_key']=row.payload.get('preview_key',key) if row else key
        payload['preview_edit_receipt']={'key':key,'message':request['message']}
        if row:row.payload=payload;row.status=payload['status']
        else:
            row=AssistantProposal(session_id=session.id,source_revision=revision(db),status=payload['status'],payload=payload)
            db.add(row);db.flush();session.latest_proposal_id=row.id
        record_guard(db,row)
        return workspace_drafts.envelope(db,'planning',row.id)


def edit(db,id,expected,content):
    from . import workspace_drafts
    if set(content)!={'schedule'}:error('INVALID_DRAFT','初稿编辑只接受日程字段。',422)
    value=SchedulePreview.model_validate(content['schedule'])
    row=workspace_drafts.require(db,'planning',id)
    receipt={'from':expected,'content':content}
    if row.payload.get('edit_receipt')==receipt:return workspace_drafts.envelope(db,'planning',id)
    workspace_drafts.check(db,row,expected)
    session=db.get(AssistantSession,row.session_id)
    before=row.payload['preview_input']
    if value.task_id!=before.get('task_id'):error('INVALID_DRAFT','不能通过初稿编辑替换正式任务身份。',422)
    origins={**row.payload['field_sources'],**{k:'user_explicit' for k,v in value.model_dump(mode='json').items() if before.get(k)!=v}}
    prepared=calculate(db,session,value,origins,row.payload['actions'][0]['target'])
    db.rollback()
    with planning_transaction(db):
        row=workspace_drafts.require(db,'planning',id)
        receipt={'from':expected,'content':content}
        if row.payload.get('edit_receipt')==receipt:return workspace_drafts.envelope(db,'planning',id)
        workspace_drafts.check(db,row,expected)
        session=db.get(AssistantSession,row.session_id)
        if session.latest_proposal_id!=id or row.status not in ('ready','needs_input','conflict','no_plan') or row.source_revision!=revision(db):
            error('STALE_DRAFT','草案已失效，请保留输入并重新读取。')
        before=row.payload['preview_input']
        if value.task_id!=before.get('task_id'):error('INVALID_DRAFT','不能通过初稿编辑替换正式任务身份。',422)
        payload=prepared
        row.payload={**payload,'preview_key':row.payload['preview_key'],'edit_receipt':receipt};row.status=payload['status']
        record_guard(db,row)
        return workspace_drafts.envelope(db,'planning',id)

"""Bounded model planning followed by server validated allowlisted tools.

No tool can confirm a draft or write formal facts. Durable keys are independent
of run attempt, so retry cannot duplicate an already produced suggestion.
"""
import json
import logging
import asyncio
import hashlib
from datetime import datetime, timedelta
from pydantic import ValidationError
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from ..models import AssistantSession, AssistantRun, AssistantMessage, GrowthChangeDraft, Task, GrowthGoal, MemoryEntry
from ..secretary_schemas import LookupArgs,MemoryContent
from ..workspace_schemas import ToolPlan, ToolCall, RangeArgs, PlanningArgs, BusinessArgs, EditToolArgs, ReviewToolArgs, ReviewDraftCreate
from ..task_breakdown_schemas import BreakdownCreate
from . import claude_client
from .conversations import local_owner,error,ensure_available
from .planning_state import planning_transaction
from .workspace_views import revision,calendar_events,review_facts
from . import workspace_drafts
from . import ai_skills
from . import ai_diagnostics as trace
from .assistant_clock import assistant_now

logger=logging.getLogger(__name__)
RUNTIME_PROTOCOL='draft-recovery-v3'


def call_key(call):
    arguments=call.arguments
    if call.name in ('calendar','review','review_draft'):
        try:arguments=range_arguments(call.name,arguments)
        except (ValidationError,HTTPException):pass
    return hashlib.sha256(json.dumps([call.name,arguments],sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()[:20]


def range_arguments(name, arguments):
    """Only known date aliases; unknown fields and conflicting values still fail."""
    values=dict(arguments)
    pairs=(('start','start_date'),('end','end_date'))
    for canonical,alias in pairs:
        target,source=(alias,canonical) if name=='review_draft' else (canonical,alias)
        if source in values:
            if target in values and values[target]!=values[source]:
                error('INVALID_TOOL_ARGUMENTS','日期参数相互冲突，请明确同一查询范围。',422)
            values[target]=values.pop(source)
    if name=='review_draft':return ReviewToolArgs.model_validate(values).model_dump(mode='json')
    if 'period' in values:
        if values.pop('period') not in ('day','week','month'):
            error('INVALID_TOOL_ARGUMENTS','回顾周期无效。',422)
    return RangeArgs.model_validate(values).model_dump(mode='json')


def execution_receipt(results, previous):
    """Business outcomes are server receipts, never a second model's claims.

    Pure queries and free chat keep streaming. A persisted draft is not a formal
    save, and a failed tool never grants a completed business outcome.
    """
    lines=[]
    drafts=[r['draft'] for r in results if r.get('draft') and not r.get('error')]
    before={(r['kind'],r['id']):r for r in previous}
    labels={'planning':'日程方案','breakdown':'任务拆解','profile':'档案修改','feedback':'执行反馈','review_record':'复盘记录'}
    for draft in drafts:
        kind=draft['kind'];old=before.get((kind,draft['id']));status=draft['status']
        action='已生成可编辑的' if old is None else '已更新同一份' if old['version']!=draft['version'] else '已读取当前'
        if status=='applied':lines.append(f'当前{labels[kind]}已采用，本轮没有重复保存。');continue
        lines.append(f'{action}{labels[kind]}。')
        value=draft.get('content',{}).get('schedule')
        if value:
            old_value=(old or {}).get('content',{}).get('schedule',{})
            if old_value:
                changed=[label for key,label in [('title','任务名称'),('start_time','开始时间'),('day','日期'),('duration_minutes','工作时长'),('segments','分段'),('break_minutes','段间休息'),('deadline','截止时间')] if old_value.get(key)!=value.get(key)]
                if changed:lines.append('修改了'+ '、'.join(changed)+'。')
            lines.append(f"任务：{value['title']}；工作时长：{value['duration_minutes']}分钟。")
            items=[item for item in draft.get('items',[]) if item['ref']==draft.get('schedule_target')]
            from .assistant_clock import SHANGHAI
            for item in items:
                start=datetime.fromisoformat(item['start_at']).astimezone(SHANGHAI)
                end=datetime.fromisoformat(item['end_at']).astimezone(SHANGHAI)
                lines.append(f"候选安排：{start:%Y-%m-%d %H:%M} 至 {end:%Y-%m-%d %H:%M}。")
            if not items:lines.append('当前没有找到可用安排，请核对冲突或调整时间。')
            if value.get('deadline'):lines.append(f"截止时间：{datetime.fromisoformat(value['deadline']).astimezone(SHANGHAI):%Y-%m-%d %H:%M}。")
        elif kind=='review_record':
            content=draft['content']
            last=(datetime.fromisoformat(content['end_date'])-timedelta(days=1)).date()
            lines.append(f"{content['title']}（{content['start_date']} 至 {last}）。")
            if content.get('summary'):lines.append(content['summary'][:600])
        if status in ('stale','superseded','discarded'):lines.append('这份草案当前不可采用，请重新读取最新状态。')
        elif status in ('conflict','no_plan'):lines.append('当前方案存在冲突或未找到可行安排，尚不能确认采用。')
        lines.extend(draft.get('unresolved',[]))
        lines.extend(draft.get('notices',[]))
    for result in results:
        if result.get('memory') and not result.get('error'):lines.append('已提出待审核的记忆建议，确认后才参与长期参考。')
        if result.get('error') and not result.get('recovered_by'):
            lines.append('本次操作未完成：'+result.get('message','工具执行失败，请核对后重试。'))
    if not lines:return None
    if any(r.get('fallback') for r in results):lines.append('模型处理未完成，初稿使用了已知信息与标注的默认值。')
    if any(d['status']!='applied' for d in drafts):lines.append('尚未保存正式修改，请在右侧辅助栏审核并明确确认。')
    elif not drafts:lines.append('本轮没有修改正式任务或日程。')
    return '\n'.join(dict.fromkeys(lines))
PLANNER='''工具选择协议：只返回符合schema的JSON，不输出解释。只能选择allowed_tools。
tasks/goals/memories使用lookup_schema的id/q/offset/limit；calendar/review使用start,end（上海日期，end不含）。日期工具优先按tool_schemas中的工具名查对应契约，不混用查询和草案字段。
planning_draft使用planning_schema；breakdown_draft使用breakdown_schema；review_draft使用review_schema。
profile_draft/feedback_draft使用operations，遵守business_operations。edit_draft只引用已协调的current_drafts及kind/id/version/content，保留用户其它编辑。
memory_suggestion使用memory_schema。没有权限时calls为空；缺必要字段只返回questions，不执行依赖答案的动作。
每轮总计最多4个工具。需要查询结果才能决定时，只选择查询并设置continue_after_read=true，下一步读取previous_tool_results。普通查询无需继续。
decision_feedback是服务端对未完成办事路径的一次纠正；不要重复已经成功的工具或创建第二份草案。'''


async def plan(request):
    from ..assistant_schemas import PreferencePatch
    from ..schemas import GrowthGoalCreate,GrowthGoalPatch,TaskFeedbackCreate
    from .conversation_context import bounded_request
    request=bounded_request(request)
    selection=ai_skills.select_skills(request['message'],request.get('history',[]),request.get('current_drafts',[]))
    system,_=ai_skills.compose(selection,PLANNER)
    schema=ToolPlan.model_json_schema()
    if selection.allowed:schema['$defs']['ToolCall']['properties']['name']['enum']=sorted(selection.allowed)
    else:
        schema['properties']['calls']={'type':'array','maxItems':0}
        schema.pop('$defs',None)
    from . import draft_defaults
    from ..workspace_schemas import SchedulePreview
    data={**request,'draft_defaults':draft_defaults.DEFAULTS,'schedule_preview_schema':SchedulePreview.model_json_schema(),
        'allowed_tools':sorted(selection.allowed),'schema':schema,'planning_schema':PlanningArgs.model_json_schema(),
        'breakdown_schema':BreakdownCreate.model_json_schema(),'range_schema':RangeArgs.model_json_schema(),
        'edit_schema':EditToolArgs.model_json_schema(),'goal_patch_schema':GrowthGoalPatch.model_json_schema(),
        'preference_patch_schema':PreferencePatch.model_json_schema(),
        'business_operations':{'create_goal':'op plus goal_schema fields','update_goal':'op, goal_id, fields matching goal_patch_schema',
            'record_feedback':'op, task_id plus feedback_schema fields except client_action_id (server generated)',
            'create_preference_rule':{'fields':'op, name, description?, kind, category_key?, weekdays?, parameters',
                'parameters':{'prefer_time':'{start:HH:MM,end:HH:MM}','avoid_time':'{start:HH:MM,end:HH:MM}','deadline_buffer':'{hours:integer 0..72}','adjustment_mode':'{mode:balanced|preference|stable}','ai_note':'{text:string}' }},
            'update_preference_rule':'op, id, fields containing supported create_preference_rule fields or enabled',
            'set_preferences':'op, settings matching preference_patch_schema'},
        'lookup_schema':LookupArgs.model_json_schema(),'memory_schema':MemoryContent.model_json_schema(),'review_schema':ReviewToolArgs.model_json_schema(),
        'goal_schema':GrowthGoalCreate.model_json_schema(),'feedback_schema':TaskFeedbackCreate.model_json_schema()}
    data['tool_schemas']={name:contract for name,contract in {
        'calendar':data['range_schema'],'review':data['range_schema'],
        'review_draft':data['review_schema']}.items() if name in selection.allowed}
    for key,tool in [('planning_schema','planning_draft'),('breakdown_schema','breakdown_draft'),('edit_schema','edit_draft'),
        ('memory_schema','memory_suggestion'),('review_schema','review_draft')]:
        if tool not in selection.allowed:data.pop(key,None)
    if 'planning_draft' not in selection.allowed:data.pop('schedule_preview_schema',None)
    if not selection.expected:data.pop('draft_defaults',None)
    if not selection.allowed.intersection({'profile_draft','feedback_draft'}):
        for key in ('business_operations','goal_schema','goal_patch_schema','feedback_schema','preference_patch_schema'):data.pop(key,None)
    serialized=json.dumps(data,ensure_ascii=False)
    if len(serialized)+len(system)>48000:raise claude_client.AIServiceError('AI_CONTEXT_TOO_LARGE')
    raw=await claude_client.request_claude(serialized,system,claude_client.get_claude_config(),2400)
    from .constraint_parser import normalize_fence,unique_object,reject_constant
    try:
        parsed=json.loads(normalize_fence(raw),object_pairs_hook=unique_object,parse_constant=reject_constant)
        trace.record('tool_plan.json',structure=type(parsed).__name__)
        result=ToolPlan.model_validate(parsed)
        trace.record('tool_plan.valid',calls=[c.name for c in result.calls],questions=len(result.questions))
        return result
    except ValidationError as exc:
        trace.record('tool_plan.schema_failed',errors=trace.schema_errors(exc))
        raise claude_client.AIServiceError('AI_RESPONSE_INVALID') from None
    except (ValueError,RecursionError) as exc:
        trace.record('tool_plan.json_failed',error_type=type(exc).__name__)
        raise claude_client.AIServiceError('AI_RESPONSE_INVALID') from None


def tool_session(db,conversation,scope):
    now=assistant_now();week=now.date()-timedelta(days=now.weekday())
    key=f'tool:{conversation}:{scope}:{week if scope!="profile" else "all"}'
    row=db.scalar(select(AssistantSession).where(AssistantSession.owner_id==local_owner(db),AssistantSession.client_request_id==key))
    if row:ensure_available(db,row,write=True);return row
    row=AssistantSession(scope=scope,week_start=week,client_request_id=key,owner_id=local_owner(db),title='业务草案')
    db.add(row);db.flush();return row


def refs_for(db,conversation):
    refs={}
    rows=db.scalars(select(AssistantRun).where(AssistantRun.session_id==conversation).order_by(AssistantRun.id.desc()).limit(20)).all()
    for r in rows:
        for result in r.payload.get('tool_results',[]):
            ref=result.get('draft')
            if ref:
                try:
                    current=workspace_drafts.envelope(db,ref['kind'],ref['id'])
                    if current.get('replacement_id'):current=workspace_drafts.envelope(db,'planning',current['replacement_id'])
                    if current['status'] not in ('discarded','superseded'):refs[(ref['kind'],ref['id'])]=current
                except HTTPException:pass
    return list(refs.values())[:10]


def persist(engine,rid,token,**values):
    with Session(engine) as db,planning_transaction(db):
        run=db.get(AssistantRun,rid)
        if not run or run.payload.get('token')!=token:return False
        run.payload={**run.payload,**values}
        output=db.get(AssistantMessage,run.payload['assistant_message_id'])
        links=[*output.content.get('links',[]),*(link for result in run.payload.get('tool_results',[]) for link in result.get('links',[]))]
        links=list({(link.get('page'),link.get('kind'),link.get('id')):link for link in links}.values())
        output.content={**output.content,'tools':run.payload.get('tool_results',[]),
            'questions':run.payload.get('tool_questions',[]),
            'links':links,
            'business_status':run.payload.get('skill_diagnostics',{}).get('outcome')}
        return run.status=='running'


async def execute(db,run,call,index,*,fallback=False):
    name,args=call.name,call.arguments;key=f'tool:{run.id}:{index}'
    if name=='memories':
        from .secretary import memory_data
        values=LookupArgs.model_validate(args)
        query=select(MemoryEntry).where(MemoryEntry.owner_id==local_owner(db),MemoryEntry.status=='confirmed')
        if values.id is not None:query=query.where(MemoryEntry.id==values.id)
        if values.q.strip():query=query.where(MemoryEntry.text.contains(values.q.strip(),autoescape=True))
        rows=db.scalars(query.order_by(MemoryEntry.id.desc()).offset(values.offset).limit(values.limit+1)).all()
        return {'items':[memory_data(db,r) for r in rows[:values.limit]],
            'next_offset':values.offset+values.limit if len(rows)>values.limit else None,'source':'用户已确认的长期参考',
            'links':[{'page':'profile','kind':'memory','id':r.id,'label':'查看记忆：'+r.text[:24]} for r in rows[:3]]}
    if name=='review_draft':
        if run.payload.get('skill_diagnostics',{}).get('reason')=='draft_followup':
            error('DRAFT_COORDINATION_REQUIRED','请按现有复盘草案的最新版本修改，或在右侧编辑；本轮不会另建复盘草案。')
        if not args:
            from .draft_defaults import review_range
            start,end,period=review_range(run.text,assistant_now())
            args={'start_date':start,'end_date':end,'period':period}
        values=ReviewToolArgs.model_validate(range_arguments(name,args))
        db.rollback()
        result=await workspace_drafts.create_review_draft(db,run.session_id,ReviewDraftCreate(
            **values.model_dump(),client_request_id=key,message_id=run.payload['user_message_id']),record_message=False,deterministic=fallback)
        return {'draft':{'kind':'review_record','id':result['id']},'summary':result['summary'],'status':result['status']}
    if name in ('tasks','goals'):
        values=LookupArgs.model_validate(args);model=Task if name=='tasks' else GrowthGoal
        query=select(model)
        if values.id is not None:query=query.where(model.id==values.id)
        if values.q.strip():query=query.where(model.title.contains(values.q.strip(),autoescape=True))
        rows=db.scalars(query.order_by(model.id.desc()).offset(values.offset).limit(values.limit+1)).all()
        items=[dict(id=r.id,title=r.title,status=r.status.value if hasattr(r.status,'value') else r.status,
            **({'minutes':r.duration_minutes,'deadline':r.deadline.isoformat(),'kind':r.task_kind} if name=='tasks' else {'weekly_target':r.weekly_target,'version':r.version,'due_date':r.due_date.isoformat() if r.due_date else None})) for r in rows[:values.limit]]
        return {'items':items,'next_offset':values.offset+values.limit if len(rows)>values.limit else None,'source':'当前正式记录'}
    if name=='preferences':
        if args:error('INVALID_TOOL','偏好查询不接收额外参数。',422)
        from .taxonomy import rules_payload
        from .assistant_state import preference_settings
        return {'items':rules_payload(db)[:30],'settings':preference_settings(db)['settings']}
    if name=='memory_suggestion':
        if not any(word in run.text for word in ('记住','以后','长期','偏好','习惯','一直')):
            error('MEMORY_EXPLICIT_INTENT_REQUIRED','临时表达不生成长期记忆；请明确说明希望以后记住什么。',422)
        from .secretary import create_memory,memory_data
        values=MemoryContent.model_validate({**args,'scope':args.get('scope') or 'general'});db.rollback()
        with planning_transaction(db):
            row=create_memory(db,values.model_dump(),key,sources={'conversation_id':run.session_id,'message_ids':[run.payload['user_message_id']]},suggested=True)
            return {'memory':memory_data(db,row),'summary':'仅提出记忆建议，审核确认后才参与后续参考。'}
    if name in ('calendar','review'):
        value=RangeArgs.model_validate(range_arguments(name,args))
        return calendar_events(db,value.start,value.end) if name=='calendar' else review_facts(db,value.start,value.end)
    if name=='breakdown_draft':
        from .conversation_context import context_for
        from .draft_defaults import schedule
        request_context,_=context_for(db,run)
        value,_=schedule(request_context,assistant_now())
        args={**args,'title':args.get('title') or value.title,'text':args.get('text') or run.text,
            'deadline':value.deadline,'expected_duration_minutes':value.duration_minutes}
        if db.scalar(select(Task.id).where(Task.title==args['title'])) is not None:
            error('TASK_ALREADY_EXISTS','已有同名正式任务，请在任务页选择具体任务；当前不会重复创建。',409)
        request=BreakdownCreate.model_validate({**args,'client_request_id':key,'source':'ai'})
        from .task_breakdown import create_draft
        db.rollback();result=await create_draft(db,request)
        return {'draft':{'kind':'breakdown','id':result.id},'summary':result.content.parent.title,'status':result.status}
    if name=='planning_draft':
        if 'actions' in args and (not isinstance(args['actions'],list) or any(not isinstance(a,dict) or not isinstance(a.get('fields',{}),dict) for a in args['actions'])):
            PlanningArgs.model_validate(args)
        from .conversation_context import context_for
        from .draft_defaults import user_values, schedule
        request,_=context_for(db,run)
        references=refs_for(db,run.session_id)
        if run.text.startswith(('就用这个','按这个方案','就这样')):
            latest=next((r for r in references if r['kind']=='planning'),None)
            if latest:return {'draft':{'kind':'planning','id':latest['id']},'summary':'请打开最新草案使用明确确认入口；聊天不会自行保存。','status':latest['status']}
        previews=[r for r in references if r['kind']=='planning' and r.get('content',{}).get('schedule') and r['status'] not in ('applied','discarded','superseded')]
        if len(previews)>1:error('DRAFT_COORDINATION_REQUIRED','存在多份日程初稿，请先选择并打开要修改的草案。')
        partial=any(a.get('op')=='add' and not a.get('fields',{}).get('deadline') for a in args.get('actions',[]))
        if any(a.get('op')=='add' for a in args.get('actions',[])):
            trusted,_=schedule(request,assistant_now())
            partial=partial or not trusted.deadline
        if previews or partial or not args.get('actions') and (not args or user_values(run.text,assistant_now()).get('title')):
            from .schedule_preview import create
            base=previews[0] if previews else None
            if base and not any(r['kind']=='planning' and r['id']==base['id'] and r['version']==base['version'] for r in run.payload.get('draft_versions',[])):
                error('DRAFT_COORDINATION_REQUIRED','请先读取最新草案并协调未保存编辑，再继续修改。')
            result=await asyncio.to_thread(create,db,run,request,key,tool_session,base_ref=base)
            value=result['content']['schedule']
            trace.record('planning_draft.persisted',draft_id=result['id'],status=result['status'],
                defaults_applied=sorted(k for k,v in result['field_sources'].items() if v=='system_default'),
                duration_minutes=value['duration_minutes'],hard_deadline_present=bool(value['deadline']),items=len(result['items']))
            return {'draft':{'kind':'planning','id':result['id']},'summary':result['summary'],'status':result['status']}
        request=PlanningArgs.model_validate(args)
        if request.questions:return {'questions':request.questions}
        if not request.actions and not request.replan:error('INVALID_TOOL','需要明确的任务修改或规划要求。',422)
        from ..routers.assistant import message
        from ..assistant_schemas import MessageRequest
        db.rollback()
        with planning_transaction(db):session=tool_session(db,run.session_id,'planning');sid=session.id
        result=await message(sid,MessageRequest(client_message_id=key,text=run.text,**{**request.model_dump(mode='json',exclude_unset=True),'replan':request.replan}),db)
        return {'draft':{'kind':'planning','id':result['id']},'summary':result['summary'],'status':result['status'],
            'questions':result.get('questions',[])}
    if name=='edit_draft':
        values=EditToolArgs.model_validate(args)
        allowed=run.payload.get('draft_versions',[])
        if not any(r['kind']==values.kind and r['id']==values.id and r['version']==values.version for r in allowed):
            error('DRAFT_COORDINATION_REQUIRED','请先打开草案，处理未保存编辑并读取最新版本后再让AI修改。')
        latest=workspace_drafts.envelope(db,values.kind,values.id)
        if len(json.dumps(latest['content'],ensure_ascii=False))>10000:error('DRAFT_COORDINATION_REQUIRED','这份草案较长，请在工作区修改，避免省略字段被覆盖。')
        db.rollback();result=workspace_drafts.edit(db,values.kind,values.id,values.version,values.content)
        resolved=result.get('id',values.id) if isinstance(result,dict) and values.kind=='planning' else values.id
        return {'draft':{'kind':values.kind,'id':resolved},'summary':'已更新同一草案，仍须审核确认。'}
    values=BusinessArgs.model_validate(args);kind='profile' if name=='profile_draft' else 'feedback'
    workspace_drafts.validate_business(db,kind,values.operations);db.rollback()
    with planning_transaction(db):
        existing=db.scalar(select(GrowthChangeDraft).where(GrowthChangeDraft.payload['tool_key'].as_string()==key))
        if existing:return {'draft':{'kind':kind,'id':existing.id},'summary':'已恢复原草案'}
        session=tool_session(db,run.session_id,'profile' if kind=='profile' else 'review')
        draft=GrowthChangeDraft(session_id=session.id,scope=session.scope,status='ready',source_revision=revision(db),
            payload={'operations':values.operations,'tool_key':key,'reply':'待你审核的修改','changes':[]})
        db.add(draft);db.flush()
        return {'draft':{'kind':kind,'id':draft.id},'summary':'已生成待审核草案，没有保存正式资料。'}


async def prepare(engine,rid,token,request):
    with Session(engine) as db:
        run=db.get(AssistantRun,rid)
        request['current_drafts']=refs_for(db,run.session_id)
        request['review_range']=run.payload.get('review_range')
        for ref in run.payload.get('draft_versions',[]):
            try:
                current=workspace_drafts.envelope(db,ref['kind'],ref['id'])
                if current['version']!=ref['version']:error('DRAFT_VERSION_CONFLICT','草案已变化，请重新读取。')
                request['current_drafts']=[r for r in request['current_drafts'] if (r['kind'],r['id'])!=(ref['kind'],ref['id'])]+[current]
            except HTTPException as exc:
                request['draft_coordination_error']=exc.detail
        from .conversation_context import bounded_drafts
        request['current_drafts']=bounded_drafts(request['current_drafts'][-10:])
        snapshot=revision(db)
        stored=run.payload.get('tool_plan')
    selection=ai_skills.select_skills(request['message'],request.get('history',[]),request.get('current_drafts',[]))
    _,audit=ai_skills.compose(selection)
    trace.record('skills.selected',names=audit['names'],hashes=audit['hashes'],expected=selection.expected)
    logger.info('ai_skills %s',json.dumps(audit,sort_keys=True))
    if not persist(engine,rid,token,skill_diagnostics=audit):return None
    if selection.reason=='ambiguous_draft':
        request['execution_notice']='有多类待审核草案，请先明确要修改日程还是复盘等内容，或打开对应草案；本轮未修改草案或正式资料。'
        return request
    batch_index=0
    results=[]
    repair_batch=None
    argument_repaired=False
    while len(results)<4 and batch_index<5:
        with Session(engine) as db:
            run=db.get(AssistantRun,rid)
            batches=run.payload.get('tool_batches',[])
            repair_batch=run.payload.get('skill_repair_batch')
            format_repaired=run.payload.get('planner_format_repaired',False)
            argument_repaired=run.payload.get('tool_argument_repaired',False)
        saved=batches[batch_index] if batch_index<len(batches) else stored if batch_index==0 else None
        from .conversation_context import provider_value
        request['previous_tool_results']=provider_value(results)
        if repair_batch==batch_index:
            request['decision_feedback']={'code':'MISSING_DRAFT','expected_kind':selection.expected,
                'instruction':'明确办事请求还没有对应草案。仅这一次重新决策；补缺信息就questions，不重复成功工具。'}
        try:
            selected=ToolPlan.model_validate(saved) if saved else await plan(request)
        except claude_client.AIServiceError as exc:
            if not selection.expected or exc.code in ('AI_SKILLS_UNAVAILABLE','AI_CONTEXT_TOO_LARGE'):raise
            if exc.code=='AI_RESPONSE_INVALID' and repair_batch is None:
                repair_batch=batch_index
                format_repaired=True
                if not persist(engine,rid,token,skill_repair_batch=repair_batch,planner_format_repaired=True):return None
                request['decision_feedback']={'code':'INVALID_TOOL_PLAN','instruction':'仅这一次修复结构；严格返回schema JSON，不猜测缺失的真实事实。'}
                try:selected=await plan(request)
                except claude_client.AIServiceError as repaired:
                    request['planner_failure']=repaired.code;selected=ToolPlan()
            else:request['planner_failure']=exc.code;selected=ToolPlan()
        seen_reads={r.get('call_key') for r in results if not r.get('error')}
        cost=0
        for candidate in selected.calls:
            key=call_key(candidate)
            if candidate.name in ai_skills.READ_TOOLS and key in seen_reads:continue
            cost+=1
            if candidate.name in ai_skills.READ_TOOLS:seen_reads.add(key)
        if cost>4-len(results):
            request['tool_questions']=['本轮工具次数已达上限，请核对已有结果后继续。']
            break
        if not saved:
            batches=[*batches,selected.model_dump(mode='json')]
        elif not batches:
            batches=[selected.model_dump(mode='json')]
        if not persist(engine,rid,token,tool_plan=batches[0],tool_batches=batches):return None
        if selected.questions:
            request['tool_questions']=selected.questions
            break
        rejected=ai_skills.validate_plan(selected,selection)
        if rejected:
            denied=next(c.name for c in selected.calls if ai_skills.validate_plan(ToolPlan(calls=[c]),selection))
            results.append({'tool':denied,'error':rejected,
                'message':'本次请求未授权这类操作，未执行草案或正式修改。'})
            if not persist(engine,rid,token,tool_results=results):return None
            break
        batch_start=len(results)
        reserved=False
        repeated_failure=False
        for call in selected.calls:
            identity=call_key(call)
            if call.name in ai_skills.READ_TOOLS:
                if any(r.get('call_key')==identity and r.get('error') for r in results):
                    trace.record('tool.failed_read_stopped',tool=call.name)
                    repeated_failure=True;break
                if any(r.get('call_key')==identity and not r.get('error') for r in results):
                    trace.record('tool.read_reused',tool=call.name)
                    continue
                if selection.expected and not ai_skills.fulfilled(selection,results) and len(results)>=3:
                    trace.record('tool.budget_reserved',expected=selection.expected)
                    reserved=True;break
            index=len(results)
            with Session(engine) as db:
                run=db.get(AssistantRun,rid)
                previous=run.payload.get('tool_results',[])
                if index<len(previous):results.append(previous[index]);continue
                if run.status!='running' or run.payload.get('token')!=token:return None
                run.phase='querying' if call.name in ai_skills.READ_TOOLS else 'calculating'
                db.commit()
                try:
                    if call.name.endswith('_draft') and revision(db)!=snapshot:error('STALE_DRAFT','读取期间资料已变化，请重新核对。')
                    result=await execute(db,run,call,index)
                    if 'draft' in result:
                        ref=result['draft'];result['draft']=workspace_drafts.envelope(db,ref['kind'],ref['id'])
                    if call.name in ai_skills.READ_TOOLS:
                        for earlier in results:
                            if earlier.get('tool')==call.name and earlier.get('error')=='INVALID_TOOL_ARGUMENTS':
                                earlier['recovered_by']='argument_repair'
                    results.append(jsonable_encoder({'tool':call.name,'call_key':identity,**result}))
                    trace.record('tool.returned',tool=call.name,index=index,draft=bool(result.get('draft')),questions=len(result.get('questions',[])))
                except HTTPException as exc:
                    detail=exc.detail if isinstance(exc.detail,dict) else {}
                    results.append({'tool':call.name,'call_key':identity,'error':detail.get('code','TOOL_FAILED'),'message':detail.get('message','工具未完成，正式资料未改变。')})
                except (ValidationError,ValueError,KeyError,TypeError) as exc:
                    trace.record('tool.arguments_failed',tool=call.name,error_type=type(exc).__name__,errors=trace.schema_errors(exc) if isinstance(exc,ValidationError) else [])
                    results.append({'tool':call.name,'call_key':identity,'error':'INVALID_TOOL_ARGUMENTS','message':'信息不完整或参数无效，请补充后再试。',
                        'validation_errors':trace.schema_errors(exc) if isinstance(exc,ValidationError) else []})
                except claude_client.AIServiceError as exc:
                    results.append({'tool':call.name,'error':exc.code,'message':'草案生成未完成，请重试；未保存正式资料。'})
                except SQLAlchemyError:
                    results.append({'tool':call.name,'error':'DRAFT_STORAGE_FAILED','message':'初稿未保存：无法完成数据库读取或持久化，不能确认冲突检查。请稍后重试。'})
            if not persist(engine,rid,token,tool_results=results):return None
        invalid=[r for r in results[batch_start:] if r.get('error')=='INVALID_TOOL_ARGUMENTS']
        if repeated_failure:break
        if invalid:
            if argument_repaired:break
            if not persist(engine,rid,token,tool_argument_repaired=True):return None
            request['decision_feedback']={'code':'INVALID_TOOL_ARGUMENTS',
                'errors':[{'tool':r['tool'],'fields':r.get('validation_errors',[])} for r in invalid],
                'instruction':'仅修复一次参数，按tool_schemas区分review查询的start/end与review_draft的start_date/end_date。不重复失败参数或已成功工具。'}
            batch_index+=1
            continue
        if reserved or selected.continue_after_read and len(results)==batch_start:
            trace.record('tool.read_loop_stopped',reason='reserved_budget' if reserved else 'repeated_read_batch')
            break
        if any(r.get('questions') for r in results):break
        if not selected.continue_after_read:
            if request.get('planner_failure'):break
            if batch_index+1<len(batches) or repair_batch==batch_index+1:
                batch_index+=1
                continue
            if selection.expected and not ai_skills.fulfilled(selection,results) and not any(r.get('error') for r in results) and repair_batch is None and len(results)<4:
                repair_batch=batch_index+1
                if not persist(engine,rid,token,skill_repair_batch=repair_batch):return None
            else:break
        batch_index+=1
    # Last resort uses only verified user input and code-owned defaults. Never
    # feed malformed model text into a business service. It consumes a tool slot.
    forbidden={'TOOL_NOT_ALLOWED','DRAFT_COORDINATION_REQUIRED','DRAFT_VERSION_CONFLICT','STALE_DRAFT','STALE_CANDIDATE','DRAFT_STORAGE_FAILED'}
    if selection.expected in ('planning','review_record') and not ai_skills.fulfilled(selection,results) and len(results)<4 and not any(r.get('error') in forbidden for r in results):
        name='planning_draft' if selection.expected=='planning' else 'review_draft'
        with Session(engine) as db:
            run=db.get(AssistantRun,rid)
            if run.status!='running' or run.payload.get('token')!=token:return None
            try:
                if revision(db)!=snapshot:error('STALE_DRAFT','正式资料已变化，请重新读取。')
                result=await execute(db,run,ToolCall(name=name),len(results),fallback=True)
                if 'draft' in result:
                    ref=result['draft'];result['draft']=workspace_drafts.envelope(db,ref['kind'],ref['id'])
                results.append(jsonable_encoder({'tool':name,**result,'fallback':'trusted_defaults','cause':request.get('planner_failure','INCOMPLETE_PLAN')}))
                for earlier in results[:-1]:
                    if earlier.get('error') in ('INVALID_TOOL_ARGUMENTS','AI_RESPONSE_INVALID','AI_UNAVAILABLE'):earlier['recovered_by']='trusted_defaults'
                request['tool_questions']=[]
                request['execution_notice']='已使用已知信息与标注的默认值生成可编辑初稿，尚未保存正式修改。请打开最新草案检查；你也可以继续聊天修改。'
            except HTTPException as exc:
                detail=exc.detail if isinstance(exc.detail,dict) else {}
                results.append({'tool':name,'error':detail.get('code','DRAFT_SAVE_FAILED'),'message':detail.get('message','初稿未能保存，正式资料未改变。')})
            except (ValidationError,ValueError,KeyError,TypeError):
                results.append({'tool':name,'error':'DRAFT_INPUT_INVALID','message':'初稿未保存：请核对日期、任务名称和5分钟整数倍的工作时长。'})
            except SQLAlchemyError:
                results.append({'tool':name,'error':'DRAFT_STORAGE_FAILED','message':'初稿未保存：无法完成数据库读取或持久化，不能确认冲突检查。请稍后重试。'})
        if not persist(engine,rid,token,tool_results=results):return None
    questions=list(dict.fromkeys(q.strip() for q in [*request.get('tool_questions',[]),
        *(q for result in results for q in result.get('questions',[]))] if isinstance(q,str) and q.strip()))
    request['tool_questions']=questions
    state=ai_skills.outcome(selection,results,questions)
    diagnostics={**audit,'decision_count':batch_index+1+int(format_repaired),'repair_used':repair_batch is not None,'outcome':state,
        'tools':[{'name':r['tool'],'status':'failed' if r.get('error') else 'needs_input' if r.get('questions') else 'returned'} for r in results]}
    if not persist(engine,rid,token,tool_questions=questions,skill_diagnostics=diagnostics):return None
    if state=='not_created':
        label={'planning':'日程方案','breakdown':'任务拆解','review_record':'复盘初稿','memory':'记忆建议','profile':'档案修改','feedback':'执行反馈'}[selection.expected]
        request['execution_notice']=f'这次没有生成可审核的{label}：工具选择未完成，或已达到本轮调用上限。正式资料未改变。请重试，或在对应工作区继续处理。'
    if any(r.get('error')=='DRAFT_STORAGE_FAILED' for r in results):
        request['execution_notice']='初稿未保存：数据库读取或保存失败，无法确认当前冲突。已经读取的结果仍保留；请稍后重试，未进行正式修改。'
    receipt=execution_receipt(results,request.get('current_drafts',[]))
    if receipt and not questions:
        request['execution_notice']=receipt
        trace.record('reply.execution_receipt',drafts=sum(bool(r.get('draft')) for r in results),failed_tools=sum(bool(r.get('error')) for r in results))
    request['tool_results']=provider_value(results)
    return request

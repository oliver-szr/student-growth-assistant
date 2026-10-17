"""Chat drafts and atomic application; provider calls stay outside write locks."""
import asyncio
import logging
from datetime import date, timedelta
from sqlalchemy import select
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker
from ..database import get_db
from ..models import AssistantSession, AssistantProposal, AssistantMessage, AssistantPreference, AssistantRun, GrowthGoal, GrowthGoalRevision, GrowthUserProfile, GrowthChangeDraft, PreferenceRule, Task, TaskFeedback, TaskGrowthContext, TaskSchedulingProfile, Plan, PlanItem, CourseImport, PlanningState, TaskStatus, WorkspaceMetadata, utc_now
from ..assistant_schemas import MessageRequest, PreviewRequest, PreferenceSettings, PreferencePatch
from ..services import assistant_clock, assistant_ai
from ..services.assistant_state import task_library, baseline, time_rules, world_rules, merge_actions, build_proposal, proposed_world, preference_settings, merge_preference_patch
from ..services.assistant_scheduler import validate_assistant, dt
from ..services.planning_state import begin_planning_transaction, get_or_create_planning_state, bump_revision
from ..services.plan_safety import validate_retained_history
from ..services.scoped_replanning import guard_content, validate_scope
from ..services.scheduling_types import SchedulingInputError
from ..services.growth_profile import record_profile_revision
from ..services.growth_tracking import ensure_task_context, record_unknown_completion, retract_latest_completion
from ..services.validator import expand_time_rules
from ..services.planning_window import expand_window_rules
from ..services.claude_client import AIServiceError
from ..schemas import GrowthDirectionUpdate, GrowthGoalCreate, GrowthGoalPatch, TaskFeedbackCreate
from ..services.taxonomy import categories_payload, create_category, rule_payload, rules_from_legacy, rules_payload, update_category, validate_rule

router=APIRouter(prefix='/api/assistant',tags=['Assistant'])
_run_tasks={}
logger = logging.getLogger(__name__)


def fail(code,message,status=409):
    raise HTTPException(status,detail=dict(code=code,message=message))


def require(db,model,id):
    value=db.get(model,id)
    if value is None: fail('NOT_FOUND','记录不存在。',404)
    return value


def response(p):
    return {**p.payload,'id':p.id,'status':p.status,'source_revision':p.source_revision,'plan_id':p.plan_id}


def _revision(db):
    state=db.get(PlanningState,1)
    return state.revision if state else 0


def _active_candidate(db,s):
    previous=db.get(AssistantProposal,s.latest_proposal_id) if s.latest_proposal_id else None
    if previous and previous.status=='ready' and previous.source_revision==_revision(db) and previous.payload.get('items'):
        return previous
    return None


def _previous_candidate(db,s):
    previous=_active_candidate(db,s)
    if previous:
        return previous.payload['items']+previous.payload.get('retained',[])
    return None


def _merge_temporary_preferences(previous,incoming):
    if not previous:return incoming or {}
    if incoming is None:return previous
    merged={key:list(value) for key,value in previous.items()}
    for key,value in incoming.items():
        if not value:
            merged[key]=[]
            continue
        current=merged.get(key,[])
        merged[key]=current+[item for item in value if item not in current]
    return merged


def current_week():
    now=assistant_clock.assistant_now()
    return now.date()-timedelta(days=now.weekday())


def require_current(s):
    if s.week_start!=current_week(): fail('OUTSIDE_CURRENT_WEEK','会话不属于当前周，请新建本周会话。')


def base_actions(db,s,revision):
    p=db.get(AssistantProposal,s.latest_proposal_id) if s.latest_proposal_id else None
    return p.payload['actions'] if p and p.status not in ('applied','discarded','superseded') and p.source_revision==revision else []


def _verified_scope(db,p):
    markers=[m.content for m in db.scalars(select(AssistantMessage).where(AssistantMessage.proposal_id==p.id,AssistantMessage.role=='assistant')).all() if (m.content or {}).get('replanning_guard')]
    scope=p.payload.get('replanning')
    if markers or scope:
        if not scope or not markers or any(marker!=guard_content(p.payload) for marker in markers):
            fail('STALE_CANDIDATE','候选调整范围记录已变化，请重新生成。')
        if scope['mode']=='expanded':
            source=db.get(AssistantProposal,scope.get('expansion_from'))
            if not source or source.session_id!=p.session_id or source.source_revision!=p.source_revision:
                fail('STALE_CANDIDATE','扩大范围授权已失效，请重新生成。')
            original=_verified_scope(db,source)
            if not original or original['mode']!='local' or not original['requires_expansion'] or original['formal_snapshot_signature']!=scope['formal_snapshot_signature']:
                fail('STALE_CANDIDATE','缺少明确的扩大范围授权。')
    return scope


def _scope_context(db,s):
    previous=db.get(AssistantProposal,s.latest_proposal_id) if s.latest_proposal_id else None
    if previous and previous.source_revision==_revision(db) and previous.status not in ('applied','discarded','superseded'):
        return _verified_scope(db,previous)
    return None


def proposal_payload(db,s,actions,questions=None,ai_error=None,preferences=None,preference_updates=None,allow_replan=False,expand_scope=False):
    previous=_active_candidate(db,s)
    pending=db.get(AssistantProposal,s.latest_proposal_id) if s.latest_proposal_id else None
    if pending and pending.source_revision==_revision(db) and pending.status not in ('applied','discarded','superseded'):
        previous=pending
    temporary_preferences=None
    if previous:
        inherited=previous.payload
        if preference_updates is None and inherited.get('preference_updates'):
            preference_updates=inherited['preference_updates']['settings']
        if preferences is None and inherited.get('personal_preferences'):
            preferences={k:v for k,v in inherited['personal_preferences'].items() if k!='temporary_avoid_windows'}
        temporary_preferences=inherited.get('temporary_preferences')
        allow_replan=allow_replan or bool(preference_updates or temporary_preferences)
    scope=_scope_context(db,s) or {}
    payload=build_proposal(db,s.week_start,actions,questions,preferences=preferences,preference_updates=preference_updates,allow_replan=allow_replan or expand_scope,temporary_preferences=temporary_preferences,previous_override=_previous_candidate(db,s),expanded=expand_scope or scope.get('mode')=='expanded',expansion_from=s.latest_proposal_id if expand_scope else scope.get('expansion_from'))
    payload['ai_error']=ai_error
    return payload


def save_proposal(db,s,actions,questions=None,ai_error=None,preferences=None,preference_updates=None,allow_replan=False,prepared_payload=None):
    payload=prepared_payload if prepared_payload is not None else proposal_payload(db,s,actions,questions,ai_error,preferences,preference_updates,allow_replan)
    old=db.get(AssistantProposal,s.latest_proposal_id) if s.latest_proposal_id else None
    if old and old.status not in ('applied','discarded'): old.status='superseded'
    p=AssistantProposal(session_id=s.id,source_revision=get_or_create_planning_state(db).revision,status=payload['status'],payload=payload)
    db.add(p); db.flush(); s.latest_proposal_id=p.id
    return p


class SessionRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')


class RunRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    client_message_id:str=Field(min_length=1,max_length=100)
    text:str=Field(min_length=1,max_length=2000)


def _run_response(run):
    return dict(id=run.id,status=run.status,phase=run.phase,error_code=run.error_code,proposal_id=run.payload.get('proposal_id'),draft_id=run.payload.get('draft_id'))


def _draft_change_summaries(operations, context):
    categories={item['key']:item for item in context.get('categories',[])}
    rules={int(item['id']):item for item in context.get('preference_rules',[])}
    goals={int(item['id']):item for item in context.get('goals',[])}
    names={op.get('temp_ref'):op.get('name') for op in operations if op.get('op')=='create_category'}
    def rule_text(rule, fields=None):
        value={**(rule or {}),**(fields or {})}; params=value.get('parameters') or {}; kind=value.get('kind')
        category_key=value.get('category_key'); category_name=categories.get(category_key,{}).get('name') or value.get('category_name') or names.get(value.get('category_ref'))
        prefix=f"{category_name} · " if category_name else "全部任务 · "
        days=value.get('weekdays')
        suffix=f" · { '、'.join(('周一','周二','周三','周四','周五','周六','周日')[day-1] for day in days) }" if days else ''
        if kind=='prefer_time': return f"{prefix}尽量安排在 {params.get('start','')}–{params.get('end','')}{suffix}"
        if kind=='avoid_time': return f"{prefix}尽量避开 {params.get('start','')}–{params.get('end','')}{suffix}"
        if kind=='deadline_buffer': return f"{prefix}截止前 {params.get('hours',0)} 小时完成"
        if kind=='adjustment_mode': return {'balanced':'兼顾习惯与稳定','preference':'优先符合习惯','stable':'尽量少移动已有安排'}.get(params.get('mode'),params.get('mode',''))
        return params.get('text','供AI参考')
    result=[]
    for op in operations:
        kind=op.get('op')
        if kind=='create_category':
            result.append(dict(title='新增任务类别',before='无',after=op.get('name',''),impact='保存后可用于新任务和偏好规则。'))
        elif kind=='update_category':
            row=categories.get(op.get('key'),{}); fields=op.get('fields',{})
            result.append(dict(title='修改任务类别',before=row.get('name',''),after=fields.get('name',row.get('name',''))+(' · 停用' if fields.get('active') is False else ''),impact='原有关联任务和历史记录会保留。'))
        elif kind=='create_preference_rule':
            category=op.get('category_key')
            category_name=categories.get(category,{}).get('name') if category else names.get(op.get('category_ref'))
            params=op.get('parameters') or {}; rule_kind=op.get('kind')
            detail=(f"{params.get('start','')}–{params.get('end','')}" if rule_kind in ('prefer_time','avoid_time') else f"提前{params.get('hours')}小时" if rule_kind=='deadline_buffer' else params.get('mode','') if rule_kind=='adjustment_mode' else '仅供AI参考，不直接参与排程')
            result.append(dict(title=op.get('name','新增安排偏好'),before='无',after=f"{category_name+'：' if category_name else ''}{detail}",impact='经确认后参与后续规划。'))
        elif kind=='update_preference_rule':
            row=rules.get(int(op.get('id',0)),{}); fields=op.get('fields',{})
            after_name=fields.get('name',row.get('name',''))
            after_rule=rule_text(row,fields)
            if fields.get('enabled') is False: after_rule+=' · 停用'
            result.append(dict(title='修改安排偏好',before=f"{row.get('name','')}：{rule_text(row)}",after=f"{after_name}：{after_rule}",impact='规则参数保存后用于后续规划。'))
        elif kind=='create_goal':
            result.append(dict(title='新增长期目标',before='无',after=f"{op.get('title','')} · 每周{op.get('weekly_target')}{op.get('unit_label','')}",impact='目标保存后可关联任务并显示成长进展。'))
        elif kind=='update_goal':
            row=goals.get(int(op.get('goal_id',0)),{}); fields=op.get('fields',{})
            after_title=fields.get('title',row.get('title',''))
            after_target=fields.get('weekly_target',row.get('weekly_target'))
            after_unit=fields.get('unit_label',row.get('unit_label',''))
            before=f"{row.get('title','')} · 每周{row.get('weekly_target')}{row.get('unit_label','')}"
            after=f"{after_title} · 每周{after_target}{after_unit}"
            result.append(dict(title='修改长期目标',before=before,after=after,impact='保留目标版本记录，不直接覆盖已确认日程。'))
        elif kind=='set_preferences':
            labels={'task_windows':'任务适合时段','avoid_windows':'尽量避开','deadline_buffer_hours':'重要任务截止缓冲','adjustment_mode':'调整取舍'}
            result.append(dict(title='修改安排偏好',before='当前已确认规则',after='、'.join(labels.get(key,key) for key in op.get('settings',{})),impact='只改变对话中明确提到的规则。'))
        elif kind=='set_direction':
            result.append(dict(title='旧版方向资料',before='原方向',after=op.get('direction',''),impact='旧版兼容项；建议改用长期目标管理。'))
        elif kind=='record_feedback':
            tasks={int(item['id']):item for item in context.get('tasks',[])}
            outcome={'completed':'完成','partial':'部分完成','postponed':'暂缓'}.get(op.get('outcome'),'')
            minutes=f" · 本次投入 {op['actual_minutes']} 分钟" if op.get('actual_minutes') else ''
            result.append(dict(title='修正执行记录',before='原有记录',after=f"{tasks.get(int(op.get('task_id',0)),{}).get('title','任务')} · {outcome}{minutes}",impact='确认后重新计算复盘统计。'))
    return result


def _run_snapshot(db,s):
    pref=preference_settings(db)
    _,confirmed=baseline(db,s.week_start)
    rules=time_rules(db); names={r.id:r.title for r in rules}
    courses=[dict(ref=f'course:{x.time_rule_id}',title=names[x.time_rule_id],start_at=x.start_at.isoformat(),end_at=x.end_at.isoformat()) for x in expand_window_rules(s.week_start,rules) if x.kind=='course']
    history=[m.text for m in db.scalars(select(AssistantMessage).where(AssistantMessage.session_id==s.id).order_by(AssistantMessage.id.desc()).limit(10)).all()][::-1]
    goals=[dict(id=g.id,title=g.title,motivation=g.motivation,priority=g.priority,metric_kind=g.metric_kind,weekly_target=g.weekly_target,unit_label=g.unit_label,status=g.status) for g in db.scalars(select(GrowthGoal).where(GrowthGoal.status=='active').order_by(GrowthGoal.priority,GrowthGoal.id)).all()]
    recent_feedback=[dict(task_id=f.task_id,outcome=f.outcome,actual_minutes=f.actual_minutes,initial_estimate_minutes=f.initial_estimate_minutes,family=f.family_snapshot,completed_at=f.completed_at.isoformat() if f.completed_at else None,reason=f.reason) for f in db.scalars(select(TaskFeedback).where(TaskFeedback.retracted_at.is_(None)).order_by(TaskFeedback.id.desc()).limit(12)).all()]
    revision=get_or_create_planning_state(db).revision
    latest=db.get(AssistantProposal,s.latest_proposal_id) if s.latest_proposal_id else None
    current=_active_candidate(db,s)
    candidate_context={key:current.payload.get(key) for key in ('tasks','items','changes','selected_candidate_id','selected_strategy','preference_updates','temporary_preferences')} if current else None
    return dict(revision=revision,latest_id=s.latest_proposal_id,latest_status=latest.status if latest else None,base_actions=base_actions(db,s,revision),preferences=pref['settings'],preference_is_sample=pref['is_sample'],context=dict(now=assistant_clock.assistant_now().isoformat(),week_start=s.week_start.isoformat(),tasks=latest.payload['tasks'] if latest and latest.status not in ('applied','discarded','superseded') and latest.source_revision==revision else task_library(db),task_categories=categories_payload(db,True),courses=courses,confirmed_items=confirmed,current_candidate=candidate_context,preferences=pref['settings'],goals=goals,recent_execution_feedback=recent_feedback,history=history))


def _reason_codes(reasons,option,options,payload):
    metrics=option['metrics']; all_metrics=[x['metrics'] for x in options]
    max_moves=max((x['changed_tasks_weight'] for x in all_metrics),default=0)
    max_miss=max((x['preference_misses_weight'] for x in all_metrics),default=0)
    max_buffer=max((x['deadline_buffer_shortfall_hours'] for x in all_metrics),default=0)
    has_pref=bool(payload.get('personal_preferences',{}).get('task_windows') or payload.get('personal_preferences',{}).get('avoid_windows'))
    preference_cost=lambda value:sum(value.get(key,0) for key in ('preference_misses_weight','avoided_tasks_weight','temporary_avoided_tasks_weight'))
    dimensions=(preference_cost,lambda value:value.get('changed_tasks_weight',0),lambda value:value.get('deadline_buffer_shortfall_hours',0))
    balanced_tradeoff=False
    for other in all_metrics:
        ours=[metric(metrics) for metric in dimensions]; theirs=[metric(other) for metric in dimensions]
        if any(a<b for a,b in zip(ours,theirs)) and any(a>b for a,b in zip(ours,theirs)):
            balanced_tradeoff=True; break
    supported={'follows_task_window':has_pref and metrics['preference_misses_weight']<max_miss,
               'avoids_unwanted_window':bool(payload.get('personal_preferences',{}).get('avoid_windows')) and metrics.get('avoided_tasks_weight',0)<max((x.get('avoided_tasks_weight',0) for x in all_metrics),default=0),
               'reduces_task_moves':metrics['changed_tasks_weight']<max_moves,
               'more_deadline_buffer':metrics['deadline_buffer_shortfall_hours']<max_buffer,
               'balanced_tradeoff':len(options)>1 and balanced_tradeoff}
    return [code for code in reasons if supported.get(code,False)]


def _apply_option(proposal,option,source,reasons,error=None):
    options=proposal.payload.get('candidate_options',[])
    valid=_reason_codes(reasons,option,options,proposal.payload)
    labels={'follows_task_window':'更符合你设置的任务时段偏好','avoids_unwanted_window':'避开了你不想安排任务的时段','reduces_task_moves':'减少了对原有任务安排的移动','more_deadline_buffer':'为重要任务留出了更多截止缓冲','balanced_tradeoff':'在个人偏好、任务移动和截止风险之间作了平衡'}
    proposal.payload={**proposal.payload,'items':option['items'],'changes':option['changes'],'summary':option['summary']+'\n所有本轮任务都通过课程、截止时间和锁定校验。','selected_candidate_id':option['candidate_id'],'selected_strategy':option['strategy'],'selected_metrics':option['metrics'],'alternatives':[x['items'] for x in options if x['candidate_id']!=option['candidate_id']][:2],'recommendation':{'source':source,'candidate_id':option['candidate_id'],'reason_codes':valid,'reason_text':[labels[x] for x in valid]},'recommendation_error':error}
    if 'change_groups' in option: proposal.payload={**proposal.payload,'change_groups':option['change_groups']}


def _set_run(engine,run_id,status=None,phase=None,error=None,proposal_id=None):
    factory=sessionmaker(bind=engine,autoflush=False,autocommit=False)
    with factory() as db:
        run=db.get(AssistantRun,run_id)
        if not run:return
        if status:run.status=status
        if phase:run.phase=phase
        run.error_code=error
        if proposal_id:run.payload={**run.payload,'proposal_id':proposal_id}
        db.commit()


def _create_run_proposal(engine,run_id,actions,questions,context,preference_updates,temporary_preferences,strategy,clear_temporary_preferences=False):
    factory=sessionmaker(bind=engine,autoflush=False,autocommit=False)
    with factory() as db:
        run=require(db,AssistantRun,run_id); session=require(db,AssistantSession,run.session_id)
        if run.status!='running' or _revision(db)!=run.source_revision: return None
        if session.latest_proposal_id!=run.payload.get('latest_id'):return None
        merged=merge_actions(run.payload.get('base_actions',[]),actions)
        previous=_active_candidate(db,session)
        inherited=previous.payload if previous else {}
        inherited_updates=(inherited.get('preference_updates') or {}).get('settings')
        if inherited_updates and preference_updates:
            preference_updates=merge_preference_patch(inherited_updates,preference_updates)
        elif inherited_updates:
            preference_updates=inherited_updates
        temporary_preferences=None if clear_temporary_preferences else _merge_temporary_preferences(inherited.get('temporary_preferences'),temporary_preferences)
        effective=merge_preference_patch(run.payload['preferences'],preference_updates)
        temporary_preferences=temporary_preferences or {}
        if temporary_preferences.get('avoid_windows'):effective['temporary_avoid_windows']=temporary_preferences['avoid_windows']
        if strategy:effective['adjustment_mode']=strategy
        week=session.week_start; revision=run.source_revision
        scope=_scope_context(db,session) or {}
        payload=build_proposal(db,week,merged,questions,preferences=effective,strategy=strategy or 'balanced',preference_updates=preference_updates,allow_replan=bool(preference_updates or temporary_preferences or strategy),temporary_preferences=temporary_preferences,previous_override=_previous_candidate(db,session),expanded=scope.get('mode')=='expanded',expansion_from=scope.get('expansion_from'))
        payload.update(ai_error=None,requested_strategy=strategy,temporary_preferences=temporary_preferences or {},recommendation=None)
        db.rollback()
        begin_planning_transaction(db)
        run=require(db,AssistantRun,run_id); session=require(db,AssistantSession,run.session_id)
        latest=db.get(AssistantProposal,run.payload.get('latest_id')) if run.payload.get('latest_id') else None
        latest_status=latest.status if latest else None
        if run.status!='running' or _revision(db)!=revision or session.latest_proposal_id!=run.payload.get('latest_id') or latest_status!=run.payload.get('latest_status'):return None
        if latest and latest.status not in ('applied','discarded'):latest.status='superseded'
        proposal=AssistantProposal(session_id=session.id,source_revision=revision,status=payload['status'],payload=payload)
        db.add(proposal); db.flush(); session.latest_proposal_id=proposal.id
        db.add(AssistantMessage(session_id=session.id,role='assistant',text='\n'.join(proposal.payload['questions']) or proposal.payload['summary'],proposal_id=proposal.id,content=guard_content(proposal.payload)))
        run.phase='recommending' if proposal.status=='ready' else 'finished'; run.payload={**run.payload,'proposal_id':proposal.id}
        db.commit(); return proposal.id


async def _process_run(engine,run_id):
    factory=sessionmaker(bind=engine,autoflush=False,autocommit=False)
    try:
        with factory() as db:
            run=db.get(AssistantRun,run_id)
            if not run or run.status!='running':return
            snapshot=dict(run.payload); text=run.text; session_id=run.session_id
        if snapshot.get('scope') in ('profile','review'):
            context=snapshot['context']
            try:
                result=await assistant_ai.workspace_message(snapshot['scope'],text,context)
            except AIServiceError as exc:
                _set_run(engine,run_id,'failed','finished',exc.code); return
            with factory() as db:
                run=require(db,AssistantRun,run_id); session=require(db,AssistantSession,session_id)
                if run.status!='running' or _revision(db)!=run.source_revision: return
                operations=result['operations']
                if snapshot['scope']=='review':
                    task_ids={task['id'] for task in context['tasks']}
                    for operation in operations:
                        if operation.get('task_id') not in task_ids: raise ValueError('unknown task')
                draft=None
                if operations:
                    old=db.scalar(select(GrowthChangeDraft).where(GrowthChangeDraft.session_id==session.id,GrowthChangeDraft.status=='ready').order_by(GrowthChangeDraft.id.desc()))
                    if old: old.status='superseded'
                    draft=GrowthChangeDraft(session_id=session.id,scope=snapshot['scope'],source_revision=run.source_revision,status='ready',payload={'operations':operations,'changes':_draft_change_summaries(operations,context),'reply':result['reply'],'questions':result['questions']})
                    db.add(draft); db.flush()
                text_out='\n'.join(result['questions']) if result['questions'] else result['reply']
                db.add(AssistantMessage(session_id=session.id,role='assistant',text=text_out,content={'draft_id':draft.id if draft else None,'questions':result['questions'],'changes':_draft_change_summaries(operations,context)}))
                run.status='completed'; run.phase='finished'; run.payload={**run.payload,'draft_id':draft.id if draft else None}; db.commit()
            return
        if snapshot.get('retry_recommendation'):
            with factory() as db:
                proposal=require(db,AssistantProposal,snapshot['proposal_id']); facts=dict(proposal.payload)
        else:
            parsed=await assistant_ai.parse_message(text,snapshot['context'])
            questions=parsed.questions
            actions=[a.model_dump(mode='json',exclude_unset=True) for a in parsed.actions]
            updates=parsed.preference_updates.model_dump(mode='json',exclude_none=True) if parsed.preference_updates else None
            temporary=parsed.temporary_preferences.model_dump(mode='json',exclude_unset=True,exclude_none=True) if parsed.temporary_preferences else None
            _set_run(engine,run_id,phase='arranging')
            proposal_id=await asyncio.to_thread(_create_run_proposal,engine,run_id,actions,questions,snapshot['context'],updates,temporary,parsed.strategy,parsed.clear_temporary_preferences)
            if not proposal_id:
                _set_run(engine,run_id,'failed','finished','STALE_CANDIDATE'); return
            with factory() as db:
                run=require(db,AssistantRun,run_id); proposal=require(db,AssistantProposal,proposal_id)
                if proposal.status!='ready':run.status='completed'; run.phase='finished'; db.commit(); return
                facts=dict(proposal.payload)
        with factory() as db:
            run=require(db,AssistantRun,run_id)
            if run.status!='running':return
            run.phase='recommending'; db.commit()
        try:
            result=await assistant_ai.recommend(facts)
            source='ai'; error=None
        except AIServiceError as exc:
            result={'candidate_id':facts['selected_candidate_id'],'reason_codes':[]}
            source='program_fallback'; error=exc.code
        with factory() as db:
            run=require(db,AssistantRun,run_id); proposal=require(db,AssistantProposal,run.payload['proposal_id'])
            session=require(db,AssistantSession,session_id)
            current_revision=_revision(db)
            if run.status!='running':return
            if current_revision!=run.source_revision or session.latest_proposal_id!=proposal.id or proposal.status!='ready':
                run.status='failed'; run.phase='finished'; run.error_code='STALE_CANDIDATE'; db.commit(); return
            option=next((x for x in proposal.payload.get('candidate_options',[]) if x['candidate_id']==result['candidate_id']),None)
            if option is None: option=next(x for x in proposal.payload['candidate_options'] if x['strategy']=='balanced')
            _apply_option(proposal,option,source,result.get('reason_codes',[]),error)
            run.status='completed'; run.phase='finished'; run.error_code=error
            assistant=db.scalar(select(AssistantMessage).where(AssistantMessage.proposal_id==proposal.id,AssistantMessage.role=='assistant'))
            if assistant:assistant.text=proposal.payload['summary']
            db.commit()
    except asyncio.CancelledError:
        _set_run(engine,run_id,'cancelled','cancelled'); raise
    except AIServiceError as exc:
        _set_run(engine,run_id,'failed','finished',exc.code)
    except Exception:
        logger.exception("Assistant run failed unexpectedly (run_id=%s)", run_id)
        _set_run(engine,run_id,'failed','finished','AI_UNAVAILABLE')


def _launch_run(db,run_id):
    task=asyncio.create_task(_process_run(db.get_bind(),run_id))
    _run_tasks[run_id]=task
    task.add_done_callback(lambda _: _run_tasks.pop(run_id,None))


@router.get('/settings')
def settings(db:Session=Depends(get_db)):
    identity=db.get(WorkspaceMetadata,1)
    return {**assistant_clock.clock_settings(),'grid_minutes':5,'planning_window_days':14,'workspace_id':identity.workspace_id if identity else 'uninitialized'}


@router.get('/preferences')
def get_preferences(db:Session=Depends(get_db)):
    current=preference_settings(db)
    return {**current['settings'],'is_sample':current['is_sample']}


@router.put('/preferences')
def put_preferences(payload:PreferenceSettings,db:Session=Depends(get_db)):
    try:
        begin_planning_transaction(db)
        row=db.get(AssistantPreference,1)
        values=payload.model_dump(mode='json')
        if row is None:
            row=AssistantPreference(id=1,settings=values,is_sample=False); db.add(row)
        else:
            row.settings=values; row.is_sample=False
        db.flush()
        rules_from_legacy(db, values)
        record_profile_revision(db, values)
        bump_revision(db)
        db.commit()
        return {**values,'is_sample':False}
    except Exception: db.rollback(); raise


@router.post('/sessions',status_code=201)
def create_session(payload:SessionRequest,db:Session=Depends(get_db)):
    s=AssistantSession(week_start=current_week(),scope='planning'); db.add(s); db.commit(); db.refresh(s)
    return {'id':s.id,'week_start':s.week_start.isoformat()}


class WorkspaceOpenRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    scope:str=Field(pattern='^(planning|review|profile)$')
    week_start:date|None=None


class GrowthDraftPreviewRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    operations:list[dict]=Field(max_length=10)


@router.post('/sessions/open',status_code=201)
def open_workspace_session(payload:WorkspaceOpenRequest,db:Session=Depends(get_db)):
    week=date(1970,1,5) if payload.scope=='profile' else (payload.week_start or current_week())
    if week.weekday()!=0: fail('INVALID_WEEK','复盘周必须从周一开始。',422)
    if payload.scope=='planning' and week!=current_week(): fail('OUTSIDE_CURRENT_WEEK','规划只支持当前周。',422)
    existing=db.scalar(select(AssistantSession).where(AssistantSession.scope==payload.scope,AssistantSession.week_start==week).order_by(AssistantSession.id.desc()))
    if existing:return {'id':existing.id,'scope':existing.scope,'week_start':existing.week_start.isoformat()}
    session=AssistantSession(week_start=week,scope=payload.scope); db.add(session); db.commit(); db.refresh(session)
    return {'id':session.id,'scope':session.scope,'week_start':session.week_start.isoformat()}


@router.post('/sessions/{id}/runs',status_code=202)
async def create_run(id:int,payload:RunRequest,db:Session=Depends(get_db)):
    s=require(db,AssistantSession,id)
    if s.scope not in ('planning','profile','review'): fail('INVALID_DRAFT','请使用任务拆解专用入口。',422)
    if s.scope=='planning': require_current(s)
    existing=db.scalar(select(AssistantRun).where(AssistantRun.session_id==id,AssistantRun.client_message_id==payload.client_message_id))
    if existing:return _run_response(existing)
    active=db.scalar(select(AssistantRun).where(AssistantRun.session_id==id,AssistantRun.status=='running'))
    if active:fail('RUN_IN_PROGRESS','当前对话正在处理上一条消息，请稍候或取消后再试。')
    if s.scope=='planning': snapshot=_run_snapshot(db,s)
    else:
        tasks=[{'id':t.id,'title':t.title,'status':t.status.value,'duration_minutes':t.duration_minutes,'deadline':t.deadline.isoformat(),'priority':t.priority.value} for t in db.scalars(select(Task).where(Task.status.in_([TaskStatus.todo,TaskStatus.done]),Task.task_kind=='executable').order_by(Task.id)).all()]
        profile=db.get(GrowthUserProfile,1)
        active_draft=db.scalar(select(GrowthChangeDraft).where(GrowthChangeDraft.session_id==id,GrowthChangeDraft.status=='ready').order_by(GrowthChangeDraft.id.desc()))
        history=[m.text for m in db.scalars(select(AssistantMessage).where(AssistantMessage.session_id==id).order_by(AssistantMessage.id.desc()).limit(8)).all()][::-1]
        goals=[{'id':g.id,'title':g.title,'status':g.status,'priority':g.priority,'metric_kind':g.metric_kind,'weekly_target':g.weekly_target,'unit_label':g.unit_label} for g in db.scalars(select(GrowthGoal).order_by(GrowthGoal.id)).all()]
        context={'scope':s.scope,'week_start':s.week_start.isoformat(),'profile':{'direction':profile.direction if profile else ''},'preferences':preference_settings(db)['settings'],'preference_rules':rules_payload(db),'categories':categories_payload(db,True),'goals':goals,'tasks':tasks,'feedback':[{'id':f.id,'task_id':f.task_id,'outcome':f.outcome,'actual_minutes':f.actual_minutes,'category_key':f.family_snapshot,'category_name':f.category_name_snapshot,'occurred_at':f.occurred_at.isoformat()} for f in db.scalars(select(TaskFeedback).where(TaskFeedback.retracted_at.is_(None)).order_by(TaskFeedback.id.desc()).limit(20)).all()],'current_draft':active_draft.payload if active_draft else None,'history':history}
        snapshot={'scope':s.scope,'context':context,'revision':get_or_create_planning_state(db).revision}
    run=AssistantRun(session_id=id,client_message_id=payload.client_message_id,text=payload.text,status='running',phase='understanding',source_revision=snapshot['revision'],payload=snapshot)
    db.add(run); db.flush()
    db.add(AssistantMessage(session_id=id,client_message_id=payload.client_message_id,role='user',text=payload.text))
    db.commit(); db.refresh(run)
    _launch_run(db,run.id)
    return _run_response(run)


@router.get('/runs/{id}')
def get_run(id:int,db:Session=Depends(get_db)):
    run=require(db,AssistantRun,id)
    if run.status=='running' and _revision(db)!=run.source_revision:
        begin_planning_transaction(db)
        run=require(db,AssistantRun,id)
        if run.status=='running' and _revision(db)!=run.source_revision:
            run.status='failed'; run.phase='finished'; run.error_code='STALE_CANDIDATE'; db.commit()
            task=_run_tasks.get(run.id)
            if task and not task.done():task.cancel()
    return _run_response(run)


@router.post('/runs/{id}/cancel')
def cancel_run(id:int,db:Session=Depends(get_db)):
    run=require(db,AssistantRun,id)
    if run.status=='running':
        run.status='cancelled'; run.phase='cancelled'
        proposal_id=run.payload.get('proposal_id')
        proposal=db.get(AssistantProposal,proposal_id) if proposal_id else None
        if proposal and proposal.status not in ('applied','superseded'):proposal.status='discarded'
        db.commit()
        task=_run_tasks.get(run.id)
        if task and not task.done():task.cancel()
    return _run_response(run)


@router.post('/runs/{id}/retry',status_code=202)
async def retry_run(id:int,db:Session=Depends(get_db)):
    run=require(db,AssistantRun,id)
    if run.status=='running':return _run_response(run)
    if run.status=='completed' and require(db,AssistantSession,run.session_id).scope!='planning':
        fail('RUN_NOT_RETRYABLE','这条资料或复盘对话已经处理完成。')
    if run.status not in ('failed','interrupted','completed') or run.error_code=='STALE_CANDIDATE':
        fail('RUN_NOT_RETRYABLE','当前运行不能重试，请发送一条新消息。')
    if get_or_create_planning_state(db).revision!=run.source_revision:fail('STALE_CANDIDATE','任务或偏好已变化，请重新发送。')
    if run.status=='completed' and run.payload.get('proposal_id'):
        proposal=require(db,AssistantProposal,run.payload['proposal_id'])
        if proposal.payload.get('recommendation',{}).get('source')!='program_fallback':fail('RUN_NOT_RETRYABLE','这个运行已经完成。')
        run.payload={**run.payload,'retry_recommendation':True}
    run.status='running'; run.phase='understanding' if not run.payload.get('retry_recommendation') else 'recommending'; run.error_code=None
    db.commit(); _launch_run(db,run.id)
    return _run_response(run)


@router.get('/sessions/{id}')
def get_session(id:int,db:Session=Depends(get_db)):
    s=require(db,AssistantSession,id)
    if s.scope!='planning':
        messages=[dict(id=m.id,role=m.role,text=m.text,content=m.content) for m in db.scalars(select(AssistantMessage).where(AssistantMessage.session_id==s.id).order_by(AssistantMessage.id)).all()]
        draft=db.scalar(select(GrowthChangeDraft).where(GrowthChangeDraft.session_id==s.id,GrowthChangeDraft.status=='ready').order_by(GrowthChangeDraft.id.desc()))
        runs=[dict(id=r.id,status=r.status,phase=r.phase,error_code=r.error_code,created_at=r.created_at.isoformat()) for r in db.scalars(select(AssistantRun).where(AssistantRun.session_id==s.id).order_by(AssistantRun.id.desc()).limit(5)).all()]
        tasks=[{'id':t.id,'title':t.title,'status':t.status.value} for t in db.scalars(select(Task).where(Task.task_kind=='executable').order_by(Task.id)).all()]
        goals=[{'id':g.id,'title':g.title,'status':g.status} for g in db.scalars(select(GrowthGoal).order_by(GrowthGoal.id)).all()]
        return {'id':s.id,'scope':s.scope,'week_start':s.week_start.isoformat(),'messages':messages,'draft':({'id':draft.id,**draft.payload} if draft else None),'runs':runs,'tasks':tasks,'goals':goals,'categories':categories_payload(db,True),'preference_rules':rules_payload(db)}
    p=db.get(AssistantProposal,s.latest_proposal_id) if s.latest_proposal_id else None
    _,items=baseline(db,s.week_start)
    rules=time_rules(db); names={r.id:r.title for r in rules}
    courses=[dict(ref=f'course:{x.time_rule_id}',title=names[x.time_rule_id],start_at=x.start_at.isoformat(),end_at=x.end_at.isoformat(),kind='course') for x in expand_window_rules(s.week_start,rules) if x.kind=='course']
    warnings=[w for c in db.scalars(select(CourseImport)).all() for w in c.warnings]
    messages=[dict(id=m.id,role=m.role,text=m.text,content=m.content) for m in db.scalars(select(AssistantMessage).where(AssistantMessage.session_id==s.id).order_by(AssistantMessage.id)).all()]
    proposal_data=response(p) if p else None
    state=db.get(PlanningState,1)
    if p and proposal_data['status'] in ('ready','conflict','needs_input','no_plan') and p.source_revision!=(state.revision if state else 0):
        proposal_data['status']='stale'
    runs=[dict(id=r.id,status=r.status,phase=r.phase,error_code=r.error_code,created_at=r.created_at.isoformat()) for r in db.scalars(select(AssistantRun).where(AssistantRun.session_id==s.id).order_by(AssistantRun.id.desc()).limit(5)).all()]
    return dict(id=s.id,week_start=s.week_start.isoformat(),messages=messages,proposal=proposal_data,tasks=task_library(db),task_categories=categories_payload(db),confirmed_items=items,courses=courses,warnings=warnings,preferences=get_preferences(db),preference_rules=rules_payload(db),runs=runs,settings=settings(db))


@router.post('/sessions/{id}/messages')
async def message(id:int,payload:MessageRequest,db:Session=Depends(get_db)):
    s=require(db,AssistantSession,id); require_current(s)
    if s.scope!='planning': fail('INVALID_DRAFT','请使用对应工作台的专用入口。',422)
    duplicate=db.scalar(select(AssistantMessage).where(AssistantMessage.session_id==id,AssistantMessage.client_message_id==payload.client_message_id))
    if duplicate:
        if duplicate.proposal_id:return response(require(db,AssistantProposal,duplicate.proposal_id))
        existing_run=db.scalar(select(AssistantRun).where(AssistantRun.session_id==id,AssistantRun.client_message_id==payload.client_message_id))
        if existing_run:fail('RUN_IN_PROGRESS','这条消息已进入 AI 处理流程，请查询运行状态。')
    revision=get_or_create_planning_state(db).revision
    base=base_actions(db,s,revision)
    latest_id=s.latest_proposal_id
    latest=db.get(AssistantProposal,latest_id) if latest_id else None
    latest_status=latest.status if latest else None
    actions=[a.model_dump(mode='json',exclude_unset=True) for a in payload.actions]; questions=payload.questions; error=None
    if not actions and not payload.replan:
        tasks=latest.payload['tasks'] if latest and latest.status not in ('applied','discarded','superseded') and latest.source_revision==revision else task_library(db)
        history=[m.text for m in db.scalars(select(AssistantMessage).where(AssistantMessage.session_id==id).order_by(AssistantMessage.id.desc()).limit(10)).all()][::-1]
        context=dict(now=assistant_clock.assistant_now().isoformat(),week_start=s.week_start.isoformat(),tasks=tasks,history=history)
        db.rollback()
        try:
            parsed=await assistant_ai.parse_message(payload.text,context)
            actions=[a.model_dump(mode='json',exclude_unset=True) for a in parsed.actions]; questions=parsed.questions
        except AIServiceError as exc:
            error=exc.code; questions=['AI暂不可用，输入已保留。请重试或填写手动任务卡片。']
    merged=merge_actions(base,actions)
    db.rollback()
    prepared=await asyncio.to_thread(proposal_payload,db,s,merged,questions,error,allow_replan=payload.replan)
    db.rollback()
    try:
        begin_planning_transaction(db)
        s=require(db,AssistantSession,id); require_current(s)
        duplicate=db.scalar(select(AssistantMessage).where(AssistantMessage.session_id==id,AssistantMessage.client_message_id==payload.client_message_id))
        if duplicate: return response(require(db,AssistantProposal,duplicate.proposal_id))
        current_latest=db.get(AssistantProposal,latest_id) if latest_id else None
        current_status=current_latest.status if current_latest else None
        if get_or_create_planning_state(db).revision!=revision or s.latest_proposal_id!=latest_id or current_status!=latest_status:
            fail('STALE_CANDIDATE','资料或会话已变化，请重新发送；输入不会自动应用。')
        p=save_proposal(db,s,merged,questions,error,prepared_payload=prepared)
        db.add_all([AssistantMessage(session_id=id,client_message_id=payload.client_message_id,role='user',text=payload.text,proposal_id=p.id),AssistantMessage(session_id=id,role='assistant',text='\n'.join(p.payload['questions']) or p.payload['summary'],proposal_id=p.id,content=guard_content(p.payload))])
        r=response(p); db.commit(); return r
    except Exception: db.rollback(); raise


@router.post('/proposals/{id}/preview')
def preview(id:int,payload:PreviewRequest,db:Session=Depends(get_db)):
    try:
        begin_planning_transaction(db)
        old=require(db,AssistantProposal,id); s=require(db,AssistantSession,old.session_id); require_current(s)
        if payload.client_message_id:
            duplicate=db.scalar(select(AssistantMessage).where(AssistantMessage.session_id==s.id,AssistantMessage.client_message_id==payload.client_message_id))
            if duplicate: return response(require(db,AssistantProposal,duplicate.proposal_id))
        if s.latest_proposal_id!=old.id or old.source_revision!=get_or_create_planning_state(db).revision:
            fail('STALE_CANDIDATE','资料或候选已变化，请重新生成；不会覆盖最新任务修改。')
        if old.status in ('applied','discarded','superseded'): fail('PROPOSAL_INACTIVE','请修改最新候选。')
        scope=_verified_scope(db,old) or {}
        if payload.expand_scope:
            if payload.actions or payload.questions or payload.preference_updates or payload.temporary_preferences or payload.strategy or payload.clear_temporary_preferences or payload.candidate_id or payload.alternative_index is not None or scope.get('mode')!='local' or not scope.get('requires_expansion'):
                fail('INVALID_SCOPE_EXPANSION','仅可对当前需要扩大范围的局部候选单独确认。',422)
            prepared=proposal_payload(db,s,old.payload['actions'],expand_scope=True)
            p=save_proposal(db,s,old.payload['actions'],prepared_payload=prepared)
            db.add(AssistantMessage(session_id=s.id,client_message_id=payload.client_message_id,role='assistant',text=p.payload['summary'],proposal_id=p.id,content=guard_content(p.payload)))
            r=response(p); db.commit(); return r
        if payload.candidate_id:
            option=next((x for x in old.payload.get('candidate_options',[]) if x['candidate_id']==payload.candidate_id),None)
            if option is None: fail('INVALID_CANDIDATE','这个备选方案不存在，请重新计算。',422)
            old.payload={**old.payload,'items':option['items'],'changes':option['changes'],'summary':option['summary'],'selected_candidate_id':option['candidate_id'],'selected_strategy':option['strategy'],'selected_metrics':option['metrics'],'recommendation':{'source':'user_selected','candidate_id':option['candidate_id'],'reason_codes':[],'reason_text':[]}}
            if 'change_groups' in option: old.payload={**old.payload,'change_groups':option['change_groups']}
            r=response(old); db.commit(); return r
        actions=[a.model_dump(mode='json',exclude_unset=True) for a in payload.actions]
        if payload.alternative_index is not None:
            alternatives=old.payload.get('alternatives',[])
            if payload.alternative_index>=len(alternatives): fail('INVALID_ALTERNATIVE','备选不存在。',422)
            alt=alternatives[payload.alternative_index]
            if not isinstance(alt,dict): fail('INVALID_ALTERNATIVE','请通过聊天指定要修改的任务时间。',422)
            actions.append(dict(op='update',target=alt['ref'],fields={'profile':{'fixed_start':alt['start_at']}}))
        p=save_proposal(db,s,merge_actions(old.payload['actions'],actions),payload.questions)
        db.add(AssistantMessage(session_id=s.id,client_message_id=payload.client_message_id,role='assistant',text='\n'.join(p.payload['questions']) or p.payload['summary'],proposal_id=p.id,content=guard_content(p.payload)))
        r=response(p); db.commit(); return r
    except Exception: db.rollback(); raise


@router.post('/proposals/{id}/explanation')
async def explanation(id:int,db:Session=Depends(get_db)):
    p=require(db,AssistantProposal,id)
    if p.status!='ready': fail('PROPOSAL_NOT_READY','只有经过校验的候选可解释。')
    facts=dict(p.payload); db.rollback()
    try: return dict(text=await assistant_ai.explain(facts),source='ai')
    except AIServiceError as e: return dict(text=facts['summary'],source='facts',ai_error=e.code)


@router.post('/proposals/{id}/discard')
def discard(id:int,db:Session=Depends(get_db)):
    begin_planning_transaction(db)
    p=require(db,AssistantProposal,id)
    if p.status=='applied': fail('PROPOSAL_APPLIED','已经采用的方案不能放弃。')
    p.status='discarded'; r=response(p); db.commit(); return r


@router.post('/proposals/{id}/confirm')
def confirm(id:int,db:Session=Depends(get_db)):
    try:
        begin_planning_transaction(db)
        p=require(db,AssistantProposal,id)
        if p.status=='applied': return response(p)
        if p.status!='ready': fail('PROPOSAL_NOT_READY','当前方案不可采用。')
        s=require(db,AssistantSession,p.session_id); require_current(s)
        if s.latest_proposal_id!=p.id or p.source_revision!=get_or_create_planning_state(db).revision:
            fail('STALE_CANDIDATE','候选依据的资料已变化，请重新生成。')
        world=proposed_world(db,s.week_start,p.payload['actions'],_previous_candidate(db,s))
        _verified_scope(db,p)
        try:
            validate_scope(p.payload,world,world_rules(db,world,(p.payload.get('temporary_preferences') or {}).get('blocked_windows',[])))
        except ValueError as error:
            fail('STALE_CANDIDATE',str(error))
        if world['questions']: fail('STALE_CANDIDATE','时间或任务状态已变化，请重新生成。')
        blocks=(p.payload.get('temporary_preferences') or {}).get('blocked_windows',[])
        _,validation_previous=baseline(db,s.week_start)
        try:
            validate_retained_history(validation_previous,world['retained'],world['now'])
        except SchedulingInputError as error:
            fail('STALE_CANDIDATE',str(error))
        # A user may explicitly lock a pending future slot. Such a lock never
        # grants the "already started formal task" exception to a past draft.
        staged_locks={a['target'] for a in p.payload['actions'] if a.get('fields',{}).get('profile',{}).get('locked') is True}
        # Reasserting a formal lock cannot authorize moving its existing slots.
        formal_locks={f'task:{profile.task_id}' for profile in db.scalars(select(TaskSchedulingProfile)).all() if (profile.settings or {}).get('locked')}
        staged_locks-=formal_locks
        for ref in staged_locks:
            segments=[x for x in p.payload['items'] if x['ref']==ref]
            if segments and all(dt(x['start_at'])>=world['now'] for x in segments):
                validation_previous=[x for x in validation_previous if x['ref']!=ref]+segments
        violations=validate_assistant(s.week_start,world['now'],world['selected'],world_rules(db,world,blocks),p.payload['items'],validation_previous)
        if violations: fail('STALE_CANDIDATE','候选已不满足当前时间或约束，请重新生成。')
        mapping={t['ref']:t.get('id') for t in world['tasks'] if t.get('id')}
        for a in p.payload['actions']:
            data=next(t for t in world['tasks'] if t['ref']==a['target'])
            if a['op']=='add':
                t=Task(title=data['title'],description=data.get('description'),duration_minutes=data['duration_minutes'],deadline=dt(data['deadline']),priority=data['priority'],status=data['status'])
                db.add(t); db.flush(); mapping[data['ref']]=t.id
                goal_id=data.get('goal_id')
                if goal_id is not None and db.get(GrowthGoal,goal_id) is None: fail('INVALID_GOAL','关联目标已不存在，请重新生成方案。',409)
                db.add(TaskGrowthContext(task_id=t.id,goal_id=goal_id,family=data.get('task_type','other'),family_confirmed=True,initial_estimate_minutes=data['duration_minutes'],deadline_source='external'))
                if t.status==TaskStatus.done: record_unknown_completion(db,t)
            else:
                t=require(db,Task,int(a['target'].split(':')[1]))
                previous_status=t.status
                for k in ('title','description','duration_minutes','deadline','priority','status'):
                    if k in a['fields']: setattr(t,k,dt(data[k]) if k=='deadline' else data[k])
                t.updated_at=utc_now()
                growth=ensure_task_context(db,t)
                if 'goal_id' in a['fields']:
                    goal_id=data.get('goal_id')
                    if goal_id is not None and db.get(GrowthGoal,goal_id) is None: fail('INVALID_GOAL','关联目标已不存在，请重新生成方案。',409)
                    growth.goal_id=goal_id
                if 'task_type' in a['fields']:
                    growth.family=data.get('task_type','other'); growth.family_confirmed=True
                if previous_status!=TaskStatus.done and t.status==TaskStatus.done: record_unknown_completion(db,t)
                elif previous_status==TaskStatus.done and t.status in (TaskStatus.todo,TaskStatus.cancelled): retract_latest_completion(db,t.id)
            profile=db.get(TaskSchedulingProfile,t.id)
            if not profile: profile=TaskSchedulingProfile(task_id=t.id,settings={}); db.add(profile)
            profile.settings={**(data.get('profile') or {}),'task_type':data.get('task_type','other')}
        if p.payload.get('preference_updates'):
            values=p.payload['preference_updates']['settings']
            pref=db.get(AssistantPreference,1)
            if pref is None: db.add(AssistantPreference(id=1,settings=values,is_sample=False))
            else: pref.settings=values; pref.is_sample=False
            db.flush()
            rules_from_legacy(db, values, source="user")
            db.flush(); record_profile_revision(db)
        names={r.id:r.title for r in time_rules(db)}
        rules=time_rules(db); plans=[]
        for offset in (0,7):
            start=s.week_start+timedelta(days=offset)
            current=db.scalar(select(Plan).where(Plan.week_start==start,Plan.status=='confirmed'))
            if current: current.status='superseded'; db.flush()
            weekly_items=[x for x in p.payload['items']+world['retained'] if start<=dt(x['start_at']).date()<start+timedelta(days=7)]
            plan=Plan(week_start=start,status='confirmed',source_revision=p.source_revision,based_on_plan_id=current.id if current else None,task_ids=sorted({mapping[x['ref']] for x in weekly_items}),confirmed_at=utc_now())
            db.add(plan); db.flush(); plans.append(plan)
            for x in weekly_items:
                db.add(PlanItem(plan_id=plan.id,kind='task',task_id=mapping[x['ref']],title_snapshot=x['title'],start_at=dt(x['start_at']),end_at=dt(x['end_at'])))
            for x in expand_time_rules(start,rules):
                if x.kind=='course':db.add(PlanItem(plan_id=plan.id,kind='course',time_rule_id=x.time_rule_id,title_snapshot=names[x.time_rule_id],start_at=x.start_at,end_at=x.end_at))
        plan=plans[0]
        p.status='applied'; p.plan_id=plan.id; bump_revision(db)
        db.add(AssistantMessage(session_id=s.id,role='assistant',text='已采用方案：任务资料与本周、下周日程已一起保存。',proposal_id=p.id))
        r=response(p); db.commit(); return r
    except Exception: db.rollback(); raise


@router.post('/drafts/{id}/confirm')
def confirm_growth_draft(id:int,db:Session=Depends(get_db)):
    try:
        begin_planning_transaction(db)
        draft=require(db,GrowthChangeDraft,id)
        if draft.scope not in ('profile','review'): fail('INVALID_DRAFT','请使用任务拆解专用确认入口。',422)
        if draft.status=='applied': return {'id':draft.id,'status':'applied'}
        if draft.status!='ready' or draft.source_revision!=_revision(db): fail('STALE_DRAFT','资料已变化，请重新生成草案。')
        session=require(db,AssistantSession,draft.session_id)
        if session.scope!=draft.scope: fail('INVALID_DRAFT','草案类型不正确。',422)
        operations=draft.payload['operations']
        if len(operations)>10: fail('INVALID_DRAFT','一次最多确认10项修改。',422)
        category_refs={}
        if draft.scope=='profile':
            for operation in operations:
                if operation['op']=='create_category':
                    if not operation.get('temp_ref') or operation['temp_ref'] in category_refs: fail('INVALID_DRAFT','新增类别引用无效。',422)
                    row=create_category(db,operation['name'])
                    category_refs[operation['temp_ref']]=row.key
                elif operation['op']=='update_category':
                    fields=operation.get('fields') or {}
                    row=update_category(db,operation['key'],**fields)
        for operation in operations:
            op=operation.get('op')
            if draft.scope=='profile' and op in ('create_category','update_category'):
                continue
            if draft.scope=='profile' and op=='set_direction':
                values=GrowthDirectionUpdate(direction=operation['direction'])
                profile=db.get(GrowthUserProfile,1)
                if profile is None:
                    profile=GrowthUserProfile(id=1,direction=values.direction,version=1); db.add(profile)
                else:
                    profile.direction=values.direction
                    profile.updated_at=utc_now()
                db.flush()
            elif draft.scope=='profile' and op=='set_preferences':
                changes=operation['settings']
                current=preference_settings(db)['settings']
                merged=merge_preference_patch(current,changes)
                legacy={key:merged[key] for key in ('task_windows','avoid_windows','deadline_buffer_hours','adjustment_mode')}
                pref=db.get(AssistantPreference,1)
                if pref is None: db.add(AssistantPreference(id=1,settings=legacy,is_sample=False))
                else: pref.settings={**(pref.settings or {}),**legacy}; pref.is_sample=False
                rules_from_legacy(db,changes)
                db.flush()
            elif draft.scope=='profile' and op=='create_preference_rule':
                category_key=operation.get('category_key') or category_refs.get(operation.get('category_ref'))
                if operation.get('category_ref') and not category_key: fail('INVALID_DRAFT','偏好引用的新增类别不存在。',422)
                values=validate_rule(db,dict(name=operation.get('name'),description=operation.get('description',''),kind=operation.get('kind'),category_key=category_key,weekdays=operation.get('weekdays'),parameters=operation.get('parameters'),source='user'))
                db.add(PreferenceRule(**values))
            elif draft.scope=='profile' and op=='update_preference_rule':
                row=require(db,PreferenceRule,int(operation['id']))
                changes=operation.get('fields') or {}
                values=validate_rule(db,{**dict(name=row.name,description=row.description,kind=row.kind,category_key=row.category_key,weekdays=row.weekdays,parameters=row.parameters,source='user'),**changes},own_id=row.id)
                for key,value in values.items(): setattr(row,key,value)
                if 'enabled' in changes: row.enabled=bool(changes['enabled'])
                row.updated_at=utc_now()
            elif draft.scope=='profile' and op=='create_goal':
                goal=GrowthGoal(**GrowthGoalCreate.model_validate({k:v for k,v in operation.items() if k!='op'}).model_dump())
                db.add(goal); db.flush()
                db.add(GrowthGoalRevision(goal_id=goal.id,version=goal.version,snapshot={'title':goal.title,'motivation':goal.motivation,'goal_type':goal.goal_type,'priority':goal.priority,'metric_kind':goal.metric_kind,'weekly_target':goal.weekly_target,'unit_label':goal.unit_label,'due_date':goal.due_date.isoformat() if goal.due_date else None,'status':goal.status}))
            elif draft.scope=='profile' and op=='update_goal':
                goal=require(db,GrowthGoal,int(operation['goal_id']))
                changes=GrowthGoalPatch.model_validate(operation['fields']).model_dump(exclude_unset=True)
                for key,value in changes.items(): setattr(goal,key,value)
                if changes:
                    goal.version+=1; goal.updated_at=utc_now()
                    db.add(GrowthGoalRevision(goal_id=goal.id,version=goal.version,snapshot={'title':goal.title,'motivation':goal.motivation,'goal_type':goal.goal_type,'priority':goal.priority,'metric_kind':goal.metric_kind,'weekly_target':goal.weekly_target,'unit_label':goal.unit_label,'due_date':goal.due_date.isoformat() if goal.due_date else None,'status':goal.status}))
            elif draft.scope=='review' and op=='record_feedback':
                task=require(db,Task,int(operation['task_id']))
                values={k:v for k,v in operation.items() if k in {'outcome','actual_minutes','remaining_minutes','reason'}}
                values['client_action_id']=f'chat-draft-{draft.id}'
                if operation.get('corrects_feedback_id') is not None: values['corrects_feedback_id']=operation['corrects_feedback_id']
                feedback=TaskFeedbackCreate(**values)
                from ..services.growth_tracking import record_feedback
                record_feedback(db,task,feedback)
            else: fail('INVALID_DRAFT','草案包含不支持的修改。',422)
        if draft.scope=='profile' and operations:
            db.flush(); record_profile_revision(db)
        draft.status='applied'; draft.applied_at=utc_now(); bump_revision(db); db.commit()
        return {'id':draft.id,'status':'applied','message':'已保存。可以将这项修改带入规划，另行生成日程候选。'}
    except Exception:
        db.rollback(); raise


@router.post('/drafts/{id}/preview')
def preview_growth_draft(id:int,payload:GrowthDraftPreviewRequest,db:Session=Depends(get_db)):
    draft=require(db,GrowthChangeDraft,id)
    if draft.scope not in ('profile','review'): fail('INVALID_DRAFT','请使用任务拆解专用编辑入口。',422)
    if draft.status!='ready' or draft.source_revision!=_revision(db): fail('STALE_DRAFT','资料已变化，请重新生成草案。')
    if not payload.operations: fail('EMPTY_DRAFT','请保留至少一项要确认的修改。',422)
    categories={row['key'] for row in categories_payload(db)}
    category_refs={op.get('temp_ref') for op in payload.operations if op.get('op')=='create_category'}
    for op in payload.operations:
        kind=op.get('op')
        if draft.scope=='profile' and kind=='create_preference_rule':
            cat=op.get('category_key')
            if cat is not None and cat not in categories: fail('INVALID_DRAFT','偏好所关联的类别不存在。',422)
            if op.get('category_ref') and op['category_ref'] not in category_refs: fail('INVALID_DRAFT','偏好所关联的新类别不存在。',422)
        elif draft.scope=='profile' and kind not in {'set_direction','set_preferences','create_goal','update_goal','create_category','update_category','update_preference_rule'}:
            fail('INVALID_DRAFT','草案包含不支持的修改。',422)
        elif draft.scope=='review' and kind!='record_feedback':
            fail('INVALID_DRAFT','草案包含不支持的修改。',422)
    draft.payload={**draft.payload,'operations':payload.operations,'changes':_draft_change_summaries(payload.operations,{'categories':categories_payload(db),'preference_rules':rules_payload(db),'goals':[],'tasks':[]})}
    db.commit()
    return {'id':draft.id,'status':draft.status,'operations':draft.payload['operations'],'changes':draft.payload['changes']}


@router.post('/drafts/{id}/discard')
def discard_growth_draft(id:int,db:Session=Depends(get_db)):
    draft=require(db,GrowthChangeDraft,id)
    if draft.scope not in ('profile','review'): fail('INVALID_DRAFT','请使用任务拆解专用取消入口。',422)
    if draft.status=='applied': fail('DRAFT_APPLIED','已保存的修改不能放弃。')
    draft.status='discarded'; db.commit()
    return {'id':draft.id,'status':draft.status}

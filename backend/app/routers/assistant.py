"""Chat drafts and atomic application; provider calls stay outside write locks."""
from datetime import date, timedelta
from sqlalchemy import select
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import AssistantSession, AssistantProposal, AssistantMessage, Task, TaskSchedulingProfile, Plan, PlanItem, CourseImport, utc_now
from ..assistant_schemas import MessageRequest, PreviewRequest
from ..services import assistant_clock, assistant_ai
from ..services.assistant_state import task_library, baseline, time_rules, world_rules, merge_actions, build_proposal, proposed_world
from ..services.assistant_scheduler import validate_assistant, dt
from ..services.planning_state import begin_planning_transaction, get_or_create_planning_state, bump_revision
from ..services.validator import expand_time_rules
from ..services.claude_client import AIServiceError

router=APIRouter(prefix='/api/assistant',tags=['Assistant'])


def fail(code,message,status=409):
    raise HTTPException(status,detail=dict(code=code,message=message))


def require(db,model,id):
    value=db.get(model,id)
    if value is None: fail('NOT_FOUND','记录不存在。',404)
    return value


def response(p):
    return {**p.payload,'id':p.id,'status':p.status,'source_revision':p.source_revision,'plan_id':p.plan_id}


def current_week():
    now=assistant_clock.assistant_now()
    return now.date()-timedelta(days=now.weekday())


def require_current(s):
    if s.week_start!=current_week(): fail('OUTSIDE_CURRENT_WEEK','会话不属于当前周，请新建本周会话。')


def base_actions(db,s):
    p=db.get(AssistantProposal,s.latest_proposal_id) if s.latest_proposal_id else None
    return p.payload['actions'] if p and p.status not in ('applied','discarded') else []


def save_proposal(db,s,actions,questions=None,ai_error=None):
    payload=build_proposal(db,s.week_start,actions,questions)
    payload['ai_error']=ai_error
    old=db.get(AssistantProposal,s.latest_proposal_id) if s.latest_proposal_id else None
    if old and old.status not in ('applied','discarded'): old.status='superseded'
    p=AssistantProposal(session_id=s.id,source_revision=get_or_create_planning_state(db).revision,status=payload['status'],payload=payload)
    db.add(p); db.flush(); s.latest_proposal_id=p.id
    return p


class SessionRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')


@router.get('/settings')
def settings():
    return assistant_clock.clock_settings()


@router.post('/sessions',status_code=201)
def create_session(payload:SessionRequest,db:Session=Depends(get_db)):
    s=AssistantSession(week_start=current_week()); db.add(s); db.commit(); db.refresh(s)
    return {'id':s.id,'week_start':s.week_start.isoformat()}


@router.get('/sessions/{id}')
def get_session(id:int,db:Session=Depends(get_db)):
    s=require(db,AssistantSession,id)
    p=db.get(AssistantProposal,s.latest_proposal_id) if s.latest_proposal_id else None
    _,items=baseline(db,s.week_start)
    rules=time_rules(db); names={r.id:r.title for r in rules}
    courses=[dict(ref=f'course:{x.time_rule_id}',title=names[x.time_rule_id],start_at=x.start_at.isoformat(),end_at=x.end_at.isoformat(),kind='course') for x in expand_time_rules(s.week_start,rules) if x.kind=='course']
    warnings=[w for c in db.scalars(select(CourseImport)).all() for w in c.warnings]
    messages=[dict(id=m.id,role=m.role,text=m.text) for m in db.scalars(select(AssistantMessage).where(AssistantMessage.session_id==s.id).order_by(AssistantMessage.id)).all()]
    return dict(id=s.id,week_start=s.week_start.isoformat(),messages=messages,proposal=response(p) if p else None,tasks=task_library(db),confirmed_items=items,courses=courses,warnings=warnings,settings=assistant_clock.clock_settings())


@router.post('/sessions/{id}/messages')
async def message(id:int,payload:MessageRequest,db:Session=Depends(get_db)):
    s=require(db,AssistantSession,id); require_current(s)
    duplicate=db.scalar(select(AssistantMessage).where(AssistantMessage.session_id==id,AssistantMessage.client_message_id==payload.client_message_id))
    if duplicate: return response(require(db,AssistantProposal,duplicate.proposal_id))
    revision=get_or_create_planning_state(db).revision
    base=base_actions(db,s)
    latest_id=s.latest_proposal_id
    actions=[a.model_dump(mode='json',exclude_unset=True) for a in payload.actions]; questions=payload.questions; error=None
    if not actions:
        latest=db.get(AssistantProposal,latest_id) if latest_id else None
        tasks=latest.payload['tasks'] if latest and latest.status not in ('applied','discarded') else task_library(db)
        history=[m.text for m in db.scalars(select(AssistantMessage).where(AssistantMessage.session_id==id).order_by(AssistantMessage.id.desc()).limit(10)).all()][::-1]
        context=dict(now=assistant_clock.assistant_now().isoformat(),week_start=s.week_start.isoformat(),tasks=tasks,history=history)
        db.rollback()
        try:
            parsed=await assistant_ai.parse_message(payload.text,context)
            actions=[a.model_dump(mode='json',exclude_unset=True) for a in parsed.actions]; questions=parsed.questions
        except AIServiceError as exc:
            error=exc.code; questions=['AI暂不可用，输入已保留。请重试或填写手动任务卡片。']
    db.rollback()
    try:
        begin_planning_transaction(db)
        s=require(db,AssistantSession,id); require_current(s)
        duplicate=db.scalar(select(AssistantMessage).where(AssistantMessage.session_id==id,AssistantMessage.client_message_id==payload.client_message_id))
        if duplicate: return response(require(db,AssistantProposal,duplicate.proposal_id))
        if get_or_create_planning_state(db).revision!=revision or s.latest_proposal_id!=latest_id:
            fail('STALE_CANDIDATE','资料或会话已变化，请重新发送；输入不会自动应用。')
        merged=merge_actions(base,actions)
        p=save_proposal(db,s,merged,questions,error)
        db.add_all([AssistantMessage(session_id=id,client_message_id=payload.client_message_id,role='user',text=payload.text,proposal_id=p.id),AssistantMessage(session_id=id,role='assistant',text='\n'.join(p.payload['questions']) or p.payload['summary'],proposal_id=p.id)])
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
        if old.status in ('applied','discarded','superseded'): fail('PROPOSAL_INACTIVE','请修改最新候选。')
        actions=[a.model_dump(mode='json',exclude_unset=True) for a in payload.actions]
        if payload.alternative_index is not None:
            alternatives=old.payload.get('alternatives',[])
            if payload.alternative_index>=len(alternatives): fail('INVALID_ALTERNATIVE','备选不存在。',422)
            alt=alternatives[payload.alternative_index]
            if not isinstance(alt,dict): fail('INVALID_ALTERNATIVE','请通过聊天指定要修改的任务时间。',422)
            actions.append(dict(op='update',target=alt['ref'],fields={'profile':{'fixed_start':alt['start_at']}}))
        p=save_proposal(db,s,merge_actions(old.payload['actions'],actions),payload.questions)
        db.add(AssistantMessage(session_id=s.id,client_message_id=payload.client_message_id,role='assistant',text='\n'.join(p.payload['questions']) or p.payload['summary'],proposal_id=p.id))
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
        world=proposed_world(db,s.week_start,p.payload['actions'])
        if world['questions']: fail('STALE_CANDIDATE','时间或任务状态已变化，请重新生成。')
        violations=validate_assistant(s.week_start,world['now'],world['selected'],world_rules(db,world),p.payload['items'],world['previous'])
        if violations: fail('STALE_CANDIDATE','候选已不满足当前时间或约束，请重新生成。')
        mapping={t['ref']:t.get('id') for t in world['tasks'] if t.get('id')}
        for a in p.payload['actions']:
            data=next(t for t in world['tasks'] if t['ref']==a['target'])
            if a['op']=='add':
                t=Task(title=data['title'],description=data.get('description'),duration_minutes=data['duration_minutes'],deadline=dt(data['deadline']),priority=data['priority'],status=data['status'])
                db.add(t); db.flush(); mapping[data['ref']]=t.id
            else:
                t=require(db,Task,int(a['target'].split(':')[1]))
                for k in ('title','description','duration_minutes','deadline','priority','status'):
                    if k in a['fields']: setattr(t,k,dt(data[k]) if k=='deadline' else data[k])
                t.updated_at=utc_now()
            profile=db.get(TaskSchedulingProfile,t.id)
            if not profile: profile=TaskSchedulingProfile(task_id=t.id,settings={}); db.add(profile)
            profile.settings=data.get('profile') or {}
        current=db.get(Plan,world['current_plan_id']) if world['current_plan_id'] else None
        if current: current.status='superseded'; db.flush()
        plan=Plan(week_start=s.week_start,status='confirmed',source_revision=p.source_revision,based_on_plan_id=current.id if current else None,task_ids=[mapping[t['ref']] for t in world['selected']],confirmed_at=utc_now())
        db.add(plan); db.flush()
        for x in p.payload['items']+world['retained']:
            db.add(PlanItem(plan_id=plan.id,kind='task',task_id=mapping[x['ref']],title_snapshot=x['title'],start_at=dt(x['start_at']),end_at=dt(x['end_at'])))
        names={r.id:r.title for r in time_rules(db)}
        for x in expand_time_rules(s.week_start,time_rules(db)):
            if x.kind=='course': db.add(PlanItem(plan_id=plan.id,kind='course',time_rule_id=x.time_rule_id,title_snapshot=names[x.time_rule_id],start_at=x.start_at,end_at=x.end_at))
        p.status='applied'; p.plan_id=plan.id; bump_revision(db)
        db.add(AssistantMessage(session_id=s.id,role='assistant',text='已采用方案：任务资料与本周日程已一起保存。',proposal_id=p.id))
        r=response(p); db.commit(); return r
    except Exception: db.rollback(); raise

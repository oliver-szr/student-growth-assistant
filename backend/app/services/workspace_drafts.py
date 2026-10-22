"""Version tokens and one envelope over the existing business draft stores."""
import hashlib
import json
from sqlalchemy import select
from ..models import AssistantProposal, AssistantSession, GrowthChangeDraft, ReviewRecord, utc_now
from ..workspace_schemas import ReviewContent
from .conversations import ensure_available, local_owner, error
from .workspace_views import revision, review_facts
from .planning_state import planning_transaction


def version(row):
    return hashlib.sha256(json.dumps([row.id,row.status,row.source_revision,row.payload],sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()[:32]


def require(db,kind,id):
    row=db.get(AssistantProposal if kind=='planning' else GrowthChangeDraft,id)
    allowed={'breakdown':'task_breakdown','profile':'profile','feedback':'review','review_record':'review_record'}
    if row is None or kind!='planning' and row.scope!=allowed.get(kind):error('DRAFT_NOT_FOUND','这份草案不存在。',404)
    ensure_available(db,db.get(AssistantSession,row.session_id))
    return row


def check(db,row,expected):
    if expected is not None and version(row)!=expected:error('DRAFT_VERSION_CONFLICT','草案已在其他入口修改；输入已保留，请比较最新版本。')


def envelope(db,kind,id):
    row=require(db,kind,id);status=row.status
    if kind=='planning':
        session=db.get(AssistantSession,row.session_id)
        if session.latest_proposal_id!=row.id and status not in ('applied','discarded'):status='superseded'
        content={'actions':row.payload.get('actions',[]),'strategy':row.payload.get('requested_strategy') or 'balanced'}
        summary=row.payload.get('summary',''); links=row.payload.get('items',[])
    elif kind=='breakdown':
        content=row.payload['content'];summary=content['parent']['title'];links=[]
        from .task_breakdown import _response
        status=_response(db,row).status
    elif kind=='review_record':
        content=row.payload['content'];summary=content['title'];links=[]
    else:
        content={'operations':row.payload.get('operations',[])};summary=row.payload.get('reply','待审核修改');links=[]
    if status=='ready' and kind!='review_record' and row.source_revision!=revision(db):status='stale'
    return dict(kind=kind,id=id,version=version(row),status=status,source_revision=row.source_revision,
        content=content,summary=summary,session_id=row.session_id,items=links,
        replacement_id=session.latest_proposal_id if kind=='planning' and status=='superseded' else None,
        facts=row.payload.get('facts'),sources=row.payload.get('sources',{}),receipt=row.payload.get('receipt') or row.payload.get('created_task_ids'))


def validate_business(db,kind,operations):
    from ..schemas import GrowthGoalCreate,GrowthGoalPatch,TaskFeedbackCreate
    from ..models import GrowthGoal,Task
    from .taxonomy import validate_rule
    from ..assistant_schemas import PreferencePatch
    if not isinstance(operations,list) or not 1<=len(operations)<=10:error('INVALID_DRAFT','需要1–10项合法修改。',422)
    def validate_preference(values,own_id=None):
        # Legacy validation normalizes single active adjustment_mode rules.
        # Validation of a draft must never commit that normalization.
        transaction=db.begin_nested()
        try:validate_rule(db,values,own_id)
        finally:transaction.rollback()
    for op in operations:
        if not isinstance(op,dict):error('INVALID_DRAFT','修改格式无效。',422)
        name=op.get('op')
        if kind=='feedback':
            if set(op)-{'op','task_id','outcome','actual_minutes','remaining_minutes','reason','corrects_feedback_id','completed_at','occurred_at','family','goal_id','difficulty'}:
                error('INVALID_DRAFT','反馈字段无效。',422)
            if name!='record_feedback' or not db.get(Task,op.get('task_id')):error('INVALID_DRAFT','反馈须引用真实任务。',422)
            TaskFeedbackCreate.model_validate({'client_action_id':'validate',**{k:v for k,v in op.items() if k not in ('op','task_id')}})
        elif name=='create_goal':GrowthGoalCreate.model_validate({k:v for k,v in op.items() if k!='op'})
        elif name=='update_goal':
            if not db.get(GrowthGoal,op.get('goal_id')):error('INVALID_DRAFT','目标不存在。',422)
            if set(op)-{'op','goal_id','fields'}:error('INVALID_DRAFT','目标修改字段无效。',422)
            GrowthGoalPatch.model_validate(op.get('fields'))
        elif name in ('create_preference_rule','update_preference_rule'):
            from ..models import PreferenceRule
            fields={'name','description','kind','category_key','weekdays','parameters','source','enabled'}
            if name=='create_preference_rule':
                if set(op)-fields-{'op'}:error('INVALID_DRAFT','偏好字段无效。',422)
                validate_preference({k:v for k,v in op.items() if k!='op'})
            else:
                if set(op)-{'op','id','fields'} or not isinstance(op.get('fields'),dict) or set(op['fields'])-fields:
                    error('INVALID_DRAFT','偏好修改字段无效。',422)
                row=db.get(PreferenceRule,op.get('id'))
                if not row:error('INVALID_DRAFT','偏好不存在。',422)
                from .taxonomy import rule_payload
                values=rule_payload(db,row);values.update(op.get('fields',{}))
                validate_preference({k:v for k,v in values.items() if k in ('name','description','kind','category_key','weekdays','parameters','source','enabled')},row.id)
        elif name=='set_preferences':
            if set(op)!={'op','settings'}:error('INVALID_DRAFT','偏好字段无效。',422)
            PreferencePatch.model_validate(op.get('settings'))
        else:error('INVALID_DRAFT','工具不支持该正式修改。仅允许目标、偏好或反馈草案。',422)


def edit(db,kind,id,expected,content):
    row=require(db,kind,id)
    if kind=='breakdown':
        from .task_breakdown import edit_draft
        from ..task_breakdown_schemas import BreakdownEdit
        numeric=row.payload['version'];db.rollback()
        return edit_draft(db,id,BreakdownEdit(version=numeric,content=content),expected)
    if kind=='planning':
        from ..routers.assistant import preview
        from ..assistant_schemas import PreviewRequest
        values=PreviewRequest.model_validate({**content,'client_message_id':f'edit:{id}:{expected}:{hashlib.sha256(json.dumps(content,sort_keys=True).encode()).hexdigest()[:16]}'})
        db.rollback();return preview(id,values,db,expected)
    db.rollback()
    with planning_transaction(db):
        row=require(db,kind,id)
        receipt={'from':expected,'content':content}
        if row.payload.get('edit_receipt')==receipt:return envelope(db,kind,id)
        check(db,row,expected)
        if row.status!='ready' or kind!='review_record' and row.source_revision!=revision(db):error('STALE_DRAFT','草案已失效，请重新生成。')
        if kind=='review_record':
            values=ReviewContent.model_validate(content)
            if values.start_date.isoformat()!=row.payload['content']['start_date'] or values.end_date.isoformat()!=row.payload['content']['end_date']:
                error('INVALID_RANGE','草案的事实来源范围保持不变；新范围请重新整理。',422)
            row.payload={**row.payload,'content':values.model_dump(mode='json')}
        else:
            if set(content)!={'operations'}:error('INVALID_DRAFT','修改格式无效。',422)
            validate_business(db,kind,content['operations'])
            row.payload={**row.payload,'operations':content['operations']}
        row.payload={**row.payload,'edit_receipt':receipt}
    return envelope(db,kind,id)


def confirm(db,kind,id,expected):
    from ..routers import assistant
    if kind=='planning':return assistant.confirm(id,db,expected)
    row=require(db,kind,id)
    if row.status!='applied':check(db,row,expected)
    if kind=='breakdown':
        from .task_breakdown import confirm_draft
        from ..task_breakdown_schemas import BreakdownVersion
        numeric=row.payload['version'];db.rollback();return confirm_draft(db,id,BreakdownVersion(version=numeric))
    if kind in ('profile','feedback'):
        db.rollback();return assistant.confirm_growth_draft(id,db,expected)
    db.rollback()
    with planning_transaction(db):
        row=require(db,kind,id)
        if row.status=='applied':return envelope(db,kind,id)
        check(db,row,expected)
        if row.status!='ready':error('STALE_DRAFT','草案已失效。')
        if row.source_revision!=revision(db):error('REVIEW_FACTS_CHANGED','正式资料已变化；请保留文字并重新整理最新事实后再确认。')
        from ..routers.workspace import save_record
        record=save_record(db,ReviewContent.model_validate(row.payload['content']),f'review-draft:{id}',facts=row.payload['facts'],sources=row.payload['sources'])
        row.status='applied';row.applied_at=utc_now();row.payload={**row.payload,'receipt':{'record_id':record.id}}
    return envelope(db,kind,id)


def discard(db,kind,id,expected):
    with planning_transaction(db):
        row=require(db,kind,id);check(db,row,expected)
        if row.status=='applied':error('DRAFT_APPLIED','已保存的事实不能通过放弃草案撤销。')
        row.status='discarded'
    return envelope(db,kind,id)

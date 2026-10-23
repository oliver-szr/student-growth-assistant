"""Deterministic, bounded context with explicit evidence classes. No embeddings."""
import re
from datetime import timedelta,date
from sqlalchemy import select,or_
from ..models import AssistantMessage,Task,GrowthGoal,MemoryEntry
from .conversations import local_owner
from .assistant_clock import assistant_now


def terms(text):
    result=[]
    for part in re.findall(r'[A-Za-z][A-Za-z0-9_-]{1,30}|[\u4e00-\u9fff]{2,}',text.lower()):
        result.extend([part] if len(part)<=4 or part.isascii() else [part[i:i+2] for i in range(len(part)-1)])
    return list(dict.fromkeys(result))[:16]


def intent(text):
    return {'planning':any(w in text for w in ('任务','日程','安排','规划','空闲','今天做','明天做','汇报','报告','截止')),
        'profile':any(w in text for w in ('目标','偏好','档案','课程','习惯')),
        'review':any(w in text for w in ('复盘','回顾','投入','完成情况','记录情况'))}


def memory_context(db,text,signals):
    words=terms(text)
    explicit=any(w in text for w in ('记得','记忆','长期偏好','你了解我','我的习惯'))
    if not words and not explicit:return []
    scope={'general','study'}|{key for key,value in signals.items() if value}
    conditions=[MemoryEntry.owner_id==local_owner(db),MemoryEntry.status=='confirmed',MemoryEntry.scope.in_(scope)]
    if not explicit:conditions.append(or_(*(MemoryEntry.text.contains(w,autoescape=True) for w in words)))
    rows=db.scalars(select(MemoryEntry).where(*conditions).order_by(MemoryEntry.updated_at.desc(),MemoryEntry.id.desc()).limit(60)).all()
    rows.sort(key=lambda r:sum(w in r.text.lower() for w in words),reverse=True)
    answer=[];budget=2400
    for row in rows[:5]:
        if len(row.text)>budget:continue
        budget-=len(row.text);answer.append(dict(id=row.id,version=row.version,text=row.text,scope=row.scope,source='用户已确认的长期参考；不是排程约束',updated_at=row.updated_at.isoformat()))
    return answer


def context_for(db,run):
    signals=intent(run.text);owner=local_owner(db)
    rows=db.scalars(select(AssistantMessage).where(AssistantMessage.session_id==run.session_id,AssistantMessage.owner_id==owner,
        AssistantMessage.id<run.payload['user_message_id']).order_by(AssistantMessage.id.desc()).limit(40)).all()
    recall=any(word in run.text for word in ('之前','前面','上次','记得','那件','提过'))
    history=[];budget=4500 if recall else 6500
    for row in rows:
        info=row.content or {}
        if info.get('kind')=='conversation_summary' or info.get('status','completed')!='completed' or not row.text:continue
        text=row.text[-min(1600,budget):]
        history.append({'id':row.id,'role':row.role,'text':text,'business_status':info.get('business_status'),
            'source':'历史交流，用户感受/AI建议不代表当前正式事实'})
        budget-=len(text)
        if len(history)>=12 or budget<=0:break
    history.reverse();links=[];now=assistant_now();facts={'now':now.isoformat()}
    from .ai_skills import select_skills
    selection=select_skills(run.text,history)
    signals={**signals,'planning':signals['planning'] or selection.expected in ('planning','breakdown'),
        'profile':signals['profile'] or selection.expected=='profile',
        'review':signals['review'] or selection.expected in ('feedback','review_record')}
    if recall:
        budget+=2000
        words=[w for w in terms(run.text) if w not in ('之前','前面','上次','记得','那件','提过')][:8]
        if words:
            older=db.scalars(select(AssistantMessage).where(AssistantMessage.session_id==run.session_id,AssistantMessage.owner_id==owner,
                AssistantMessage.id<run.payload['user_message_id'],or_(*(AssistantMessage.text.contains(w,autoescape=True) for w in words))).order_by(AssistantMessage.id.desc()).limit(8)).all()
            known={m['id'] for m in history}
            for row in older:
                info=row.content or {}
                if row.id in known or info.get('kind')=='conversation_summary' or info.get('status','completed')!='completed' or budget<=0:continue
                excerpt=row.text[:min(1000,budget)];budget-=len(excerpt)
                history.insert(0,{'id':row.id,'role':row.role,'text':excerpt,'source':'按当前话题检索的历史交流，非当前正式事实'})
        history.sort(key=lambda m:m['id'])
    evidence={'history':'仅作为交流语境，过往草案和AI推测不当作正式事实','formal':'当前服务端读取的有效正式记录优先','memory':'已确认长期参考，不覆盖正式事实；与正式资料冲突须说明并询问'}
    if any(signals.values()):
        # Exact user phrases retrieve older named resources as well as recent rows.
        words=terms(run.text)
        tasks=db.scalars(select(Task).order_by(Task.id.desc()).limit(100)).all() if signals['planning'] else []
        tasks.sort(key=lambda t:sum(w in t.title.lower() for w in words),reverse=True)
        facts['tasks']=[dict(id=t.id,title=t.title,minutes=t.duration_minutes,deadline=t.deadline.isoformat(),status=t.status.value,kind=t.task_kind,updated_at=t.updated_at.isoformat()) for t in tasks[:10]]
        if signals['profile']:
            goals=db.scalars(select(GrowthGoal).order_by(GrowthGoal.id.desc()).limit(40)).all()
            goals.sort(key=lambda g:sum(w in g.title.lower() for w in words),reverse=True)
            facts['goals']=[dict(id=g.id,title=g.title,status=g.status,weekly_target=g.weekly_target,due_date=g.due_date.isoformat() if g.due_date else None,version=g.version) for g in goals[:6]]
            from .taxonomy import rules_payload
            facts['preferences']=rules_payload(db)[:8]
            links.append({'page':'profile','kind':'profile','label':'查看正式目标与偏好'})
        if signals['planning']:
            links.append({'page':'schedule','kind':'schedule','label':'查看正式日程与任务'})
            links.extend({'page':'schedule','kind':'task','id':t.id,'label':t.title} for t in tasks[:3])
        if signals['review']:links.append({'page':'review','kind':'review','label':'查看回顾事实'})
    memories=memory_context(db,run.text,signals)
    links.extend({'page':'profile','kind':'memory','id':m['id'],'label':'查看记忆依据'} for m in memories)
    # Deep/date facts are read through the bounded tools, rather than sent by default.
    facts['data_note']='这里只是有界相关记录；日期/任务详情应使用白名单工具查最新事实，未查询不能推断。'
    return {'history':history,'message':run.text,'context':facts,'evidence':evidence,'confirmed_memories':memories},links


def provider_value(value,*,depth=0):
    """Bound outgoing data, not the persisted result/receipt or business editor."""
    if depth>8:return '[结构过深，未传输；请打开工作区核对]'
    if isinstance(value,str):return value[:1600]+('…（截断）' if len(value)>1600 else '')
    if isinstance(value,list):
        result=[provider_value(v,depth=depth+1) for v in value[:40]]
        if len(value)>40:result.append({'omitted_count':len(value)-40})
        return result
    if isinstance(value,dict):return {k:provider_value(v,depth=depth+1) for k,v in value.items() if k not in ('history','edit_receipt','receipt','facts','free','candidate_options')}
    return value


def bounded_drafts(drafts):
    import json
    result=[];budget=10000
    for draft in drafts[:10]:
        size=len(json.dumps(draft.get('content',{}),ensure_ascii=False))
        if size>budget:
            result.append({k:draft[k] for k in ('id','kind','version','status','summary') if k in draft}|{'content_omitted':True,'note':'内容较长，请到工作区修改，不得猜测被省略字段'})
        else:
            result.append({k:v for k,v in draft.items() if k not in ('facts','sources','receipt','items')});budget-=size
    return result


def bounded_request(request,maximum=26000):
    import json
    result={**request}
    result['history']=list(request.get('history',[]))
    size=lambda:len(json.dumps(result,ensure_ascii=False,default=str))
    original=size()
    while size()>maximum-200 and len(result['history'])>4:result['history'].pop(0)
    for key in ('tool_results','previous_tool_results'):
        if size()<=maximum-200:break
        if key in result:
            result[key]=[{'tool':r.get('tool'),'error':r.get('error'),'summary':r.get('summary','结果较长，详情请在工作区核对。'),
                **({'draft':{k:r['draft'][k] for k in ('kind','id','version','status') if k in r['draft']}} if r.get('draft') else {})} for r in result[key]]
    if size()>maximum-200:
        result['context']={'now':request['context']['now'],'note':'相关数据过长，使用白名单精确查询，不推断被省略事实。'}
    if size()>maximum-200:
        result['current_drafts']=[{k:d[k] for k in ('kind','id','version','status') if k in d}|{'content_omitted':True} for d in request.get('current_drafts',[])[:10]]
        result['history']=[]
    result['context_budget']={'max_characters':maximum,'history_is_bounded':True,'truncated':original!=size()}
    if size()>maximum:
        # Refuse rather than leak an oversized or pathological result. Never trim
        # the user's instruction or mutate the persisted draft to fit a prompt.
        from .claude_client import AIServiceError
        raise AIServiceError('AI_CONTEXT_TOO_LARGE')
    return result

"""Local-owner memory management and explicit, idempotent conversation summaries."""
from typing import Literal
from fastapi import APIRouter,Depends,Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import MemoryEntry,AssistantMessage
from ..secretary_schemas import MemoryCreate,MemoryEdit,MemoryContent,MemoryAction,SummaryRequest
from ..services import secretary
from ..services.conversations import local_owner,error,require_conversation
from ..services.planning_state import planning_transaction
from .workspace import ResourceId

router=APIRouter(prefix='/api',tags=['Secretary'])


@router.get('/memories')
def memories(q:str=Query(default='',max_length=100),status:Literal['all','confirmed','suggested','disabled']='all',
        offset:int=Query(default=0,ge=0,le=10000),limit:int=Query(default=25,ge=1,le=50),db:Session=Depends(get_db)):
    conditions=[MemoryEntry.owner_id==local_owner(db),MemoryEntry.status!='deleted']
    if status!='all':conditions.append(MemoryEntry.status==status)
    if q.strip():conditions.append(MemoryEntry.text.contains(q.strip(),autoescape=True))
    rows=db.scalars(select(MemoryEntry).where(*conditions).order_by(MemoryEntry.updated_at.desc(),MemoryEntry.id.desc()).offset(offset).limit(limit+1)).all()
    return {'items':[secretary.memory_data(db,row) for row in rows[:limit]],'next_offset':offset+limit if len(rows)>limit else None}


@router.post('/memories',status_code=201)
def create(payload:MemoryCreate,db:Session=Depends(get_db)):
    with planning_transaction(db):
        row=secretary.create_memory(db,payload.model_dump(exclude={'client_request_id'}),payload.client_request_id)
        if row.status=='deleted':error('MEMORY_DELETED','原请求已经删除，请核对结果后使用新建入口。',410)
        return secretary.memory_data(db,row)


@router.get('/memories/{id}')
def detail(id:ResourceId,db:Session=Depends(get_db)):
    return secretary.memory_data(db,secretary.require_memory(db,id))


@router.patch('/memories/{id}')
def edit(id:ResourceId,payload:MemoryEdit,db:Session=Depends(get_db)):
    with planning_transaction(db):
        row=secretary.change_memory(db,id,payload.expected_version,content=MemoryContent(**payload.model_dump(exclude={'expected_version'})))
        return secretary.memory_data(db,row)


@router.post('/memories/{id}/actions')
def act(id:ResourceId,payload:MemoryAction,db:Session=Depends(get_db)):
    with planning_transaction(db):
        row=secretary.change_memory(db,id,payload.expected_version,action=payload.action)
        return secretary.memory_data(db,row)


@router.get('/conversations/{id}/summaries')
def summaries(id:ResourceId,db:Session=Depends(get_db)):
    require_conversation(db,id)
    rows=db.scalars(select(AssistantMessage).where(AssistantMessage.session_id==id,AssistantMessage.content['kind'].as_string()=='conversation_summary').order_by(AssistantMessage.id.desc()).limit(20)).all()
    return {'items':[secretary.summary_data(db,row) for row in rows]}


@router.post('/conversations/{id}/summaries')
async def generate(id:ResourceId,payload:SummaryRequest,db:Session=Depends(get_db)):
    return await secretary.generate_summary(db,id,payload)


@router.get('/conversations/{id}/summaries/requests/{key}')
def operation(id:ResourceId,key:str,db:Session=Depends(get_db)):
    if not 1<=len(key)<=100:error('INVALID_REQUEST','请求标识无效。',422)
    return secretary.summary_operation(db,secretary.require_summary_run(db,id,key))

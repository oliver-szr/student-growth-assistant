"""HTTP contracts for reviewable task suggestions; no calendar writes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..task_breakdown_schemas import BreakdownCreate, BreakdownEdit, BreakdownResponse, BreakdownVersion
from ..services import task_breakdown
from ..services.claude_client import AIServiceError

router = APIRouter(prefix="/api/tasks/breakdown-drafts", tags=["Task Breakdown"])


@router.post("", response_model=BreakdownResponse, status_code=201)
async def create(payload: BreakdownCreate, db: Session = Depends(get_db)):
    try:
        return await task_breakdown.create_draft(db, payload)
    except AIServiceError as error:
        messages = {"AI_NOT_CONFIGURED": "AI 未配置，可以使用手动拆解。", "AI_UNAVAILABLE": "AI 暂时不可用，请重试或使用手动拆解。", "AI_RESPONSE_INVALID": "AI 建议格式、时长或日期无效，请重新生成或手动编辑。"}
        raise HTTPException(error.status_code, detail={"code": error.code, "message": messages[error.code]}) from None


@router.get("", response_model=list[BreakdownResponse])
def pending(db: Session = Depends(get_db)):
    return task_breakdown.list_drafts(db)


@router.get("/{draft_id}", response_model=BreakdownResponse)
def get(draft_id: int, db: Session = Depends(get_db)):
    return task_breakdown.get_draft(db, draft_id)


@router.patch("/{draft_id}", response_model=BreakdownResponse)
def edit(draft_id: int, payload: BreakdownEdit, db: Session = Depends(get_db)):
    return task_breakdown.edit_draft(db, draft_id, payload)


@router.post("/{draft_id}/confirm", response_model=BreakdownResponse)
def confirm(draft_id: int, payload: BreakdownVersion, db: Session = Depends(get_db)):
    return task_breakdown.confirm_draft(db, draft_id, payload)


@router.post("/{draft_id}/discard", response_model=BreakdownResponse)
def discard(draft_id: int, payload: BreakdownVersion, db: Session = Depends(get_db)):
    return task_breakdown.discard_draft(db, draft_id, payload)

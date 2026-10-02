"""Read-only parsing API: deliberately has no database session dependency."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from ..ai_schemas import ConstraintParseRequest, ConstraintParseResult
from ..services.claude_client import AIServiceError, ClaudeConfig, get_claude_config
from ..services.constraint_parser import current_shanghai_date, parse_constraint


router = APIRouter(prefix="/api/constraints", tags=["AI Parsing"])


def configured_claude() -> ClaudeConfig:
    try:
        return get_claude_config()
    except AIServiceError as error:
        raise HTTPException(error.status_code, detail={"code": error.code, "message": error.message}) from None


@router.post("/parse", response_model=ConstraintParseResult, responses={
    502: {"description": "AI_RESPONSE_INVALID: the provider response failed parsing or validation."},
    503: {"description": "AI_NOT_CONFIGURED or AI_UNAVAILABLE: optional AI parsing is unavailable."},
})
async def parse(
    payload: ConstraintParseRequest,
    config: ClaudeConfig = Depends(configured_claude),
    current_date: date = Depends(current_shanghai_date),
) -> ConstraintParseResult:
    try:
        return await parse_constraint(payload.text, config, current_date)
    except AIServiceError as error:
        raise HTTPException(error.status_code, detail={"code": error.code, "message": error.message}) from None

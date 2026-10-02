"""Read saved plan snapshots and optionally explain their deterministic diff."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..explanation_schemas import ExplanationRequest, ExplanationResponse
from ..models import PlanStatus
from ..services.claude_client import AIServiceError
from ..services.plan_diff import plan_diff
from ..services.plan_explanation import explain_diff, first_plan_explanation
from .plans import plan_response, require_plan


router = APIRouter(prefix="/api/plans", tags=["Plan Explanation"])


@router.post("/{candidate_id}/explanation", response_model=ExplanationResponse, responses={
    404: {"description": "PLAN_NOT_FOUND: the candidate or its saved baseline does not exist."},
    409: {"description": "PLAN_NOT_CANDIDATE or PLAN_BASELINE_INVALID: the requested snapshots cannot be explained."},
})
async def explain_candidate(
    candidate_id: int,
    payload: ExplanationRequest = ExplanationRequest(),
    db: Session = Depends(get_db),
) -> ExplanationResponse:
    # All DB access ends before provider latency. No writer reservation, mutation,
    # commit, scheduler call, revision bump, or explanation persistence.
    try:
        candidate = require_plan(db, candidate_id)
        if candidate.status != PlanStatus.candidate:
            raise HTTPException(409, detail={
                "code": "PLAN_NOT_CANDIDATE", "message": "Only a candidate plan can be explained.",
            })
        baseline = require_plan(db, candidate.based_on_plan_id) if candidate.based_on_plan_id is not None else None
        if baseline is not None and baseline.status not in (PlanStatus.confirmed, PlanStatus.superseded):
            raise HTTPException(409, detail={"code": "PLAN_BASELINE_INVALID", "message": "The candidate baseline is not a confirmed plan snapshot."})
        diff = plan_diff(
            plan_response(db, baseline).model_dump(mode="json") if baseline is not None else None,
            plan_response(db, candidate).model_dump(mode="json"),
        )
    finally:
        db.rollback()  # Release the read transaction before waiting on the provider.
    if diff["confirmed_plan_id"] is None:
        return ExplanationResponse(diff=diff, explanation=first_plan_explanation(payload.language), explanation_status="deterministic")
    try:
        explanation = await explain_diff(diff, payload.language)
    except AIServiceError:
        return ExplanationResponse(diff=diff, explanation=None, explanation_status="unavailable")
    return ExplanationResponse(diff=diff, explanation=explanation, explanation_status="available")

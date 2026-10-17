"""One bounded read-only endpoint for the Review analytics area."""
from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ..analytics_schemas import GrowthStatistics
from ..database import get_db
from ..services.growth_statistics import statistics

router = APIRouter(prefix="/api/growth", tags=["Growth Statistics"])


@router.get("/statistics", response_model=GrowthStatistics)
def get_statistics(weeks: int = Query(default=4, ge=1, le=12), end_week: date | None = None, db: Session = Depends(get_db)):
    return statistics(db, weeks, end_week)

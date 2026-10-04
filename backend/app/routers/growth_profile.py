"""Read-only personal profile and confirmed preference history endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import GrowthProfileRevision, GrowthUserProfile
from ..services.assistant_state import preference_settings

router = APIRouter(prefix="/api/growth", tags=["Personal Growth"])


@router.get("/profile")
def get_growth_profile(db: Session = Depends(get_db)) -> dict:
    profile = db.get(GrowthUserProfile, 1)
    preference = preference_settings(db)
    revisions = db.scalars(select(GrowthProfileRevision).order_by(GrowthProfileRevision.version.desc()).limit(20)).all()
    return {
        "direction": profile.direction if profile else "",
        "version": profile.version if profile else 1,
        "preferences": preference["settings"],
        "preferences_are_sample": preference["is_sample"],
        "history": [
            {"version": row.version, "direction": row.direction, "preferences": row.confirmed_preferences, "changed_at": row.changed_at.isoformat()}
            for row in reversed(revisions)
        ],
    }

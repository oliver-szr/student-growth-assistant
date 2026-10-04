"""Version snapshots for user-confirmed direction and long-term preferences."""

from datetime import timedelta

from ..models import AssistantPreference, GrowthProfileRevision, GrowthUserProfile, utc_now


def record_profile_revision(db, confirmed_preferences: dict | None = None) -> tuple[GrowthUserProfile, GrowthProfileRevision]:
    profile = db.get(GrowthUserProfile, 1)
    if profile is None:
        profile = GrowthUserProfile(id=1, direction="", version=1)
        db.add(profile)
        db.flush()
    else:
        profile.version += 1
        profile.updated_at = max(utc_now(), profile.updated_at + timedelta(microseconds=1))
    preferences = confirmed_preferences
    if preferences is None:
        from sqlalchemy import select
        from ..models import PreferenceRule
        if db.scalar(select(PreferenceRule.id).limit(1)) is not None:
            from .taxonomy import compile_preferences
            preferences = compile_preferences(db)
            preferences.pop("is_sample", None)
        else:
            row = db.get(AssistantPreference, 1)
            preferences = row.settings if row else {}
    revision = GrowthProfileRevision(
        version=profile.version,
        direction=profile.direction,
        confirmed_preferences=preferences,
        changed_at=utc_now(),
    )
    db.add(revision)
    db.flush()
    return profile, revision

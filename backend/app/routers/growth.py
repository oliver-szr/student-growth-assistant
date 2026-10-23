"""Compatibility router that assembles the personal-growth API by domain."""

from fastapi import APIRouter

from .growth_attention import _duration_advice
from .growth_attention import router as attention_router
from .growth_insights import router as insights_router
from .growth_profile import router as profile_router
from .growth_reviews import router as reviews_router
from .growth_statistics import router as statistics_router

router = APIRouter()
router.include_router(attention_router)
router.include_router(profile_router)
router.include_router(reviews_router)
router.include_router(insights_router)
router.include_router(statistics_router)

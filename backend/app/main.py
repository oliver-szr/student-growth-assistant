"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import models  # Register all tables with the existing Base.
from .models import AssistantRun
from .database import Base, engine
from .routers import dashboard, constraints, data, execution, goals, growth, plan_explanations, plans, tasks, task_breakdown, time_rules, assistant, taxonomy
from .services.growth_migrations import apply_growth_migrations
from .services.growth_data import create_daily_backup
from .services.schema_migrations import upgrade_database
from .services.planning_state import get_or_create_planning_state


class HealthResponse(BaseModel):
    status: str


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    if os.getenv("SGA_AUTO_BACKUP", "1") != "0":
        create_daily_backup(application.state.db_engine)
    # Schema changes run through versioned Alembic revisions, with backup first.
    upgrade_database(application.state.db_engine)
    with Session(application.state.db_engine) as session:
        apply_growth_migrations(session)
        get_or_create_planning_state(session)
        for run in session.query(AssistantRun).filter(AssistantRun.status=='running').all():
            run.status='interrupted'; run.phase='interrupted'
        session.commit()
    yield


app = FastAPI(lifespan=lifespan)
app.state.db_engine = engine
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174", "http://localhost:5175", "http://127.0.0.1:5175", "http://127.0.0.1:5187"],
    allow_methods=["GET", "POST", "PATCH", "PUT"],
    allow_headers=["Content-Type"],
)
app.include_router(dashboard.router)
app.include_router(task_breakdown.router)
app.include_router(tasks.router)
app.include_router(execution.router)
app.include_router(time_rules.router)
app.include_router(plans.router)
app.include_router(constraints.router)
app.include_router(plan_explanations.router)
app.include_router(assistant.router)
app.include_router(taxonomy.categories_router)
app.include_router(taxonomy.preferences_router)
app.include_router(taxonomy.settings_router)
app.include_router(goals.router)
app.include_router(growth.router)
app.include_router(data.router)


@app.get("/api/health", response_model=HealthResponse, tags=["Health"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")

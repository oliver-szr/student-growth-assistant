"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import models  # Register all tables with the existing Base.
from .database import Base, engine
from .routers import plans, tasks, time_rules
from .services.planning_state import get_or_create_planning_state


class HealthResponse(BaseModel):
    status: str


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    # create_all creates missing tables; it does not migrate existing tables.
    Base.metadata.create_all(bind=application.state.db_engine)
    with Session(application.state.db_engine) as session:
        get_or_create_planning_state(session)
        session.commit()
    yield


app = FastAPI(lifespan=lifespan)
app.state.db_engine = engine
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)
app.include_router(tasks.router)
app.include_router(time_rules.router)
app.include_router(plans.router)


@app.get("/api/health", response_model=HealthResponse, tags=["Health"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")

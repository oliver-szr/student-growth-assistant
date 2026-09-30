"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from pydantic import BaseModel

from . import models  # Register Task and TimeRule with the existing Base.
from .database import Base, engine
from .routers import tasks, time_rules


class HealthResponse(BaseModel):
    status: str


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    # create_all creates missing tables; it does not migrate existing tables.
    Base.metadata.create_all(bind=application.state.db_engine)
    yield


app = FastAPI(lifespan=lifespan)
app.state.db_engine = engine
app.include_router(tasks.router)
app.include_router(time_rules.router)


@app.get("/api/health", response_model=HealthResponse, tags=["Health"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")

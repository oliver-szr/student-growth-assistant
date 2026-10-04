"""Local export, restore, and backup inventory endpoints."""

from typing import Any
import sqlite3
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.growth_data import (
    _prepare_snapshot,
    build_snapshot,
    create_sqlite_backup,
    list_sqlite_backups,
    restore_snapshot,
)

router = APIRouter(prefix="/api/data", tags=["Local Data"])


@router.get("/export")
def export_user_data(db: Session = Depends(get_db)) -> dict:
    """Export app records as a versioned JSON document; environment secrets are never read."""
    return build_snapshot(db)


@router.post("/import")
def import_user_data(snapshot: dict[str, Any], db: Session = Depends(get_db)) -> dict:
    # Validate the complete envelope before writing a safety backup or opening a write transaction.
    _prepare_snapshot(snapshot)
    engine = db.get_bind()
    if os.getenv("SGA_SKIP_IMPORT_BACKUP") != "1":
        try:
            create_sqlite_backup(engine, force=True)
        except (OSError, sqlite3.Error, RuntimeError) as error:
            raise HTTPException(status_code=503, detail="无法创建恢复前备份，尚未导入数据") from error
    revision = restore_snapshot(db, snapshot)
    return {"status": "restored", "revision": revision, "message": "数据已恢复；旧的待确认方案已失效。"}


@router.get("/backups")
def list_local_backups(db: Session = Depends(get_db)) -> dict:
    return {"backups": list_sqlite_backups(db.get_bind())}

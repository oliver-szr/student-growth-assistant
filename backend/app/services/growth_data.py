"""Versioned JSON backup and transactional restore for the local single-user app."""

from datetime import date, datetime, time, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Boolean, Date, DateTime, Enum as SqlEnum, Integer, JSON, MetaData, String, Table, Time, delete, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..database import UTCDateTime
from ..models import AssistantProposal, AssistantRun, Base, GrowthChangeDraft, PlanningState, utc_now
from .planning_state import begin_planning_transaction, get_or_create_planning_state


FORMAT_VERSION = 2
MAX_SNAPSHOT_BYTES = 25 * 1024 * 1024
RETAIN_BACKUPS = 5


def _backup_root() -> Path:
    configured = os.getenv("SGA_BACKUP_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    repository = Path(__file__).resolve().parents[3]
    legacy = repository / "codex" / ".runtime" / "backups"
    return legacy if legacy.exists() else repository / "scripts" / ".runtime" / "backups"


def _database_path(engine: Engine) -> Path:
    name = engine.url.database
    if not name or name == ":memory:":
        raise ValueError("SQLite file database is required for backups")
    return Path(name).expanduser().resolve()


def _backup_dir(engine: Engine) -> Path:
    path = _database_path(engine)
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:10]
    return _backup_root() / f"{path.stem}-{digest}"


def create_sqlite_backup(engine: Engine, *, force: bool = False) -> Path | None:
    """Create a consistent SQLite backup with SQLite's online backup API."""
    try:
        source_path = _database_path(engine)
    except ValueError:
        return None
    if not source_path.exists() or source_path.stat().st_size == 0:
        return None

    folder = _backup_dir(engine)
    folder.mkdir(parents=True, exist_ok=True)
    today = datetime.now().astimezone().date().isoformat()
    daily_path = folder / f"{today}.sqlite"
    if daily_path.exists() and not force:
        return daily_path
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    nonce = uuid4().hex
    label = f"{timestamp}-{nonce}-pre-restore" if force else today
    destination = daily_path if not force else folder / f"{label}.sqlite"
    temporary = folder / f".{label}-{os.getpid()}-{nonce}.tmp"

    source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True, timeout=30)
    target = sqlite3.connect(temporary, timeout=30)
    try:
        source.backup(target)
        integrity = target.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RuntimeError("SQLite backup did not pass integrity_check")
        target.commit()
    finally:
        target.close()
        source.close()
    temporary.replace(destination)

    backups = sorted(folder.glob("*.sqlite"), key=lambda item: (item == destination, item.stat().st_mtime_ns, item.name), reverse=True)
    for old in backups[RETAIN_BACKUPS:]:
        try:
            old.unlink(missing_ok=True)
        except OSError:
            # A backup may be held open by an external SQLite viewer on Windows.
            # Keep startup/restores available and retry pruning the next time.
            continue
    return destination


def create_daily_backup(engine: Engine) -> Path | None:
    """Keep one startup snapshot per local day and at most five snapshots."""
    return create_sqlite_backup(engine, force=False)


def _encode_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def _decode_value(column, value: Any) -> Any:
    if value is None:
        if not column.nullable:
            raise ValueError("required field cannot be null")
        return None
    column_type = column.type
    if isinstance(column_type, SqlEnum):
        enum_type = column_type.enum_class
        if enum_type is None:
            return value
        try:
            return enum_type[value]
        except KeyError:
            return enum_type(value)
    if isinstance(column_type, UTCDateTime) or isinstance(column_type, DateTime):
        parsed = datetime.fromisoformat(value)
        if isinstance(column_type, UTCDateTime) and (parsed.tzinfo is None or parsed.utcoffset() is None):
            raise ValueError("timestamp must include a timezone offset")
        return parsed
    if isinstance(column_type, Date):
        return date.fromisoformat(value)
    if isinstance(column_type, Time):
        return time.fromisoformat(value)
    if isinstance(column_type, Boolean) and not isinstance(value, bool):
        raise ValueError("boolean field has the wrong type")
    if isinstance(column_type, Integer) and (not isinstance(value, int) or isinstance(value, bool)):
        raise ValueError("integer field has the wrong type")
    if isinstance(column_type, String) and not isinstance(value, str):
        raise ValueError("text field has the wrong type")
    return value


def build_snapshot(db: Session) -> dict:
    metadata: MetaData = Base.metadata
    tables: dict[str, list[dict[str, Any]]] = {}
    for table in metadata.sorted_tables:
        rows = db.execute(select(table)).mappings().all()
        tables[table.name] = [
            {column.name: _encode_value(row[column.name]) for column in table.columns}
            for row in rows
        ]
    state = db.get(PlanningState, 1)
    return {
        "format_version": FORMAT_VERSION,
        "exported_at": utc_now().isoformat(),
        "timezone": "UTC",
        "revision": state.revision if state else 0,
        "tables": tables,
    }


def _convert_legacy_v1(snapshot):
    """Validate exactly against the immutable v1 model before adding defaults."""
    import importlib.util
    from copy import deepcopy
    spec = importlib.util.spec_from_file_location("sga_backup_v1", Path(__file__).resolve().parents[2] / "alembic" / "baseline_models.py")
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    expected = baseline.Base.metadata.tables
    tables = snapshot["tables"]
    if set(tables) != set(expected):
        raise HTTPException(422, detail="旧v1备份的数据表与冻结版本不匹配")
    for name, table in expected.items():
        if not isinstance(tables[name], list) or any(not isinstance(row, dict) or set(row) != set(table.columns.keys()) for row in tables[name]):
            raise HTTPException(422, detail=f"旧v1备份数据表 {name} 的字段不匹配")
    converted = deepcopy(snapshot)
    converted["format_version"] = FORMAT_VERSION
    for row in converted["tables"]["tasks"]:
        row.update(parent_task_id=None, task_kind="executable", sort_order=0)
    return converted


def _prepare_snapshot(snapshot: dict) -> tuple[list[tuple[Table, list[dict]]], int]:
    if not isinstance(snapshot, dict) or set(snapshot) != {"format_version", "exported_at", "timezone", "revision", "tables"}:
        raise HTTPException(status_code=422, detail="备份文件结构不正确")
    try:
        size = len(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="备份文件包含无法读取的数据")
    if size > MAX_SNAPSHOT_BYTES:
        raise HTTPException(status_code=413, detail="备份文件超过 25 MB 限制")
    if type(snapshot["format_version"]) is not int or snapshot["format_version"] not in (1, FORMAT_VERSION):
        raise HTTPException(status_code=422, detail="不支持此备份版本")
    if snapshot["timezone"] != "UTC" or not isinstance(snapshot["tables"], dict):
        raise HTTPException(status_code=422, detail="备份时区或数据表结构无效")
    if type(snapshot["revision"]) is not int or snapshot["revision"] < 0:
        raise HTTPException(status_code=422, detail="备份版本号无效")
    if snapshot["format_version"] == 1:
        snapshot = _convert_legacy_v1(snapshot)

    metadata = Base.metadata
    expected = set(metadata.tables)
    if set(snapshot["tables"]) != expected:
        raise HTTPException(status_code=422, detail="备份中的数据表与当前版本不匹配")

    prepared: list[tuple[Table, list[dict]]] = []
    for table in metadata.sorted_tables:
        source_rows = snapshot["tables"].get(table.name)
        if not isinstance(source_rows, list):
            raise HTTPException(status_code=422, detail=f"数据表 {table.name} 格式无效")
        expected_columns = {column.name for column in table.columns}
        converted: list[dict] = []
        seen_primary_keys: set[tuple] = set()
        primary_key_names = [column.name for column in table.primary_key.columns]
        for source_row in source_rows:
            if not isinstance(source_row, dict) or set(source_row) != expected_columns:
                raise HTTPException(status_code=422, detail=f"数据表 {table.name} 的字段不匹配")
            try:
                row = {column.name: _decode_value(column, source_row[column.name]) for column in table.columns}
            except (TypeError, ValueError, KeyError) as error:
                raise HTTPException(status_code=422, detail=f"数据表 {table.name} 中有无效字段") from error
            key = tuple(row[name] for name in primary_key_names)
            if key in seen_primary_keys:
                raise HTTPException(status_code=422, detail=f"数据表 {table.name} 中有重复主键")
            seen_primary_keys.add(key)
            converted.append(row)
        prepared.append((table, converted))
    from ..assistant_schemas import Profile
    from .grid import GRID_MINUTES
    for table,rows in prepared:
        if table.name=='task_scheduling_profiles':
            for row in rows:
                settings=row['settings'] or {}
                try:Profile.model_validate({k:v for k,v in settings.items() if k!='task_type'})
                except Exception:raise HTTPException(status_code=422,detail='备份中有非法任务分段或时间约束') from None
        if table.name=='tasks':
            if any(row['duration_minutes']<=0 or row['duration_minutes']%GRID_MINUTES for row in rows):raise HTTPException(status_code=422,detail='备份任务时长不符合5分钟粒度')
    from .task_hierarchy import validate_backup_hierarchy
    validate_backup_hierarchy({table.name: rows for table, rows in prepared})
    return prepared, snapshot["revision"]


def restore_snapshot(db: Session, snapshot: dict) -> int:
    prepared, imported_revision = _prepare_snapshot(snapshot)
    begin_planning_transaction(db)
    try:
        db.execute(text("PRAGMA defer_foreign_keys=ON"))
        state = get_or_create_planning_state(db)
        next_revision = max(state.revision, imported_revision) + 1
        for table, _ in reversed(prepared):
            db.execute(delete(table))
        for table, rows in prepared:
            if rows:
                db.execute(table.insert(), rows)

        state = get_or_create_planning_state(db)
        state.revision = next_revision
        db.flush()
        # A restored snapshot must never revive a pending plan based on an old state.
        db.query(AssistantProposal).filter(AssistantProposal.status.notin_(["applied", "discarded"])).update(
            {AssistantProposal.status: "stale"}, synchronize_session=False
        )
        db.query(AssistantRun).filter(AssistantRun.status == "running").update(
            {AssistantRun.status: "interrupted", AssistantRun.phase: "interrupted"},
            synchronize_session=False,
        )
        db.query(GrowthChangeDraft).filter(GrowthChangeDraft.status == "ready").update(
            {GrowthChangeDraft.status: "stale"}, synchronize_session=False
        )
        db.commit()
        return next_revision
    except Exception as error:
        db.rollback()
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(status_code=422, detail="备份中的数据不完整，已撤销恢复操作") from error


def list_sqlite_backups(engine: Engine) -> list[dict]:
    folder = _backup_dir(engine)
    if not folder.exists():
        return []
    result = []
    for path in sorted(folder.glob("*.sqlite"), key=lambda item: item.stat().st_mtime_ns, reverse=True):
        result.append({"name": path.name, "size_bytes": path.stat().st_size, "created_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()})
    return result

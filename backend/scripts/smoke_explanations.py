"""Explicit real-provider Phase 7B smoke; isolated SQLite, no automatic retries.

Run from backend: python scripts/smoke_explanations.py --output PATH
Never prints credentials or raw provider envelopes. Synthetic plan snapshots only.
"""

import argparse
import hashlib
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import Base, create_sqlite_engine, get_db
from app.main import app
from app.services.claude_client import get_claude_config


def database_digest(engine):
    with engine.connect() as connection:
        rows = {table.name: [list(row) for row in connection.execute(table.select().order_by(*table.primary_key.columns))]
                for table in Base.metadata.sorted_tables}
    return hashlib.sha256(json.dumps(rows, default=str, sort_keys=True).encode()).hexdigest()


def run_case(case, database_path):
    engine = create_sqlite_engine(f"sqlite:///{database_path.as_posix()}")
    original_engine = app.state.db_engine
    def isolated_db():
        with Session(engine, autoflush=False) as session:
            yield session
    app.state.db_engine = engine
    app.dependency_overrides[get_db] = isolated_db
    try:
        with TestClient(app) as client:
            def post(path, body=None):
                response = client.post(path, json=body) if body is not None else client.post(path)
                if response.status_code not in (200, 201):
                    raise RuntimeError(f"Synthetic fixture failed: HTTP {response.status_code}")
                return response.json()
            def task(title, deadline="2026-10-06T18:00:00+08:00"):
                return post("/api/tasks", {"title": title, "duration_minutes": 60,
                                          "deadline": deadline, "priority": "normal"})["id"]
            def generate(ids):
                return post("/api/plans/candidates", {"week_start": "2026-10-05", "task_ids": ids})["candidate"]
            reading = task("Read Paper")
            selected = [reading]
            if case == "C_removed":
                selected.append(task("Practice Problems"))
            baseline = generate(selected)
            post(f"/api/plans/{baseline['id']}/confirm")
            if case == "A_moved":
                post("/api/time-rules", {"kind": "protected", "title": "Morning unavailable",
                     "recurrence": "once", "date": "2026-10-05", "start_time": "08:00", "end_time": "10:00"})
            elif case == "B_added_moved":
                selected.append(task("Emergency Report", "2026-10-05T12:00:00+08:00"))
            else:
                selected = [reading]
            candidate = generate(selected)
            before = database_digest(engine)
            start = time.monotonic()
            response = client.post(f"/api/plans/{candidate['id']}/explanation")
            elapsed = round(time.monotonic() - start, 3)
            body = response.json()
            return {"case": case, "http_status": response.status_code, "elapsed_seconds": elapsed,
                    "database_unchanged": before == database_digest(engine), "response": body}
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.state.db_engine = original_engine
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    config = get_claude_config()
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "configured_model": config.model,
              "timeout_seconds": 20, "max_tokens": 600, "automatic_retries": 0, "cases": []}
    with tempfile.TemporaryDirectory(prefix="phase7b-smoke-", dir=args.output.parent) as directory:
        for index, case in enumerate(("A_moved", "B_added_moved", "C_removed")):
            result = run_case(case, Path(directory) / f"case-{index}.db")
            report["cases"].append(result)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"case": case, "model": config.model, "elapsed_seconds": result["elapsed_seconds"],
                              "status": result["response"].get("explanation_status"),
                              "database_unchanged": result["database_unchanged"]}), flush=True)


if __name__ == "__main__":
    main()

# Student Growth Assistant

## Current status

Phase 2: Task + TimeRule backend CRUD for a single-user course MVP. The API now supports health checks and managing tasks, courses, and protected time. Plans, scheduling, AI, and the frontend are not implemented yet.

## Backend setup

From the project root in Windows PowerShell, create the dedicated Conda environment and install dependencies into it:

```powershell
conda create -n app_env python=3.11 -y
cd backend
conda run -n app_env python -m pip install -r requirements.txt
```

If PowerShell is already in `backend`, omit `cd backend`. `conda run -n app_env` ensures that the commands use `app_env`, even if Conda activation is not configured in the shell.
If `app_env` already exists, skip the `conda create` command.

## Run backend

From `backend`:

```powershell
conda run -n app_env --no-capture-output python -m uvicorn app.main:app --reload
```

From the project root:

```powershell
conda run -n app_env --no-capture-output python -m uvicorn app.main:app --app-dir backend --reload
```

The SQLite database path is based on `backend/app/database.py`, so either command uses `backend/data/app.db`.

## Test

From `backend`:

```powershell
conda run -n app_env --no-capture-output python -m pytest
```

Each test uses a temporary SQLite file under `backend/.pytest_tmp/` and removes that file afterward. Tests do not connect to or modify `backend/data/app.db`.

## Verify

- Health: http://127.0.0.1:8000/api/health
- Swagger UI: http://127.0.0.1:8000/docs

Use Swagger UI to try `GET`, `POST`, and `PATCH` for `/api/tasks` and `/api/time-rules`. For example, create a Task with this JSON:

```json
{
  "title": "Finish report",
  "description": "Coursework",
  "duration_minutes": 90,
  "deadline": "2026-10-05T18:00:00+08:00",
  "priority": "high"
}
```

Create a weekly course with:

```json
{
  "kind": "course",
  "title": "Software Engineering",
  "recurrence": "weekly",
  "weekday": 3,
  "start_time": "10:00",
  "end_time": "12:00"
}
```

New Tasks default to `status: "todo"`; new TimeRules default to `active: true`. To cancel a Task, `PATCH` its `status` to `"cancelled"`. To deactivate a TimeRule, `PATCH` its `active` field to `false`. There are no DELETE endpoints.

Task deadlines must include a timezone offset, such as `2026-10-05T22:00:00+08:00`. The API returns UTC with an offset (for example, `2026-10-05T14:00:00Z`). SQLite stores UTC clock values without an offset; the SQLAlchemy model restores UTC timezone information when reading them. Python code should compare these timezone-aware model datetimes with other timezone-aware datetimes. TimeRule dates and clock times describe local `Asia/Shanghai` time.

The app uses a local SQLite database and creates missing tables on startup with `Base.metadata.create_all`. This keeps the course MVP simple; it does not change existing table schemas. A production application should use database migrations, but this MVP does not use Alembic.

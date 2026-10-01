# Student Growth Assistant

## Current status

Phase 6: the non-AI deterministic planning and replanning MVP is available in the browser. React manages Tasks, Courses & Protected Time, and Weekly Plan. The existing Plan APIs persist Candidates and atomically confirm them with revision stale protection; Scheduler, Validator, models, and transactions retain their Phase 4/5 behavior. AI is not implemented.

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

API and persistence tests use temporary SQLite files under `backend/.pytest_tmp/` and remove those files afterward. Scheduler and Validator tests use plain Python data in memory. Tests do not connect to or modify `backend/data/app.db`.

## In-memory scheduling (Phase 4)

`backend/app/services/scheduler.py` exposes `schedule_week(week_start, selected_tasks, time_rules)`. Inputs use the small frozen dataclasses in `scheduling_types.py`; `week_start` is a Monday date, deadlines are timezone-aware, and TimeRule clock times describe local Shanghai time. The scheduler returns either complete task assignments or `unschedulable` with reasons and no partial assignments. It validates a successful result using `validator.py` before returning it.

The heuristic sorts by deadline, priority, and task ID, then chooses each task's earliest continuous slot. It does not backtrack or split tasks, and `unschedulable` does not prove that no legal schedule exists. See [Phase 4 implementation](docs/architecture.md#phase-4-当前实现) for the Python interface, checks, and limitations.

## Persisted plans (Phase 5)

Use Swagger at `/docs` to exercise the new backend flow:

1. Create the Tasks and TimeRules, then send `POST /api/plans/candidates` with a Monday `week_start` and a nonempty list of unique `todo` Task IDs, for example `{"week_start":"2026-10-05","task_ids":[1]}`.
2. On success, HTTP `200` returns `status: "feasible"`, a saved `candidate`, and an empty `unscheduled_tasks`. Inspect the saved plan with `GET /api/plans/{id}`.
3. Send `POST /api/plans/{id}/confirm` with no body to confirm that stored Candidate. Query the official plan with `GET /api/plans/confirmed?week_start=2026-10-05`.

Candidate generation calls the frozen Scheduler and independently validates its assignments before saving task and active course snapshots. Protected intervals constrain placement and are never PlanItems. Existing official plans remain unchanged until Confirm; `based_on_plan_id` records the current same-week official plan when generating a Candidate.

Startup creates the missing tables and safely initializes `PlanningState(id=1, revision=0)`. Task/TimeRule creation, every successful PATCH (including empty or unchanged PATCH), and successful confirmation increment the global revision once. GET, Candidate generation, and rejected operations do not increment it. Every write route reserves SQLite's writer with `BEGIN IMMEDIATE` before reading, then commits business writes and any revision increment together. Candidate computation holds that reservation until it is saved, keeping its input snapshot consistent.

Confirm rejects stale Candidates with HTTP `409 STALE_CANDIDATE`; generate a new Candidate after a Task, TimeRule, or official plan changes. Confirm uses the saved items without rerunning Scheduler. It atomically supersedes the previous same-week official plan, confirms the Candidate, and increments revision. A partial unique index enforces one confirmed plan per week. Other Candidates remain viewable but become stale; confirming a confirmed or superseded plan returns `409 PLAN_NOT_CANDIDATE`.

An incomplete greedy result returns HTTP `409 UNSCHEDULABLE` with task reasons and saves no plan. A feasible result rejected by Validator is HTTP `500`; it is never persisted. See [API contract](docs/api-contract.md) and [architecture](docs/architecture.md) for response fields and transaction details. The Phase 6 UI uses these existing APIs without changing their contract.

## Frontend setup and run

Open a second Windows PowerShell window. From the project root:

Use Node.js 20.19+ or 22.12+; Phase 3 verification used Node.js 24.13.0.

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Vite requires port 5173 and exits if it is occupied, keeping its origin consistent with backend CORS. Keep the backend running in the first window. The frontend uses `http://127.0.0.1:8000` by default. To use a different backend URL, copy `.env.example` to `.env` in `frontend`, edit `VITE_API_BASE_URL`, and restart Vite. No secret belongs in this frontend setting.

To check the frontend from `frontend`:

```powershell
npm test
npm run build
```

Task deadlines are entered and displayed in fixed Shanghai time (UTC+08:00). The frontend sends an offset-aware value such as `2026-10-05T22:00:00+08:00`; the API may return the same instant as `2026-10-05T14:00:00Z`. Weekly and one-time protected time use Shanghai local dates and clock times.

## Complete browser MVP workflow (Phase 6)

1. In **Tasks**, add at least two todo tasks with a duration, deadline, and priority. Choose deadlines that allow scheduling in the week you intend to demonstrate.
2. In **Courses & Protected Time**, add weekly courses and any protected intervals. Courses appear in plans; protected time constrains placement without becoming a PlanItem.
3. Open **Weekly Plan**. It defaults to the current Shanghai week's Monday. Selecting any date converts it to that week's Monday, displayed as **Week of YYYY-MM-DD**. Changing weeks clears the selection and Candidate, then loads that week's Confirmed Plan.
4. Select the todo tasks to schedule. Each checkbox shows title, duration, Shanghai deadline, and priority. Done and cancelled tasks are excluded. Select at least one task before generating.
5. Click **Generate Candidate** and review its Task and Course timeline in Shanghai time. **Plan details** shows source revision and the previous official plan ID. A Candidate remains separate from **Current Confirmed Plan**.
6. Click **Confirm Candidate**. Only a successful server response replaces the displayed Confirmed Plan and clears the Candidate. The page then reloads the official plan from the backend.
7. To demonstrate emergency replanning, create a normal Task with **high** priority and a deadline, return to Weekly Plan, and select the original tasks plus the new task. Generate and review the new Candidate alongside the unchanged current plan, then Confirm to supersede the old plan.
8. If a Task, TimeRule, or official plan changes after generation, Confirm may return **STALE_CANDIDATE**. The outdated preview stays visible and Confirm is disabled; explicitly generate a new Candidate. **UNSCHEDULABLE** lists task IDs, titles where available, and backend reasons; it means the current heuristic did not find a complete plan.

Leaving Weekly Plan for another tab preserves its Candidate and selections; returning reloads Tasks and the official plan. A full browser refresh resets the selected week to the current Shanghai week and discards the in-memory Candidate and selections. Open Weekly Plan to reload the persisted Confirmed Plan. Candidates remain stored in SQLite but are not automatically restored; there is no localStorage or latest-Candidate endpoint.

Loading and request errors appear on the page. **Reload tasks & confirmed plan** and **Retry** allow recovery after the backend returns. Failed Generate/Reload requests retain previously displayed plans for the selected week. A missing official plan (`404 PLAN_NOT_FOUND`) displays **No confirmed plan for this week.** as a normal empty state. Generate and Confirm cannot overlap or be submitted repeatedly while pending.

Phase 6 verification: backend **231 passed** with one existing Starlette/httpx dependency deprecation warning; frontend **19 passed**; production build successful without warnings. Real FastAPI + Vite browser checks covered initial planning and refresh, emergency replacement, stale rejection and regeneration, unschedulable tasks, and backend shutdown/recovery using an isolated demo SQLite database. Development `backend/data/app.db` was preserved. See [Phase 6 evidence](docs/architecture.md#phase-6-浏览器联调与回归) for details and limitations.

## Verify

- Health: http://127.0.0.1:8000/api/health
- Swagger UI: http://127.0.0.1:8000/docs

The browser app supports Task and TimeRule management and the full Candidate/Confirm flow without Swagger. Swagger UI remains available to inspect the API. For example, create a Task with this JSON:

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

The backend allows browser requests from `http://localhost:5173` and `http://127.0.0.1:5173` for local development. Other frontend origins need an explicit CORS configuration change.

See [Phase 3 verification](docs/phase3-verification.md) for the file list, browser checks, test results, and current limitations.

# Student Growth Assistant

## Project Overview

Student Growth Assistant is a deterministic weekly planning and replanning web application with optional AI-assisted input parsing and plan-change explanation.

## Features

- Task management
- Course and protected time management
- Weekly deterministic scheduling
- Candidate preview
- User confirmation
- Emergency replanning
- Stale candidate protection
- Natural-language TimeRule proposal
- Deterministic Plan diff
- Optional AI explanation

## Tech Stack

Backend: Python 3.11+, FastAPI, SQLAlchemy, SQLite, Pydantic and pytest. Frontend: React, Vite, JavaScript and native CSS. AI: Anthropic Messages-compatible API via a configurable gateway; the actual model is configurable and may not be Claude.

## Current status

Phase 7A adds optional natural-language TimeRule parsing to the stable non-AI MVP. Phase 7B adds local deterministic plan differences and optional AI explanation on explicit request. React manages Tasks, Courses & Protected Time, and Weekly Plan. Scheduler, Validator, database models, Candidate/Confirm transactions, and stale semantics retain their Phase 4/5 behavior. The combined Phase 7A + 7B independent code review is PASS WITH FIXES. The previous 7A gate recheck passed the delete input but still timed out on confirm and the control input; those availability records are preserved. See [Phase 7A verification](docs/phase7a-verification.md) and [Phase 7B verification](docs/phase7b-verification.md). Phase 8 final stabilization covers regression, startup documentation and an isolated demo; final v1.0 Gate Review and Git delivery remain separate steps.

## Backend setup

Use a terminal where `conda` is available (Anaconda Prompt or an initialized PowerShell). From the project root, create the dedicated Conda environment and install dependencies into it:

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
The backend runs at http://127.0.0.1:8000. Start the frontend in a second terminal using the commands below.

## Test

From `backend`:

```powershell
conda run -n app_env --no-capture-output python -m pytest
```

API and persistence tests use temporary SQLite files under `backend/.pytest_tmp/` and remove those files afterward. Scheduler and Validator tests use plain Python data in memory. Tests do not connect to or modify `backend/data/app.db`.

If an old pytest temporary directory has local ACL errors, use a fresh isolated path instead of changing application code:

```powershell
conda run -n app_env --no-capture-output python -m pytest --basetemp=../.pytest_tmp/final-regression-fresh
```

## Optional AI Configuration

AI parsing and explanation are optional. They share the **Anthropic Messages-compatible API via configurable New API gateway**, with `POST /v1/messages` on the configured gateway and top-level `system`. The model name comes from your gateway console and is never hardcoded.

Anthropic Messages-compatible gateway; actual model is configurable and may not be Claude. The current smoke configuration uses **MiniMax-M3**. Existing `claude_client.py` / `CLAUDE_*` names are retained for compatibility, not as a model claim. `CLAUDE_BASE_URL` accepts a gateway origin or its `/v1` API base, with an optional trailing slash; do not append `/messages`. The client normalizes the version suffix to avoid `/v1/v1/messages`.

Copy `backend/.env.example` to `backend/.env` and configure locally:

```dotenv
CLAUDE_API_KEY=
CLAUDE_BASE_URL=https://newapi.iomgaa.online
CLAUDE_MODEL=
CLAUDE_API_VERSION=2023-06-01
```

The backend loads only its own `.env`; process environment takes precedence. Restart after changing configuration. `.env` is ignored by Git. Keep the key backend-only; never use a `VITE_` key or send it to the browser. `python-dotenv` is the only new dependency; HTTP uses the existing `httpx`.

Missing key or model does not prevent startup or manual Task/TimeRule/planning use. Only parsing returns `503 AI_NOT_CONFIGURED`. Provider requests have a total 20-second deadline, and the frontend parse request has a 25-second timeout. Network/HTTP failures return `503 AI_UNAVAILABLE`; invalid content, JSON, schemas, or TimeRule combinations return `502 AI_RESPONSE_INVALID`, with fixed safe messages.

AI configuration is optional. AI provider availability is external and optional; core planning remains available when AI is unavailable. There is no automatic retry or fallback model.

The configured model produces an untrusted structured proposal. The proposal is validated by deterministic backend rules. The user must review and explicitly apply it through the existing TimeRule workflow. AI does not directly modify Tasks, Plans, or the database.

## Phase 7B: Explain candidate changes

In Weekly Plan, **Explain Changes** is available for a Candidate with a saved confirmed baseline. It runs only when clicked. **Changes** lists Added, Moved, Not included in candidate, and Unchanged using saved Task IDs/times and Shanghai display time. The comparison uses `candidate.based_on_plan_id`, including a now-superseded historical snapshot, rather than whichever plan is currently confirmed. A first Candidate displays **First plan for this week.** without calling AI.

AI summarizes the observable differences between the confirmed snapshot and candidate plan. It receives only the locally computed structured diff and an independent explanation prompt. No scheduler decision trace exists, so the explanation does not infer hidden causal reasoning. General scheduling policy is documented as background; first-version prose is restricted to observed changes. Removed means not included in the candidate, never deletion of a Task.

`POST /api/plans/{candidate_id}/explanation` returns HTTP 200 with the diff even if AI is unconfigured, unavailable, or rejected. **AI explanation unavailable** keeps planning and Confirm usable. The endpoint reads snapshots, releases its read transaction before waiting on the shared 20-second provider request, and does not persist explanations or change revision. The frontend deadline is 25 seconds; there is no automatic retry. New Candidates, week changes, and successful Confirm clear explanation state; late responses from old Candidates are ignored. Outdated Candidates may still be explained but retain their deterministic warning and blocked Confirm.

Verification: backend **395 passed**, frontend **46 passed**, production build and whitespace checks passed. The combined independent review added URL normalization, explicit prohibited-claim guards, and a UTC label for AI explanation times (Changes remains Shanghai). Four bounded real requests returned available explanations without invented causes or confirmation pressure; the final moved-case check included the timezone clarification. No automatic retries or timeout increase. Browser evidence from the earlier implementation is historical; this review used code/session tests and isolated API smoke. See [AI Layer independent review](docs/ai-layer-review.md) for results and limitations.

To explicitly run three real smoke cases using synthetic plans and isolated SQLite, from `backend`:

```powershell
conda run -n app_env --no-capture-output python scripts/smoke_explanations.py --output ../.pytest_tmp/phase7b-evidence/new-smoke.json
```

This consumes provider calls, loads local backend configuration, and makes one call per case without retries. Normal pytest mocks AI and does not consume provider usage.

In **Courses & Protected Time**, describe one interval and select **Parse with AI**. Supported results are weekly courses, weekly protected time, and one-time protected time. Missing or ambiguous details produce **More information needed**; task/plan commands produce **Unsupported request**. Dates and clock times use Shanghai semantics, and the backend supplies the current Shanghai date explicitly.

Review **AI Proposal**, edit the prefilled `TimeRuleForm`, then click **Apply time rule**. Only that click uses the existing `POST /api/time-rules`, saves the rule with normal defaults, and increments revision once. Older Candidates then become stale through the existing checks. **Discard**, Parse, clarification, and unsupported never write data. Manual create/edit/deactivate remains available when AI fails.

Automated pytest and Node tests use mocked AI/HTTP and never call a paid provider. The separate real smoke checklist includes the original seven examples plus three scope/injection inputs in [Phase 7A verification](docs/phase7a-verification.md); perform Apply demos only on an isolated database.

## In-memory scheduling (Phase 4)

The local minute-granularity improvement accepts any positive integer Task duration and tries starts every minute from 08:00 through 21:59. Assignments have zero seconds and microseconds and must finish by 22:00 and the deadline. The released `v1.0.0` tag remains unchanged. See the [Chinese user guide](docs/USER_GUIDE_ZH.md) for the minute-level workflow.

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

## Isolated Demo Database

Normal startup uses `backend/data/app.db`; there is no environment variable for changing this path. For a clean classroom demo, stop the normal backend and run the following from the project root in PowerShell. It uses the same `app.state.db_engine` and `get_db` overrides as the existing test harness, without changing project files or touching the development database:

```powershell
@'
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))
import uvicorn
from sqlalchemy.orm import Session
from app.main import app
from app.database import create_sqlite_engine, get_db

with tempfile.TemporaryDirectory(prefix="sga-demo-") as directory:
    engine = create_sqlite_engine(f"sqlite:///{Path(directory).as_posix()}/demo.db")
    def demo_db():
        with Session(engine, autoflush=False) as session:
            yield session
    app.state.db_engine = engine
    app.dependency_overrides[get_db] = demo_db
    try:
        uvicorn.run(app, host="127.0.0.1", port=8000)
    finally:
        engine.dispose()
'@ | conda run -n app_env --no-capture-output python -
```

Start Vite normally in a second terminal. The demo starts empty; enter the data below through the UI. Stop this backend with Ctrl+C when finished; normal shutdown removes its temporary database. Do not use `--reload` with this in-process harness. Restarting the normal backend returns to the unchanged development database; no backup/restore or new database configuration is needed.

## Demo Flow

Use an isolated temporary database for acceptance demos and keep development data unchanged. All planning dates/times use Shanghai time.

1. Add two Tasks with 60-minute durations and deadlines within the selected week.
2. Add a weekly Course and a Protected Time interval through the manual form.
3. Open Weekly Plan and choose the intended week's Monday.
4. Select both Tasks and click Generate Candidate.
5. Review the timeline and click Confirm Candidate.
6. Add an emergency Task with high priority and an earlier deadline.
7. Select the original Tasks plus the emergency Task and generate a new Candidate. Review it alongside the unchanged Confirmed Plan.
8. Optionally use Explain Changes, then confirm the replacement Candidate when satisfied. AI parsing can also be used during rule entry in step 2: review/Apply one protected interval proposal. If AI is unavailable, use the manual form and deterministic Changes.

The app generates a complete selected week; it does not freeze past or started blocks. For a presentation, select a future week and use matching deadlines. Replanning requires selecting all Tasks you want in the replacement plan. A smaller selection excludes omitted Tasks from the Candidate without deleting them.

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

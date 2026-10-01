# 项目目录结构与文件说明

当前为 Phase 6：已实现 FastAPI 健康检查、Task / TimeRule CRUD 与 React 管理界面、冻结的 Scheduler / Validator、Plan 持久化、Candidate / Confirm API 与 revision stale protection，以及非 AI Weekly Plan UI。SQLite FK 已启用；AI 未实现。

```text
student-growth-assistant/
├── .gitattributes
├── .gitignore
├── README.md
├── DIRECTORY_STRUCTURE.md
├── docs/
│   ├── architecture.md
│   ├── api-contract.md
│   └── phase3-verification.md
├── backend/
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── plans.py
│   │   │   ├── tasks.py
│   │   │   └── time_rules.py
│   │   └── services/
│   │       ├── __init__.py
│   │       ├── planning_state.py
│   │       ├── scheduling_types.py
│   │       ├── scheduler.py
│   │       └── validator.py
│   ├── data/
│   │   └── .gitkeep
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py
│       ├── test_cors.py
│       ├── test_foreign_keys.py
│       ├── test_health.py
│       ├── test_planning_state.py
│       ├── test_plans.py
│       ├── test_scheduler.py
│       ├── test_tasks.py
│       ├── test_time_rules.py
│       └── test_validator.py
└── frontend/
    ├── .env.example
    ├── index.html
    ├── package.json
    ├── package-lock.json
    ├── vite.config.js
    ├── src/
    │   ├── main.jsx
    │   ├── App.jsx
    │   ├── api.js
    │   ├── constants.js
    │   ├── datetime.js
    │   ├── planning.js
    │   ├── styles.css
    │   ├── pages/
    │   │   ├── TasksPage.jsx
    │   │   ├── TimeRulesPage.jsx
    │   │   └── WeeklyPlanPage.jsx
    │   └── components/
    │       ├── TaskForm.jsx
    │       ├── TimeRuleForm.jsx
    │       ├── PlanPreview.jsx
    │       └── PlanTimeline.jsx
    └── tests/
        ├── api.test.js
        ├── datetime.test.js
        └── planning.test.js
```

| 路径 | 用途 |
|---|---|
| `README.md` | `app_env` 后端与 npm 前端安装、运行、测试和完整非 AI MVP 浏览器操作流程。 |
| `.gitignore` | 忽略环境变量、本地 SQLite 文件、缓存、测试临时目录和前端构建产物。 |
| `.gitattributes` | 固定自身及源码、文档等文本文件的 LF 行尾。 |
| `docs/architecture.md` | Phase 0 冻结架构、Phase 1–6 实现与 Phase 6 浏览器验收证据。 |
| `docs/api-contract.md` | 已实现的 health、Task、TimeRule 与 Phase 5 Plan API 请求、响应和冲突契约。 |
| `docs/phase3-verification.md` | Phase 3 文件清单、浏览器联调证据、测试结果与限制。 |
| `backend/app/main.py` | FastAPI 应用、health、开发环境 CORS、全部路由注册、启动时创建缺失表并初始化 singleton。 |
| `backend/app/database.py` | production engine、共享 `create_sqlite_engine`、Session 工厂、Base 和 `get_db`；每连接 connect event 开启 SQLite FK。 |
| `backend/app/models.py` | Task、TimeRule、Plan、PlanItem、PlanningState ORM 表、受限枚举、CHECK 与同周唯一 confirmed partial index。 |
| `backend/app/schemas.py` | CRUD 与 Candidate / Plan 请求响应模型，Monday、唯一非空 task_ids 等校验。 |
| `backend/app/routers/tasks.py`、`time_rules.py` | Task / TimeRule CRUD；业务写入与 revision 同事务，每次成功 PATCH 统一 bump。 |
| `backend/app/routers/plans.py` | Candidate 生成与独立校验、保存任务/课程快照、Plan GET，以及原子 Confirm / stale 检查。 |
| `backend/app/services/planning_state.py` | BEGIN IMMEDIATE、singleton 幂等初始化与 SQL revision increment；helper 不自行 commit。 |
| `backend/app/services/scheduling_types.py` | 仅含固定时区、小型 frozen dataclass 与输入异常；不依赖 ORM。 |
| `backend/app/services/scheduler.py` | 确定性 earliest-slot 排程，只读输入，返回内存结果。 |
| `backend/app/services/validator.py` | 原始输入检查、规则展开与独立 assignment 校验。 |
| `backend/app/services/__init__.py` | 服务包说明；不注册业务路由或启动逻辑。 |
| `backend/tests/conftest.py` | 使用共享 engine factory，每个测试创建独立临时 SQLite 文件、启用 FK 并覆盖数据库依赖。 |
| `backend/tests/test_foreign_keys.py` | 5 个 FK 用例：每连接启用、Plan based_on 和 PlanItem 的 Plan/Task/TimeRule 引用拒绝及 rollback 后 Session 恢复。 |
| `backend/tests/test_planning_state.py` | 32 个初始化、revision、CRUD 故障原子性与并发初始化/自增用例。 |
| `backend/tests/test_plans.py` | 40 个 Candidate / Confirm / GET、快照、stale、独立 Validator gate、DB 唯一性、回滚和并发用例。 |
| `backend/tests/test_scheduler.py` | 70 个 Scheduler 用例，覆盖确定性、排序、占位、连续时段、边界和贪心限制。 |
| `backend/tests/test_validator.py` | 45 个 Validator 用例，主要使用人工构造的 assignment，验证约束和独立性。 |
| `backend/tests/test_cors.py`、`test_health.py`、`test_tasks.py`、`test_time_rules.py` | 原有 39 个 API、持久化、非法输入与 CORS 回归用例。 |
| `backend/pytest.ini` | 将 pytest 临时目录放在仓库内的忽略路径。 |
| `backend/data/.gitkeep` | 保留数据目录；本地 `app.db` 被 Git 忽略。 |
| `frontend/src/App.jsx` | 三个页面的本地状态切换；Weekly Plan 保持 mounted 以保留 Candidate。 |
| `frontend/src/api.js` | 集中处理 CRUD/Plan HTTP 请求、结构化业务错误、网络错误与 timeout。 |
| `frontend/src/constants.js` | React 组件间共享的纯常量 WEEKDAYS。 |
| `frontend/src/datetime.js` | Task/Plan datetime 固定上海转换、纯日期 Monday 归一和上海当前周计算。 |
| `frontend/src/planning.js` | 按上海日期分组 PlanItems，保持 API 顺序并格式化时间段。 |
| `frontend/src/pages/TasksPage.jsx`、`TimeRulesPage.jsx` | Task、课程与保护时间的列表和操作。 |
| `frontend/src/pages/WeeklyPlanPage.jsx` | week/todo selection、Candidate/Confirmed 独立 state、Generate/Confirm、stale/unschedulable/retry。 |
| `frontend/src/components/TaskForm.jsx`、`TimeRuleForm.jsx` | 创建与编辑复用的表单。 |
| `frontend/src/components/PlanPreview.jsx` | Candidate/Confirmed 标题、状态、元数据和 Confirm 按钮。 |
| `frontend/src/components/PlanTimeline.jsx` | 分日期展示 Task/Course 的 title_snapshot 与上海时间段。 |
| `frontend/tests/datetime.test.js` | 独立于浏览器时区的时间转换测试。 |
| `frontend/tests/api.test.js` | CRUD 422/网络错误，以及 Plan wrapper、结构化业务错误、timeout/recovery 和不可解析响应。 |
| `frontend/tests/planning.test.js` | Monday 日期边界、上海当前周、timeline 分组/顺序/快照及不同本地时区一致性。 |
| `frontend/package-lock.json` | 锁定 npm 安装的具体依赖版本。 |

运行和测试时还会生成 `__pycache__/`、`.pytest_cache/`、`.pytest_tmp/`、`backend/data/app.db`、`frontend/node_modules/` 和 `frontend/dist/`，均不属于源码，继续由 Git 忽略。pytest 和浏览器联调使用隔离 SQLite，不连接开发 app.db。当前 backend 231 个测试、frontend 19 个测试均通过，production build 成功；Phase 6 没有修改后端核心逻辑或增加依赖，AI 未实现。

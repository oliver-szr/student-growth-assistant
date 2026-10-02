# 项目目录结构与文件说明

当前进行 Phase 8 最终稳定化与交付准备，功能冻结为 Phase 1–7。SQLite FK、Scheduler / Validator、Candidate / Confirm 与 AI 边界保持不变。旧阶段验收保留历史证据；联合审核见 docs/ai-layer-review.md。Phase 8 不新增业务源码、依赖、API 或报告文件。

```text
student-growth-assistant/
├── .gitattributes
├── .gitignore
├── README.md
├── DIRECTORY_STRUCTURE.md
├── docs/
│   ├── architecture.md
│   ├── api-contract.md
│   ├── USER_GUIDE_ZH.md
│   ├── ai-layer-review.md
│   ├── phase7a-verification.md
│   ├── phase7b-verification.md
│   └── phase3-verification.md
├── backend/
│   ├── .env.example
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── ai_schemas.py
│   │   ├── explanation_schemas.py
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── plans.py
│   │   │   ├── constraints.py
│   │   │   ├── plan_explanations.py
│   │   │   ├── tasks.py
│   │   │   └── time_rules.py
│   │   └── services/
│   │       ├── __init__.py
│   │       ├── claude_client.py
│   │       ├── constraint_parser.py
│   │       ├── plan_diff.py
│   │       ├── plan_explanation.py
│   │       ├── planning_state.py
│   │       ├── scheduling_types.py
│   │       ├── scheduler.py
│   │       └── validator.py
│   ├── data/
│   │   └── .gitkeep
│   ├── scripts/
│   │   ├── smoke_constraints.py
│   │   └── smoke_explanations.py
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py
│       ├── test_claude_client.py
│       ├── test_constraints.py
│       ├── test_plan_diff.py
│       ├── test_plan_explanations.py
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
    │   ├── timeRules.js
    │   ├── explanations.js
    │   ├── styles.css
    │   ├── pages/
    │   │   ├── TasksPage.jsx
    │   │   ├── TimeRulesPage.jsx
    │   │   └── WeeklyPlanPage.jsx
    │   └── components/
    │       ├── TaskForm.jsx
    │       ├── TimeRuleForm.jsx
    │       ├── NaturalLanguageTimeRule.jsx
    │       ├── PlanPreview.jsx
    │       ├── PlanExplanation.jsx
    │       └── PlanTimeline.jsx
    └── tests/
        ├── api.test.js
        ├── datetime.test.js
        ├── planning.test.js
        ├── explanations.test.js
        └── timeRules.test.js
```

| 路径 | 用途 |
|---|---|
| `README.md` | app_env/npm 安装、运行、测试，完整非 AI MVP 和可选 AI 配置/解析流程。 |
| `.gitignore` | 忽略环境变量、本地 SQLite 文件、缓存、测试临时目录和前端构建产物。 |
| `.gitattributes` | 固定自身及源码、文档等文本文件的 LF 行尾。 |
| `docs/architecture.md` | 冻结架构、Phase 1–7 实现与 AI proposal/解释的只读边界。 |
| `docs/api-contract.md` | health、Task、TimeRule、Plan、parse 和 explanation 的请求、响应和错误契约。 |
| `docs/USER_GUIDE_ZH.md` | 面向普通用户和课程演示者的中文指南，包含启动、分钟级任务/时间规则、确认、重规划、可选 AI 和完整演示。 |
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
| `backend/tests/conftest.py` | 每例独立 SQLite/FK/DB override；自动禁用 dotenv/Claude env，并禁止未 mock 的 AI 调用。 |
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
| `backend/.env.example` | 四个历史 CLAUDE_* 环境变量的无密钥模板；真实配置仅在忽略的 backend/.env。 |
| `backend/app/ai_schemas.py` | strict、extra-forbid 的请求、八字段 proposal 与三种 status result。 |
| `backend/app/routers/constraints.py` | 无 DB Session 的只读 POST parse；safe structured AI errors。 |
| `backend/app/services/claude_client.py` | 可配置 gateway 的 /v1/messages、headers、20 秒 timeout、text 提取与安全错误。 |
| `backend/app/services/constraint_parser.py` | 上海当前日期与 prompt、最小 fence normalization、json.loads、AI schema 与既有 TimeRuleCreate 校验。 |
| `backend/scripts/smoke_constraints.py` | 显式运行的真实 provider 10 输入 smoke；与 pytest 分离，不使用数据库，报告不含 key/raw provider body。 |
| `backend/tests/test_claude_client.py` | 28 个 mock HTTP/config/date 用例；不访问真实 provider。 |
| `backend/tests/test_constraints.py` | 73 个三状态/schema/组合校验/无 SQL/无 revision/Apply stale 用例。 |
| `frontend/src/components/NaturalLanguageTimeRule.jsx` | AI textarea、局部状态、preview、复用可编辑表单、Apply/Discard。 |
| `frontend/src/timeRules.js` | proposal 映射、weekday/date 展示、共用 TimeRule form payload、classification 文案。 |
| `frontend/tests/timeRules.test.js` | 12 个 parse wrapper、AI failure/timeout、字段映射和既有 Apply endpoint 测试。 |
| `docs/phase7a-verification.md` | Phase 7A 实际回归、隔离浏览器、provider smoke 与局限记录。 |
| `backend/app/explanation_schemas.py` | language 请求、四类 diff、summary 与三种 explanation_status 的响应契约。 |
| `backend/app/services/plan_diff.py` | 无 ORM/AI/Scheduler 的纯 snapshot 比较；task_id identity、UTC interval、稳定排序。 |
| `backend/app/services/plan_explanation.py` | 独立 prompt、structured diff 输入、文本检查、首次计划双语 fallback；复用既有 provider。 |
| `backend/app/routers/plan_explanations.py` | POST explanation；历史 based_on snapshot、读事务释放、stale 允许与 HTTP 200 diff-only 降级。 |
| `backend/scripts/smoke_explanations.py` | 明确执行的三例真实 smoke；合成数据、隔离 SQLite、无重试、无密钥输出。 |
| `backend/tests/test_plan_diff.py`、`test_plan_explanations.py` | 63 个 diff/endpoint/prompt/安全降级用例；所有 pytest provider 均 mock。 |
| `frontend/src/explanations.js` | 四类展示映射、请求 session 防重复与旧响应隔离。 |
| `frontend/src/components/PlanExplanation.jsx` | Explain、Changes、AI Explanation、首次计划与 outdated warning；由 Candidate ID key 挂载。 |
| `frontend/tests/explanations.test.js` | 8 个请求/timeout、展示映射、首次计划、重复/显式触发、生命周期隔离与恢复测试。 |
| `docs/phase7b-verification.md` | 23 项交付说明、376/45 测试、浏览器、smoke、只读与限制证据。 |
| `docs/ai-layer-review.md` | 联合独立审核、395/46 回归、最小修复和有界真实 provider smoke；旧阶段记录保留。 |

运行和测试时还会生成 `__pycache__/`、`.pytest_cache/`、`.pytest_tmp/`、`backend/data/app.db`、`frontend/node_modules/` 和 `frontend/dist/`，均不属于源码，继续由 Git 忽略。pytest 和浏览器联调使用隔离 SQLite，不连接开发 app.db。当前 backend 395 个测试、frontend 46 个测试通过，production build 成功；Phase 7B 没有增加依赖。Phase 7A 只增加 python-dotenv，复用已有 httpx，没有 AI framework。此前 Phase 6 的 frontend 19 为历史快照，7A 为 38。

最新独立审核与小修复、真实 provider 和权限边界结论见 `docs/ai-layer-review.md`；旧 verification 文档保留其当时的测试计数和历史证据。

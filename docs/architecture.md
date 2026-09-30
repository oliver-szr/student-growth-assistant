# Student Growth Assistant 架构（Phase 0 冻结版）

本文依据已审核的 Phase 0 降复杂度修订，并记录 Phase 1–6 的实际实现。已完成 Task / TimeRule 管理、冻结的 Scheduler / Validator、Plan 持久化与 Candidate / Confirm API，以及非 AI Weekly Plan 浏览器流程。AI 尚未实现。

## 技术与边界

- 前端：React、Vite、JavaScript、原生 CSS、`fetch`。App 本地 state 切换 Tasks、Courses & Protected Time、Weekly Plan 三个页面，不使用 Router。
- 后端：Python、FastAPI、Pydantic、同步 SQLAlchemy、SQLite。使用 pytest 测试。
- 单用户，无登录、微服务、Docker、异步数据库或 Alembic。
- 核心流程：录入任务与课程/保护时间 → 生成 Candidate Plan → 预览 → 用户 Confirm → 替换该周 Confirmed Plan。
- 新候选在 Confirm 前不能修改正式计划。AI 不能直接修改正式计划；它仅用于后续的自然语言限制解析和计划变化解释，输出必须经过 Pydantic 与程序校验。
- 排程与约束检查由程序完成；Scheduler 和 Validator 分开。无法排入全部任务时返回 `unschedulable`，不声称数学上无解。

## 冻结的数据模型（Phase 2 和 Phase 5 实现）

| 表 | 字段与规则 |
|---|---|
| Task | `id`、`title`、可选 `description`、`duration_minutes`、`deadline`、`priority`（`low/normal/high`）、`status`（`todo/done/cancelled`）、`created_at`、`updated_at`。时长为 30 分钟的正整数倍；只有 `todo` 可参与新排程；取消而不硬删除。突发任务也是 Task。 |
| TimeRule | `id`、`kind`（`course/protected`）、`title`、`recurrence`（`weekly/once`）、`weekday`、`date`、`start_time`、`end_time`、`active`、时间戳。`weekly` 只用 `weekday`，`once` 只用 `date`；`start_time < end_time`，不跨午夜；停用而不硬删除。没有 Course 表。 |
| Plan | `id`、`week_start`、`status`（`candidate/confirmed/superseded`）、可空 `based_on_plan_id`、`source_revision`、JSON `task_ids`、`created_at`、可空 `confirmed_at`。第一版不存完整 `input_snapshot`。 |
| PlanItem | `id`、`plan_id`、`kind`（`task/course`）、可空 `task_id`、可空 `time_rule_id`、`title_snapshot`、`start_at`、`end_at`。保护时间参与计算和校验，不存为 PlanItem。 |
| PlanningState | 仅一行：`id = 1`，`revision` 为非负整数，初始 0。成功创建 Task / TimeRule、每次成功 PATCH（含空 PATCH 或相同值）或 Confirm 时递增一次；查询、生成候选和失败不递增。数据修改与递增在同一事务中。 |

同一周最多有一个 `confirmed` Plan，可有多个 `candidate`。Confirm 时旧正式计划变为 `superseded`，新计划确认且 revision 递增；三者在同一事务中完成，并由数据库唯一约束保护。

## 冻结的排程规则（Phase 4 实现）

- 时区固定为 `Asia/Shanghai`；用户指定从周一到下周一的完整周。Task deadline 的 API 输入必须带时区偏移，API 输出统一为 UTC。SQLite 以不含偏移的 UTC 钟面值保存日期时间；SQLAlchemy 读回时恢复为带 UTC 时区的 Python `datetime`，供后续代码安全比较。TimeRule 日期与钟面时间按上海本地时间理解。
- 用户明确选择本周的 `todo` 任务；不自动选择全部待办。
- 每天可用时间为 08:00–22:00，按 30 分钟网格尝试起点。任务必须连续完成，不拆分。
- 时间区间采用 `[start, end)`。课程与保护时间先占用时间；保护时间禁止安排灵活任务，但与课程重叠不代表课程取消。
- 任务按 deadline 升序、同 deadline 的 priority 从高到低、再按 task ID 升序排序。依次寻找截止时间前最早的连续合法时段；不回溯、不移动已排任务。
- 全部排入后由独立 Validator 检查任务恰好出现一次、时长、deadline、周范围、时间窗口、网格、相互冲突以及课程和保护时间。校验失败是实现错误，不能保存候选。
- 排不下时返回 `unschedulable` 和未安排任务；不保存可确认候选，不修改正式计划。Phase 5 API 返回 `409 UNSCHEDULABLE`，使用原文：`Could not generate a complete plan under the current scheduling heuristic.`
- 不处理已开始/已结束任务块、实时执行状态或自动冻结历史；演示使用未来时间或完整指定周。

## Phase 4 当前实现

Phase 4 新增 `backend/app/services/scheduler.py`、`validator.py` 与一个小型内部数据文件 `scheduling_types.py`。这三个冻结服务文件仅依赖 Python 标准库，使用 frozen dataclass 和 tuple 保存输入与输出；不导入 ORM、FastAPI 或 LLM，不查询或写入数据库，不修改 Task / TimeRule。Phase 5 在外部路由接入持久化，未修改这三个文件或其既有测试。

### 输入与输出

```python
schedule_week(week_start, selected_tasks, time_rules) -> ScheduleResult
validate_schedule(week_start, selected_tasks, time_rules, assignments) -> ValidationResult
```

- `week_start`：Python `date`，必须是 Monday，且完整七天可被 datetime 表示。
- `selected_tasks`：显式给出的 `TaskInput` 序列，字段为 `id, title, duration_minutes, deadline, priority, status`；只接受 `todo`，ID 唯一，时长为正的 30 分钟倍数，deadline 必须 aware。不会自动选择其他任务。
- `time_rules`：`TimeRuleInput` 序列，字段为 `id, kind, title, recurrence, start_time, end_time, weekday, date, active`。日期与钟面时间为纯 Python `date` / 无 offset 的 `time`。
- 成功：`ScheduleResult(status="feasible", assignments=(Assignment(...), ...), unscheduled_tasks=())`。Assignment 含 `task_id, title, start_at, end_at`；顺序为任务尝试顺序，时间均为 aware +08:00。
- 未完成：`ScheduleResult(status="unschedulable", assignments=(), unscheduled_tasks=(UnscheduledTask(...), ...))`。每项含 `task_id, reason_code="NO_SLOT_FOUND", message`；不返回部分安排。
- 输入非法：Scheduler 抛 `SchedulingInputError`，带 `INVALID_WEEK`、`INVALID_TASKS` 或 `INVALID_TIME_RULES` 的 `code`，与正常的 `unschedulable` 区分。非法时长不会被取整。
- Validator 返回 `ValidationResult(valid=..., violations=(Violation(...), ...))`；每项含 `code, message, task_ids`。非法原始输入同样返回结构化 violation。

### 排序、网格与时区

排序为 `deadline → priority(high > normal > low) → task id`。deadline 先转换为固定 UTC+08:00 比较，因此不同 offset 表示的同一 instant 会正确进入后续 tie-break。

排程采用 **deterministic earliest-slot heuristic**：对每个任务，从 Monday 开始，依次检查七天中每天 08:00、08:30、…、21:30，共最多 196 个候选起点。只有整个连续区间能在当天 08:00–22:00 内完成、不晚于 deadline、不占用课程 / 保护时间 / 已安排任务时才放置。任务可恰好在 22:00 或 deadline 结束。超过 14 小时的任务直接报告找不到时段，不拆分，也避免构造超范围 timedelta。失败后仍检查剩余任务以收集全部失败项；任何失败使整体结果不完整。

内部统一使用标准库 `timezone(timedelta(hours=8), name="Asia/Shanghai")` 的固定 aware 时区，不依赖电脑本地时区、pytz 或系统 zoneinfo 数据。weekly 规则先用上海日期和 weekday 找到 occurrence，再组合本地 start_time / end_time。once 仅在本周 `[Monday, next Monday)` 内生效。inactive 规则不占位；所有输入规则仍须结构合法。规则时刻不要求位于 30 分钟网格，排程器不会把课程或保护时间边界取整。

active course-course 的半开区间重叠属于 `INVALID_TIME_RULES`，即使未选择任务也会拒绝。course-protected、protected-protected 重叠允许存在；它们共同阻止任务占用该时间。课程本身可以位于任务工作窗口外。本阶段结果只包含 task assignments，不输出 course block；课程仍从原始 TimeRule 展开为约束。

### Validator 的独立性

Validator 不调用或导入 Scheduler，不重新排程后对比，也不相信结果的 status。它从原始 selected_tasks 和 TimeRule 重新检查：任务完整性 / 唯一性 / 未选择 ID、精确时长、aware datetime、上海周范围、同一天 08:00–22:00、起点网格（含秒 / 微秒）、deadline、task-task、task-course、task-protected 冲突，并检查课程输入合法性与 course-course 冲突。

Scheduler 仅复用 Validator 的原始输入检查与 TimeRule 展开函数；放置逻辑与 assignment 检查逻辑各自实现。两侧都使用 `[start, end)`；首尾相接合法。Scheduler 在返回 feasible 前调用独立 Validator，若发现 violation 则抛实现错误，而不返回伪成功。

### 限制与验收

- greedy，no backtracking，no task splitting，不移动已经安排的任务，不搜索最优解。
- **does not guarantee finding a schedule if another ordering might work.** `unschedulable` 仅表示当前 heuristic 没有生成完整安排，不是数学上的无解证明。
- 测试中的反例：Monday 09:30–11:00 为保护时间；30 分钟任务截止 11:30，90 分钟任务截止 12:00。当前规则先放短任务到 08:00，使长任务找不到连续时段；若长任务先放 08:00–09:30、短任务放 11:00–11:30，Validator 确认该替代安排合法。
- 固定上海时区、完整指定周、不考虑当前时间；仅纯 Python 内存接口，不包含持久化或产品排程入口。

2026-09-30 实际验收：Scheduler 70 个用例，Validator 45 个用例；后端完整 pytest 为 **154 passed**（原有 39 + 新增 115），仅保留一条既有 Starlette/httpx 依赖弃用警告。前端未改功能，`npm test` 为 **6 passed**，`npm run build` 成功，无构建 warning。新增服务的独立进程导入检查不加载 SQLAlchemy / FastAPI，Validator 导入也不加载 Scheduler。

## Phase 5 当前实现

### 数据与初始化

`models.py` 新增 `plans`、`plan_items`、`planning_state`。Plan 的 `week_start` 为 Date，`task_ids` 为 JSON；Plan 与 PlanItem 时间戳继续使用现有 `UTCDateTime`，SQLite 存 UTC 钟面值，ORM / API 返回 aware UTC。status 与 kind 由数据库枚举 CHECK 限制；PlanItem CHECK 保证 task/course 分别只引用 Task/TimeRule，区间时长为正。PlanningState CHECK 限制 id=1 且 revision 非负。

启动仍使用 `Base.metadata.create_all` 创建缺失表，然后在同一初始化 Session 内调用 `get_or_create_planning_state` 并 commit。该 helper 使用 SQLite `INSERT ... ON CONFLICT DO NOTHING`，不存在时创建 revision=0，已存在时保留当前 revision。helper 自身不 commit；`bump_revision` 使用 SQL `revision = revision + 1`，同样不 commit。没有 Alembic 或独立 revision API。

### 事务与 Candidate

所有 Task / TimeRule POST、PATCH 及 Candidate / Confirm 都先在新请求 Session 中执行 `BEGIN IMMEDIATE`，在读取正式状态前取得 SQLite 写入保留锁。这样并发请求不会基于旧 revision 或不一致的 Task / TimeRule 组合写入。Candidate 的计算也在该事务内；这是单用户、小规模 MVP 的串行写入取舍，计算期间其他写请求会等待 SQLite 默认锁超时。GET 不获取写入保留锁。

Task / TimeRule mutation、revision increment、flush、响应构造与一次 commit 在同一 try 块内；响应在 commit 前构造，Task 的 UTC 读回行为保持不变。任何异常都 rollback 并重新抛出。每个成功 PATCH 统一 bump 一次，包括 `{}` 和相同值。无效输入、缺失资源与其他失败均不 bump。

Candidate 流程：校验 Monday 与非空唯一正整数 task_ids → 读取 singleton revision → 查询并检查所有选中 Task 存在且 todo → 读取 TimeRule 与同周 confirmed → 转为 Phase 4 frozen 输入 → `schedule_week` → 独立调用 `validate_schedule` → 用现有 `expand_time_rules` 展开 course → 原子保存 Plan 和 items → commit。task_ids 保留用户请求顺序，source_revision 保存读取的 revision，based_on_plan_id 指向当时的同周 confirmed 或 null。

Task item 用 ORM Task.title 保存 title_snapshot；course item 用 ORM TimeRule.title 与既有展开区间保存。仅保存 active course，不保存 protected 或 inactive course。GET 直接返回历史快照，按 start_at、kind、id 升序，不用当前标题覆盖旧值。

Scheduler 输入异常映射为 422；正常 `unschedulable` 映射为 409 `UNSCHEDULABLE` 并提供原因；feasible 输出若被独立 Validator 拒绝则为 500 `GENERATED_SCHEDULE_INVALID`。这些情况均 rollback，不新增 Plan / PlanItem、不 bump revision，也不修改旧 confirmed。Candidate 成功只增加候选，不修改正式状态或 revision。

### Confirm 与 stale

Confirm 的唯一输入为路径中的 Plan ID，不接收前端上传的安排。事务内依次读取 PlanningState、已保存 Plan，检查存在、status=candidate、source_revision 等于当前 revision，再读取同周 confirmed。缺失返回 404 `PLAN_NOT_FOUND`；非 candidate（含重复确认）返回 409 `PLAN_NOT_CANDIDATE`；旧 revision 返回 409 `STALE_CANDIDATE`，不自动重排。

有旧 confirmed 时先设为 superseded 并 flush，释放 partial unique index 的旧条目；flush 不 commit，仍可回滚。然后将候选设为 confirmed、写 confirmed_at、bump revision、flush 并构造响应，最终只 commit 一次。数据库 partial unique index `one_confirmed_plan_per_week` 对 `status='confirmed'` 的 week_start 强制唯一。任何失败都回滚旧 status、新 status、confirmed_at 和 revision。其他周的正式计划不变。

Confirm 不重跑 Scheduler，也不再次运行 Validator；确认的就是生成时已通过独立 Validator 的已保存安排，revision 相等保证期间所有受支持的正式状态修改都已被检测。A / B 从同一 revision 生成后，Confirm A 会 bump，使 B 保持 candidate 但不能确认。Task / TimeRule mutation 同样使所有旧 revision 候选 stale；候选保留，可继续 GET。

### Phase 5 验收与边界

2026-09-30 后端完整 `python -m pytest`：**226 passed**，其中原有 Phase 1–4 的 154 个用例、新增 PlanningState 32 个和 Plan 40 个。新增测试覆盖 singleton 自动初始化、revision 全部语义、每种 CRUD 写入的故障回滚、Candidate 输入/校验/无写入失败/课程快照、Confirm 替换/stale/状态拒绝/其他周隔离，以及数据库唯一性绕过尝试后的 Session 恢复。

原子性测试在 Confirm 的两个 Plan status 和 revision 已实际 flush 后注入 SQLAlchemyError 或 RuntimeError，验证三者与 confirmed_at 一起回滚。并发测试验证首次初始化与 revision increment 不丢失、两个同 revision 候选最多一个确认成功，以及 Candidate 生成时并发 Task 修改等待保存后才提交。

前端回归 `npm test` 为 **6 passed**，`npm run build` 成功，无 build warning。后端仅保留既有 Starlette TestClient/httpx 弃用警告。开发 app.db 前后 SHA-256 均为 `067DA30A177C38A70C40D7FEB00A23A5304B63F9A8D67E2D9572E708BD782FBA`；冻结的 Phase 4 服务与测试、前端源码/配置/测试 hash 均未变化。

`git diff --check` 退出 0、无空白错误，普通命令出现已有 `.gitignore` 的 LF→CRLF 转换提示；以单次 `-c core.safecrlf=false` 运行检查无输出，未修改 Git 配置或 `.gitignore`。数据库、pytest 临时目录、node_modules 和 dist 仍被忽略，本阶段未 stage、commit 或 push。

Phase 5 验收时仍为单用户全局 revision；修改无关任务或其他周规则也会使旧候选 stale。只支持现有 SQLite MVP 与 create_all，不提供迁移、历史候选清理、Plan 编辑、AI 或新约束接口。周计划 React UI 在下述 Phase 6 接入。Phase 4 的 greedy 限制保持原样，直接绕过受支持 API 修改 Task / TimeRule 不在 revision 保护范围内。

Phase 5 FK cleanup 后，production engine 和 pytest test_engine 共同使用 `database.py` 的 `create_sqlite_engine`。engine 的 SQLAlchemy `connect` event 在每个 DBAPI connection 建立时执行 `PRAGMA foreign_keys=ON`。新增 5 个测试检查每连接启用、四种外键拒绝不存在的引用，以及 IntegrityError rollback 后 Session 可继续使用；排序 tie fixture 使用真实 TimeRule ID。后端总数为 231。

## Phase 6 当前实现

`WeeklyPlanPage.jsx` 负责周选择、todo Task checkbox、Generate/Confirm、loading 和业务错误；`PlanPreview.jsx` 展示正式或候选计划，`PlanTimeline.jsx` 展示按上海日期分组的 Task/Course 快照。`planning.js` 仅含分组和时间段格式化函数。只增加这些小组件/纯函数，无 Router、状态库、日历库、存储或 npm 依赖。

所有 HTTP URL 仍集中于 `api.js`，新增四个 Plan wrapper。共用请求处理保留 HTTP status、结构化 detail/code，并继续处理 FastAPI 422、网络错误、15 秒 timeout 和不可解析响应。Weekly Plan 实际使用 Candidate、Confirmed 和 Confirm 接口；`getPlan` wrapper 可读取已有 ID，无新增 endpoint。

### 日期、状态与错误

默认周显式对当前 instant 加 UTC+08:00，再取上海日期并归一为 Monday。纯日期用数值年月日构造 UTC calendar fields，使用 UTC getters，不解析 date-only 字符串后做本地时区转换。PlanItem 时间复用 `datetime.js` 的固定上海转换；timeline 保持 backend 返回的顺序和 title_snapshot，不用当前 Task 标题覆盖快照。

`candidatePlan` 与 `confirmedPlan` 各有独立 state。Generate 成功只替换 Candidate；请求开始和失败均保留已有 Candidate/Confirmed。Confirm 成功先使用返回的 confirmed 数据、清空 Candidate，再重新 GET 官方状态；后续 GET 失败时保留已成功确认的返回值。正常 `404 PLAN_NOT_FOUND` 是空状态，读取错误和 loading 分开显示。

STALE_CANDIDATE 保留预览并标记 Outdated candidate，禁用 Confirm，提示用户显式重新 Generate；PLAN_NOT_CANDIDATE 使用后端 message 并阻止再次确认。UNSCHEDULABLE 显示未排 Task ID、可映射标题和 reason/message，不声称数学无解。网络/timeout 错误结束 loading，可 Reload/Retry，不自动 Generate 或 Confirm。

同步 `useRef` guard 和按钮 disabled 防止 Generate/Confirm 重复提交或重叠。读请求 effect 在 week、active 或刷新版本变化时忽略旧响应。WeeklyPlanPage 在 App 中保持 mounted，通过 hidden wrapper 切换可见性；返回该页重新加载 Tasks/Confirmed，同时保留 Candidate。切换周清空选择和 Candidate；完整刷新回默认周，Confirmed 从后端重新加载，Candidate 不自动恢复。

Task selection 只过滤 todo，不在前端重复 Scheduler 的 deadline/week 判断。少于一个任务时前端显示 Select at least one task.，不发送生成请求。laptop 下 Candidate 与 Confirmed 双列，800px 以下上下排列，仅显示有 PlanItems 的日期。

### Phase 6 浏览器联调与回归

实际启动 FastAPI + Vite，使用仓库外独立 `demo.db`，覆盖 `get_db` 和 app.state.db_engine，沿用现有 SQLite engine factory。浏览器创建所有演示 Tasks/TimeRules；没有向开发 app.db 写入。

| 检查 | 实际结果 |
|---|---|
| Flow A 首次计划 | 2 个 todo Task、Monday 09:00–10:00 course 与 10:00–11:00 protected；生成 Candidate #1，显示 Task/Course，不显示 protected，Confirmed 为空。Confirm #1 成功，刷新后正式计划重新读取。 |
| Flow B Emergency | 浏览器新增 high-priority Task，生成 Candidate #2 与 Confirmed #1 同时显示。生成前后 Plan #1 完整 GET JSON 一致；Confirm #2 后 #1 superseded，旧 items 保留。 |
| Flow C stale | Candidate #3 生成后到 Tasks 修改标题，返回仍保留候选；Confirm 返回 STALE_CANDIDATE、outdated 且禁用按钮，Confirmed #2 完整 JSON 不变。重新生成 #4 并确认成功。 |
| Flow D unschedulable | 900 分钟 Task 返回 UNSCHEDULABLE，显示标题、ID 和原因，不新增 Plan，Confirmed #4 不变。随后已有 Candidate #5 时再次失败，#5 和正式计划都保留。 |
| Flow E API failure | 实际停止隔离 backend，再 Generate/Reload：显示连接错误并结束 loading，Confirmed #4/Candidate #5 保留。重启同一 demo.db 后 Reload 与 Generate 恢复。 |
| 其他交互 | 任意日期归一 Monday，0 Task 提示，done/cancelled 不可选，换周清空候选与选择，正常 404 空状态，PLAN_NOT_CANDIDATE 使用后端提示并禁用按钮；Plan details 展示 revision/based_on ID；600px 布局上下排列。 |

2026-10-01 最终前端 `npm test`：**19 passed**（既有 6 + 新增 13）；测试四个 Plan wrapper、结构化 404/409/500、timeout/recovery、不可解析响应、Monday 跨月/年/闰日、上海 Monday 午夜边界、分组顺序/快照和 UTC/Los Angeles/Kiritimati 环境一致性。`npm run build` 成功，无 build warning。后端完整 `python -m pytest`：**231 passed, 1 warning**，仅既有 Starlette/httpx 依赖弃用提示。浏览器控制台检查无 React/Fast Refresh warning；Flow E 的断网是主动测试。

开发 app.db SHA-256 前后均为 `067DA30A177C38A70C40D7FEB00A23A5304B63F9A8D67E2D9572E708BD782FBA`。37 个保护文件 hash 均未变化，覆盖后端源码/测试、依赖清单/lock、Vite 配置、既有 Task/TimeRule 页面/表单及开发数据库。没有 stage、commit、push 或实现 AI。

`git diff --check` 退出 0，无空白错误；普通命令仍有既有 `.gitignore` LF→CRLF 提示，单次使用 `-c core.safecrlf=false` 时无输出，未改 Git 配置。新增/修改的前端和文档另做空白检查，因为尚未跟踪的文件不进入普通 diff。数据库、缓存、node_modules 和 dist 未被跟踪；隔离联调日志和截图保存在仓库外，验收后停止本次 demo 服务。

限制：仍使用 Phase 4 greedy heuristic，不保证找到其他排序可能找到的合法解；不考虑当前时刻或冻结已执行块。全局 revision 会使无关修改后的候选 stale。完整刷新不恢复 Candidate、无 Plan History/编辑/拖拽/自动重排；没有引入浏览器 E2E 测试框架，组件流程由实际浏览器联调验证。

## 分阶段实现

| 阶段 | 范围与独立验收 |
|---|---|
| Phase 1 | FastAPI、SQLite、Session、health；后端可启动，health 200，数据库连接与 pytest 通过。 |
| Phase 2 | Task、TimeRule 模型和 CRUD；`/docs` 可创建/查询/修改，重启后保留，非法输入被拒绝。 |
| Phase 3 | React 页面管理 Task 与 TimeRule；浏览器操作和错误展示可用。 |
| Phase 4 | 确定性 Scheduler 与独立 Validator；用内存数据验证排序、冲突、deadline、`unschedulable`。 |
| Phase 5 | Plan、PlanItem、PlanningState、Candidate/Confirm；候选不改正式计划，旧候选返回 409，事务安全。 |
| Phase 6 | 周计划界面；无 AI 时完成录入、生成、预览、确认、加入突发任务、重新确认的完整流程。 |
| Phase 7 | 自然语言限制解析与 AI 解释；校验和用户应用后才能保存限制，AI 失败不阻断 Phase 6。 |
| Phase 8 | 错误处理、pytest 回归、README、演示与 GitHub 准备。 |

Phase 2 使用已有的 SQLAlchemy `Base`、engine、Session 和 `get_db`，启动时用 `Base.metadata.create_all` 创建缺失的 `tasks`、`time_rules` 表。课程 MVP 不使用 Alembic；`create_all` 不会迁移已存在的表结构。HTTP 输入输出由 Pydantic schema 处理，路由直接使用 Session；API pytest 每例使用独立临时 SQLite 文件，不连接开发数据库。Phase 3 前端直接调用已冻结的 CRUD API，不新增业务表或计划接口。Phase 4 的服务与测试仅使用内存数据。

# Student Growth Assistant API 契约（Phase 5）

统一使用 `/api` 前缀。下表核心 API 均已实现；Task / TimeRule 请求响应保持原契约，Plan 接口按已审核的 Phase 5 要求实现。

Phase 6 仅新增前端接入；本文件中的 endpoint、schema、status code、revision 与事务契约均保持 Phase 5 行为。

| 方法 | 路径 | 阶段 | 用途 |
|---|---|---|---|
| GET | `/api/health` | 1 | 健康检查 |
| GET | `/api/tasks` | 2 | 查询任务 |
| POST | `/api/tasks` | 2 | 创建任务 |
| PATCH | `/api/tasks/{id}` | 2 | 修改、完成或取消任务 |
| GET | `/api/time-rules` | 2 | 查询课程与保护时间 |
| POST | `/api/time-rules` | 2 | 创建时间规则 |
| PATCH | `/api/time-rules/{id}` | 2 | 修改或停用规则 |
| POST | `/api/plans/candidates` | 5 | 生成候选计划 |
| GET | `/api/plans/confirmed?week_start=...` | 5 | 查询指定周正式计划 |
| GET | `/api/plans/{id}` | 5 | 查询候选或历史计划 |
| POST | `/api/plans/{id}/confirm` | 5 | 确认候选计划 |

不提供硬删除接口。当前没有 `POST /api/plans/check`、`POST /api/constraints/parse` 或 AI API。

Phase 3 浏览器界面使用上述已实现的七个接口，不改变其请求和响应。`datetime-local` 视为固定上海时间：例如 `2026-10-05T22:00` 发送为 `2026-10-05T22:00:00+08:00`；收到 `2026-10-05T14:00:00Z` 时仍显示 `22:00`。编辑保护时间从 `weekly` 切到 `once` 时明确发送 `weekday: null`，反向切换时明确发送 `date: null`。

## Phase 6：Weekly Plan 前端接入

`frontend/src/api.js` 提供 `createCandidatePlan(data)`、`getPlan(id)`、`getConfirmedPlan(weekStart)`、`confirmPlan(id)`，URL 和 fetch 集中在该文件。Weekly Plan 提交纯 Date Monday `week_start` 和用户选择的非空 todo `task_ids`；任意所选日期在前端归一为该周 Monday，默认周按显式 UTC+08:00 当前日期计算。PlanItem 的 UTC datetime 复用固定上海转换后显示。

前端将 Candidate 与 Confirmed 分别保存。生成成功或失败均不替换当前正式计划；Confirm 成功后使用服务端返回值并重新 GET Confirmed。生成失败保留旧候选和正式计划，读取失败保留同周已经显示的数据；换周主动清空旧周数据。完整刷新只重新加载 Confirmed，不恢复 Candidate。

`ApiError` 保留 HTTP status、detail.code 和原 detail。404 PLAN_NOT_FOUND 在 Confirmed 查询时显示正常空状态；409 STALE_CANDIDATE 保留 outdated 预览、禁用 Confirm；409 PLAN_NOT_CANDIDATE 展示后端 message、禁用 Confirm；409 UNSCHEDULABLE 展示 task_id、可映射标题和 message/reason_code。其他 422/500、网络错误和 timeout 使用共用可读错误处理，不自动重排或确认。

## Phase 1：健康检查

`GET /api/health` 无请求体、无认证。成功返回 HTTP `200`：

```json
{"status": "ok"}
```

FastAPI 提供 `/docs` Swagger UI 和 `/openapi.json`。它们是开发文档入口，不是业务 API。

## Phase 2：Task

`POST /api/tasks` 接收 `title`、可空 `description`、`duration_minutes`、带时区偏移的 ISO 8601 `deadline`，以及可选 `priority`（`low/normal/high`，默认 `normal`）。`title` 去除首尾空格后必须非空；时长必须大于零且是 30 的倍数。创建时不接受 `status`、ID 或时间戳。成功返回 `201` 和完整 Task；`status` 默认为 `todo`。

完整 Task 响应字段为 `id`、`title`、`description`、`duration_minutes`、`deadline`、`priority`、`status`（`todo/done/cancelled`）、`created_at`、`updated_at`。例如输入 `2026-10-05T22:00:00+08:00`，读回的 API deadline 为 `2026-10-05T14:00:00Z`。SQLite 保存不含偏移的 UTC 钟面值；SQLAlchemy ORM 读回为带 UTC 时区的 `datetime`。创建与修改都拒绝无时区的 deadline。

`GET /api/tasks` 按 ID 升序返回列表，可选 `status=todo|done|cancelled`。`PATCH /api/tasks/{id}` 可部分修改 `title`、`description`、`duration_minutes`、`deadline`、`priority`、`status`；未提供字段保持原值，明确传入 `description: null` 可清空备注。更新会刷新 `updated_at`。资源不存在返回 `404`；非法字段或取值返回 `422`。取消使用 `PATCH status=cancelled`，没有 DELETE。

## Phase 2：TimeRule

`POST /api/time-rules` 接收 `kind`（`course/protected`）、`title`、`recurrence`（`weekly/once`）、`weekday`、`date`、`start_time`、`end_time`、可选 `active`（默认 `true`），成功返回 `201` 和完整 TimeRule。响应还包括 `id`、`created_at`、`updated_at`。

`weekly` 必须有 1–7 的 `weekday`，且 `date` 为空；`once` 必须有 `date`，且 `weekday` 为空。`course` 只允许 `weekly`。`title` 去空格后非空；`start_time < end_time`，不支持跨午夜。时间字段是上海本地钟面时间，不附带时区偏移。

`GET /api/time-rules` 按 ID 升序返回全部规则。`PATCH /api/time-rules/{id}` 可部分修改 `kind`、`title`、`recurrence`、`weekday`、`date`、`start_time`、`end_time`、`active`。后端先将 PATCH 字段与数据库现值合并，再对**最终完整规则**重新执行全部校验；非法组合返回 `422` 且不写入。资源不存在返回 `404`。停用使用 `PATCH active=false`，没有 DELETE。

## Phase 5：Candidate

生成候选的请求：

```json
{"week_start": "2026-10-05", "task_ids": [1, 2, 3]}
```

`POST /api/plans/candidates` 接收上述请求。`week_start` 必须是周一；`task_ids` 至少一个、不重复、每项为正整数，拒绝 bool / 字符串 ID 和额外字段。用户提交本次需安排的完整任务 ID 列表；加入突发任务时包括原选中任务与新任务。后端读取任务和 TimeRule，不接受前端指定 `source_revision` 或宣称计划合法。

所有请求 ID 必须存在且 status=todo；不存在返回 422 `TASK_NOT_FOUND`，done / cancelled 返回 422 `TASK_NOT_TODO`，detail 中列出相关 task_ids。Schema 输入错误同样为 422，使用 FastAPI 标准字段错误列表。课程重叠等 Scheduler 原始输入错误为 422，detail 含原 `SchedulingInputError.code`（例如 `INVALID_TIME_RULES`）和 message。

全部排入并通过独立 Validator 时，HTTP `200`，响应包含 `status: "feasible"`、完整 `candidate`（下文的 Plan 响应结构）以及空的 `unscheduled_tasks`。保存时记录全局当前 source_revision 和同周正式计划 ID（based_on_plan_id，无则 null），不 bump revision，也不修改任何正式计划。

未能完整安排时，HTTP `409`，例如：

```json
{
  "detail": {
    "code": "UNSCHEDULABLE",
    "message": "Could not generate a complete plan under the current scheduling heuristic.",
    "unscheduled_tasks": [
      {
        "task_id": 3,
        "reason_code": "NO_SLOT_FOUND",
        "message": "No continuous slot was found before the task deadline under the current MVP scheduling rules."
      }
    ]
  }
}
```

此响应不写 Plan / PlanItem、不 bump revision、不修改正式计划。它表示当前 heuristic 未生成完整计划，不声称数学上无解。若 Scheduler 声称 feasible 但独立 Validator 拒绝，返回 500，detail 含 `code: "GENERATED_SCHEDULE_INVALID"`、message 和 violations，同样不写候选。

## Phase 5：Plan 查询响应

`GET /api/plans/{id}` 返回 HTTP 200 和已保存 Plan，缺失为 404 `PLAN_NOT_FOUND`。可以读取 candidate、confirmed、superseded；stale candidate 仍然保留并可查看。Plan 响应字段：

| 字段 | 类型与含义 |
|---|---|
| id | 整数 ID |
| week_start | ISO date，周一 |
| status | candidate / confirmed / superseded |
| based_on_plan_id | 生成时同周 confirmed 的 ID，或 null |
| source_revision | 生成时的全局 planning revision，Confirm 不改此字段 |
| task_ids | 用户明确选择的 ID 列表，保留请求顺序 |
| created_at | aware UTC timestamp |
| confirmed_at | 首次确认的 aware UTC timestamp；候选为 null，superseded 保留历史值 |
| items | 按 start_at ASC、kind ASC、id ASC 排序的快照列表 |

每个 item 含 `id`、`plan_id`、`kind`（task/course）、`task_id`、`time_rule_id`、`title_snapshot`、`start_at`、`end_at`。task item 仅 task_id 非空，course item 仅 time_rule_id 非空。title_snapshot 与时间区间来自生成时的持久化数据，后续 Task / TimeRule 修改不会覆盖它们。active course 区间复用 Phase 4 `expand_time_rules`；protected 和 inactive course 不成为 item。

`GET /api/plans/confirmed?week_start=YYYY-MM-DD` 要求 Monday，非 Monday 为 422 `INVALID_WEEK`，无法解析或缺少参数为 FastAPI 标准 422。仅返回该周 status=confirmed 的 Plan；没有正式计划返回 404 `PLAN_NOT_FOUND`，不会选择 candidate、superseded 或最新记录。此查询的成功响应直接为上述 Plan，不包含 Candidate envelope。

## Phase 5：Confirm

`POST /api/plans/{id}/confirm` 无需请求体，只使用路径 ID。后端在一个 SQLite 写事务中读取 singleton 和已保存候选，然后按顺序检查：

| 条件 | HTTP / detail.code |
|---|---|
| Plan 不存在 | 404 / PLAN_NOT_FOUND |
| status 不是 candidate，包括重复 Confirm | 409 / PLAN_NOT_CANDIDATE |
| source_revision 与当前 revision 不相等 | 409 / STALE_CANDIDATE |

stale 响应示例：

```json
{
  "detail": {
    "code": "STALE_CANDIDATE",
    "message": "The candidate plan was generated from an older planning state. Generate a new candidate before confirming."
  }
}
```

检查通过后，同周旧 confirmed 变为 superseded，候选变为 confirmed，写入 confirmed_at，revision +1，最终一次 commit；任一步失败全部 rollback。成功为 HTTP 200，直接返回 Plan 响应。其他周正式计划不变。partial unique index 保护同周最多一个 confirmed；其他旧 revision 候选保持 candidate，但后续 Confirm 会返回 STALE_CANDIDATE。

Confirm 不重新排程或再运行 Validator，使用生成时已独立校验的持久化快照和 revision 检查。拒绝时不修改任何 Plan 或 revision，也不自动生成新候选。

## Phase 5：revision 与事务

单用户全局 `PlanningState(id=1, revision=0)` 在启动时自动初始化。创建 Task / TimeRule、每个成功 PATCH（含空 PATCH 或无实际变化）和成功 Confirm 各 bump 一次，均与业务 mutation 同事务。GET、Candidate generation、输入拒绝、排程/校验失败和被拒绝的 Confirm 均不 bump。

Task / TimeRule / Candidate / Confirm 写请求在读取之前使用 `BEGIN IMMEDIATE`，使 Candidate 输入与 revision 一致，并串行执行 stale 检查与正式计划替换。Candidate 计算期间其他写入会等待，这是当前 SQLite MVP 的取舍。GET 不写数据。

Phase 5 按最新审核要求将早期设计中的 HTTP 200 unschedulable 更新为 HTTP 409，并明确重复 Confirm 返回 409，不再静默成功。其他 CRUD 契约不变。timestamp 使用带偏移的 ISO 8601（输出 UTC）；week_start / TimeRule.date 为 date，TimeRule 钟面时间仍为无 offset 的上海本地 time。

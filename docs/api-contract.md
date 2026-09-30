# Student Growth Assistant API 契约（Phase 0 冻结版）

统一使用 `/api` 前缀。下表是冻结的核心 API；**当前已实现 Phase 1 和 Phase 2 的前七个接口**，计划接口留待 Phase 5。

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

不提供硬删除接口。`POST /api/plans/check` 和 `POST /api/constraints/parse` 不属于核心接口，可在 Phase 7 视需要增加。

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

## 后续阶段的固定契约

生成候选的请求：

```json
{"week_start": "2026-10-05", "task_ids": [1, 2, 3]}
```

`week_start` 是周一。前端提交本次需安排的完整任务 ID 列表；加入突发任务时包括原选中任务与新任务。后端读取任务和 TimeRule，不接受前端指定 `source_revision` 或宣称计划合法。

全部排入并通过 Validator 时，HTTP `200`，响应包含 `status: "feasible"`、完整 `candidate`（含 `id`、`status`、`week_start`、`source_revision`、`task_ids`、全部任务和课程 `items`）以及空的 `unscheduled_tasks`。

未能完整安排时，HTTP `200`，例如：

```json
{
  "status": "unschedulable",
  "candidate": null,
  "unscheduled_tasks": [
    {
      "task_id": 3,
      "reason_code": "NO_SLOT_FOUND",
      "message": "按当前排程顺序，未找到截止时间前的连续可用时段"
    }
  ],
  "message": "Under the current MVP scheduling rules, a complete schedule could not be generated."
}
```

此响应不保存可确认候选，也不修改正式计划。它表示当前确定性规则未生成完整计划，不声称数学上无解。

Confirm 只接收计划 ID；后端读取已保存的候选，检查状态、`source_revision` 与当前 revision 一致，再运行 Validator，最后在一个事务中替换该周正式计划。同一当前正式计划的重复 Confirm 不产生重复数据。

通用状态：创建 Task/TimeRule 用 `201`；查询、修改和排程结果用 `200`；资源不存在用 `404`；旧候选或状态冲突用 `409`；字段或约束错误用 `422`。所有 API 日期时间使用带偏移的 ISO 8601 格式。

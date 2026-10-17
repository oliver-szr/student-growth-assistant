# Student Growth Assistant API Contract

统一使用 `/api` 前缀。当前工作台使用两周 Assistant 流程；下表中的 `/api/plans` 是保留的单周兼容接口。二者均不能未经用户确认修改正式日程。时间语义为北京时间，任务时长和安排起点采用 **5 分钟网格**，API 时间戳输出为 UTC。

阶段 0 保留请求和成功响应结构，强化当前时间、锁定、历史及确认时校验。新增拒绝语义见下文，不新增业务接口或数据库字段。

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
| POST | `/api/constraints/parse` | 7A | 只读自然语言 TimeRule proposal |
| POST | `/api/plans/{candidate_id}/explanation` | 7B | 只读 deterministic diff 与可选 AI explanation |

不提供硬删除接口。当前没有 `POST /api/plans/check` 或 `/api/constraints/apply`。

阶段 2 继续无硬删除 API（DELETE 返回405）；不能用取消父容器来静默取消子任务。

`datetime-local` 视为固定上海时间：例如 `2026-10-05T22:00` 发送为 `2026-10-05T22:00:00+08:00`；收到 `2026-10-05T14:00:00Z` 时仍显示 `22:00`。规则从 `weekly` 切到 `once` 时明确发送 `weekday: null`，反向切换时明确发送 `date: null`。

## 当前规划工作台与旧接口

前端请求统一经 `frontend/src/api.js`。现行三页为规划、复盘和我的档案；旧 WeeklyPlan 页面已移除，保留单周接口及 wrapper 供兼容使用。日期计算、网格与禁止过去时间均由后端负责，前端不能自行声明候选合法。

| 方法与路径 | 当前行为 |
|---|---|
| `POST /api/assistant/sessions` | 创建本周规划会话 |
| `POST /api/assistant/sessions/{id}/messages` | 接收结构化手动动作，或解析自然语言；只生成草案 |
| `POST /api/assistant/sessions/{id}/runs` | 后台 AI 运行；通过 `/runs/{id}` 查询，可取消或重试 |
| `GET /api/assistant/sessions/{id}` | 读取正式安排、任务和最新候选 |
| `POST /api/assistant/proposals/{id}/preview` | 编辑草案或选择现有候选，不写正式任务与日程 |
| `POST /api/assistant/proposals/{id}/confirm` | 复验后原子保存任务及两周日程 |
| `POST /api/assistant/proposals/{id}/discard` | 放弃草案 |

Assistant 覆盖本周剩余时间及下周；默认连续，用户明确允许后才有限分段，均衡、习惯、稳定策略仍独立评分。确认时检查会话周、最新候选、全局版本、当前时间、完整剩余时长、DDL、网格、课程、保护时间和锁定。保留历史必须完整对应正式计划快照，不能引用未采用的候选来授权历史写入；重复声明已锁定也不能移动原时段。拒绝使用既有 `409 STALE_CANDIDATE` 等错误语义；重复确认已采用的 Assistant 方案幂等返回，不重复写入或增加版本。

无 AI Key 时，手动结构化动作和程序排程仍可使用；AI 解析、推荐和解释不得绕过程序校验。两条确认路径均不根据日程结束或计时结束自动完成任务。

`ApiError` 保留 HTTP status、detail.code 和原 detail。404 PLAN_NOT_FOUND 在 Confirmed 查询时显示正常空状态；409 STALE_CANDIDATE 保留 outdated 预览、禁用 Confirm；409 PLAN_NOT_CANDIDATE 展示后端 message、禁用 Confirm；409 UNSCHEDULABLE 展示 task_id、可映射标题和 message/reason_code。其他 422/500、网络错误和 timeout 使用共用可读错误处理，不自动重排或确认。

## 局部重规划扩展（开发阶段 1）

不新增路由。旧请求字段与 `changes`、`items`、候选比较结构继续保留；老客户端不传新字段仍可生成草案，新生成的草案默认使用局部范围。

| 请求字段 | 含义与默认值 |
|---|---|
| messages 的 `replan: boolean = false` | 为 true 时允许无 actions 的手动程序重规划，跳过 AI 解析；按任务重规划可传已有 update 动作且 fields 为 `{}` |
| preview 的 `expand_scope: boolean = false` | 只能单独用于最新、同版本、需要扩大范围的局部失败候选；显式扩大后创建新候选，仍不写正式计划 |

这两个字段只属于 HTTP 请求，不属于 AI 的 ParsedCommand。扩大范围不能与任务编辑、策略选择、偏好修改等混用；非法扩大请求返回 `422 INVALID_SCOPE_EXPANSION`，资料、快照、范围记录或授权失效返回既有 `409 STALE_CANDIDATE`。候选仍须通过 confirm，失败不推进正式版本。带 client_message_id 的扩大请求可按现有消息语义幂等重试。

```json
{"client_message_id":"local-1","text":"局部重规划","replan":true}
```

```json
{"client_message_id":"expand-1","expand_scope":true}
```

新增响应字段：

- `replanning`：`mode` 为 local/expanded，含 affected_refs、preserved_refs、protected_refs、formal_snapshot_signature、expansion_from、requires_expansion。扩大授权仅在同版本有效草案链中继承；正式采用、放弃或版本变化后失效。
- `change_groups`：preserved/moved/added/pending/removed 数组及 counts（前四组按 task ref 去重）；各任务携带完整 before_segments、after_segments 与程序 reasons。缺少剩余工作证据时 remaining_minutes 为 null，不把原预计时长冒充剩余量。此类任务集中显示为 pending，历史仍完整保留。
- `formal_plan_needs_review`：原正式片段不满足新增规则、DDL 或工作要求，或尚需核对剩余工作；为 true 时提醒旧计划需要重新核对，不代表已更新正式计划。
- `selected_metrics` 和 candidate_options 的 metrics 增加 moved_task_count、moved_segment_count、total_shift_minutes、overlap_minutes、overlap_ratio。位移按各任务排序后的旧/新片段配对计算，未配对片段由片段数体现；重叠比仅针对原/新都有安排的任务，无比较基线时为 null。这些观测值不改变策略评分。
- 每个 candidate_option 同步提供 change_groups，切换候选时明细与选中指标一起变化。

diagnostics 保留 code/message 并按事实附加 ref/task_id、constraint、original_interval(s)、conflict_interval、time_rule_id、blocking_ref、options。真实 TimeRule 引用标记 `rule_source=time_rule`；本轮临时约束或保留片段占用标记 in_memory_constraint，使用 constraint 引用，不冒充数据库规则 ID。options 仅为建议，不能直接修改 DDL、时长或时间规则。

主要原因代码为 TIME_RULE_CONFLICT、DEADLINE_VIOLATION、LOCKED_SEGMENT、CURRENT_TIME_ADVANCED、WORK_REQUIREMENTS_CHANGED、NEW_TASK、TASK_UPDATED、EXPLICIT_REPLAN、SCOPE_EXPANDED、LOCAL_SCOPE_LIMIT，并保留引擎 NO_PLAN_FOUND/SEARCH_LIMIT。缺少剩余证据和窗口外任务的 pending reasons 使用 REMAINING_WORK_REQUIRED/OUTSIDE_PLANNING_WINDOW。范围和搜索失败均不能表述为数学上无解。

没有新增数据库结构，历史无范围字段的候选继续走阶段 0 校验；新候选若范围字段损坏、丢失或与已有消息标记不一致则拒绝。备份恢复仍使所有待确认候选失效。

## Phase 1：健康检查

`GET /api/health` 无请求体、无认证。成功返回 HTTP `200`：

```json
{"status": "ok"}
```

FastAPI 提供 `/docs` Swagger UI 和 `/openapi.json`。它们是开发文档入口，不是业务 API。

## Phase 2：Task

`POST /api/tasks` 接收 `title`、可空 `description`、`duration_minutes`、带时区偏移的 ISO 8601 `deadline`，以及可选 `priority`（`low/normal/high`，默认 `normal`）。`title` 去除首尾空格后必须非空；时长必须大于零且是 5 的倍数。创建时不接受 `status`、ID 或时间戳。成功返回 `201` 和完整 Task；`status` 默认为 `todo`。

完整 Task 响应字段为 `id`、`title`、`description`、`duration_minutes`、`deadline`、`priority`、`status`（`todo/done/cancelled`）、`created_at`、`updated_at`。例如输入 `2026-10-05T22:00:00+08:00`，读回的 API deadline 为 `2026-10-05T14:00:00Z`。SQLite 保存不含偏移的 UTC 钟面值；SQLAlchemy ORM 读回为带 UTC 时区的 `datetime`。创建与修改都拒绝无时区的 deadline。

`GET /api/tasks` 按 ID 升序返回列表，可选 `status=todo|done|cancelled`。`PATCH /api/tasks/{id}` 可部分修改 `title`、`description`、`duration_minutes`、`deadline`、`priority`、`status`；未提供字段保持原值，明确传入 `description: null` 可清空备注。更新会刷新 `updated_at`。资源不存在返回 `404`；非法字段或取值返回 `422`。取消使用 `PATCH status=cancelled`，没有 DELETE。

### 阶段 2 Task 扩展

旧字段保留。POST/PATCH 新增可选 `parent_task_id`（正整数或null）、`task_kind`（executable/container）和 `sort_order`（非负整数）；未提供时仍为普通可执行任务。PATCH parent_task_id=null 可解除关联。父任务必须为顶层容器，最多20个子任务；子 DDL 不得晚于父 DDL，收紧父 DDL 也要检查已有子任务。父容器保持 todo，完成/取消需分别处理子任务。已有计划引用、反馈、计时或锁定时拒绝类型转换，返回409 TASK_HAS_EXECUTION_FACTS。

GET tasks/dashboard 附加同名层级字段；父任务还提供 `progress`，含 total_children、completed_children、cancelled_children、partial_children、scheduled_children、executed_children、total_estimate_minutes、remaining_minutes、actual_minutes。GET /tasks 的 status 筛选不改变父任务的完整汇总；普通任务的 progress 为 null。POST/PATCH 的即时响应可不含汇总（null），随后读取列表。

父容器在反馈、计时和两条日程入口返回422 CONTAINER_NOT_EXECUTABLE。Assistant 任务库只含可执行任务；父子不会重复排程。没有强制依赖，sort_order 仅为建议顺序。创建子任务时复制父 TaskGrowthContext 的目标/分类；拆解确认将所选目标同时写入父子上下文，之后不自动同步目标修改。

### 任务拆解草案 API

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/tasks/breakdown-drafts` | AI 或手动生成草案，201；只写既有草案/消息表 |
| GET | `/api/tasks/breakdown-drafts` | 列出待处理 ready/stale 草案，供刷新恢复 |
| GET | `/api/tasks/breakdown-drafts/{id}` | 读取指定草案，含确认结果 |
| PATCH | `/api/tasks/breakdown-drafts/{id}` | `{version, content}` 全量替换草案内容，编辑版本加1 |
| POST | `/api/tasks/breakdown-drafts/{id}/confirm` | `{version}` 重新校验并原子创建父子任务 |
| POST | `/api/tasks/breakdown-drafts/{id}/discard` | `{version}` 取消草案，不创建任务 |

生成请求：

```json
{"client_request_id":"unique-client-id","source":"ai","text":"拆解软件工程课程项目","title":"Software Engineering Project","deadline":"2026-10-25T20:00:00+08:00","expected_duration_minutes":780,"goal_id":null}
```

source=manual 不调用 Provider，初始 children=[]；确认前须至少1项。text/title 非空，日期带时区且晚于当前时间，预期分钟为5到10080的5分钟整数倍。原始 input 保留用于总量比较。相同请求ID/输入返回原草案；输入不一致409 IDEMPOTENCY_CONFLICT。

content 为 `{parent:{title,description,deadline},children:[{title,description,duration_minutes,deadline,sort_order}]}`。children 最多20项，确认/AI输出至少1项；标题非空且≤200字，描述≤4000字，时长为5到10080的5分钟整数倍，顺序0到19且不重复，子DDL在未来并不晚于父DDL。AI不能变更输入父DDL；用户可显式编辑父DDL。编辑期间允许空children以便删除/重建。

响应包含 id、status、source、source_revision、version、input、content、total_minutes、difference_minutes、created_task_ids、tasks。状态为 ready/applied/discarded/stale。原始预期不会被建议总量覆盖；确认后 created_task_ids 为父ID与按建议顺序创建的子ID。

编辑和确认检查全局资料版本与草案编辑版本，分别409 STALE_DRAFT/DRAFT_VERSION_CONFLICT；状态不允许409 DRAFT_NOT_READY，缺失404 DRAFT_NOT_FOUND，空或损坏内容422 INVALID_BREAKDOWN，过期日期422 BREAKDOWN_DEADLINE_INVALID。日期过期的草案读取时显示 stale。AI缺失配置503 AI_NOT_CONFIGURED，Provider失败503 AI_UNAVAILABLE，结构或日期不合法502 AI_RESPONSE_INVALID，均不创建正式任务。

确认以 SQLite BEGIN IMMEDIATE 串行化，整树、目标上下文、applied 状态和全局版本一次提交；已applied再次confirm返回相同ID，不再推进版本。创建不改日历，现有候选因版本变化失效，后续须单独生成/采用。恢复备份也使待确认草案过期。旧 profile/review 草案入口拒绝 task_breakdown，不能绕过编辑版本检查。

## Phase 2：TimeRule

`POST /api/time-rules` 接收 `kind`（`course/protected`）、`title`、`recurrence`（`weekly/once`）、`weekday`、`date`、`start_time`、`end_time`、可选 `active`（默认 `true`），成功返回 `201` 和完整 TimeRule。响应还包括 `id`、`created_at`、`updated_at`。

`weekly` 必须有 1–7 的 `weekday`，且 `date` 为空；`once` 必须有 `date`，且 `weekday` 为空。课程和保护时间均可按周重复或指定日期。`title` 去空格后非空；`start_time < end_time`，不支持跨午夜。时间字段是上海本地钟面时间，不附带时区偏移。

`GET /api/time-rules` 按 ID 升序返回全部规则。`PATCH /api/time-rules/{id}` 可部分修改 `kind`、`title`、`recurrence`、`weekday`、`date`、`start_time`、`end_time`、`active`。后端先将 PATCH 字段与数据库现值合并，再对**最终完整规则**重新执行全部校验；非法组合返回 `422` 且不写入。资源不存在返回 `404`。停用使用 `PATCH active=false`，没有 DELETE。

## Phase 5：Candidate

本节描述旧单周 `/api/plans`，使用原有连续任务算法，不提供两周分段或复杂时间资料的兼容实现。示例使用固定日期说明结构；实际请求必须选择仍有未来时间的周。

生成时用临时保护区间屏蔽已过去的工作时间；当前时刻不在网格上时，选择之后的合法 5 分钟起点。这些临时区间不写入用户的 TimeRule，不修改任务 DDL。

| 情况 | HTTP / detail.code |
|---|---|
| 所选周已结束 | `422 PAST_PLANNING_WINDOW` |
| 选中任务或现有正式任务包含锁定、允许分段、固定开始、限定时段 | `422 PLAN_REQUIRES_ASSISTANT` |
| 同周正式计划含已开始、已结束或多片段任务，旧算法无法保证保留 | `422 PLAN_REQUIRES_ASSISTANT` |

上述拒绝不删除历史、不修改正式计划、不推进版本。用户可使用现有规划工作台处理这些场景；软偏好不会被当成解除硬约束的许可。

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
| 时间推进使新安排进入过去，或当前约束复验失败 | 409 / STALE_CANDIDATE，附 `reason_code` |

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

Confirm 不重新排程；它重新读取任务、硬时间资料、同周正式记录和课程规则，对持久化任务片段再次运行独立 Validator，检查完整性、唯一性、时长、网格、DDL、课程、保护时间及当前时间；另核对保存的课程片段与实际课程一致。无法安全兼容的历史或锁定场景也拒绝。约束失败仍用 `409 STALE_CANDIDATE`，可附 `reason_code`（如 `TASK_PROTECTED_OVERLAP`、`COURSE_SNAPSHOT_CHANGED` 等）说明具体原因。即使 revision 相等也必须通过本次检查。

所有检查先于正式计划替换和版本递增。拒绝时保留原正式计划、候选快照及 revision，不自动重排。异常由 `planning_transaction` 回滚，仍保留同周唯一正式计划约束。旧接口重复确认返回 `PLAN_NOT_CANDIDATE`，与 Assistant 的幂等确认语义不同。

## Phase 5：revision 与事务

单用户全局 `PlanningState(id=1, revision=0)` 在启动时自动初始化。创建 Task / TimeRule、每个成功 PATCH（含空 PATCH 或无实际变化）和成功 Confirm 各 bump 一次，均与业务 mutation 同事务。GET、Candidate generation、输入拒绝、排程/校验失败和被拒绝的 Confirm 均不 bump。

Task / TimeRule / Candidate / Confirm 写请求在读取之前使用 `BEGIN IMMEDIATE`，使 Candidate 输入与 revision 一致，并串行执行 stale 检查与正式计划替换。Candidate 计算期间其他写入会等待，这是当前 SQLite MVP 的取舍。GET 不写数据。

Phase 5 按最新审核要求将早期设计中的 HTTP 200 unschedulable 更新为 HTTP 409，并明确重复 Confirm 返回 409，不再静默成功。其他 CRUD 契约不变。timestamp 使用带偏移的 ISO 8601（输出 UTC）；week_start / TimeRule.date 为 date，TimeRule 钟面时间仍为无 offset 的上海本地 time。

## Phase 7A：Natural Language → TimeRule proposal

`POST /api/constraints/parse` 接收一个非空、非纯空白、最多 4000 字符的 text，拒绝额外字段：

```json
{"text":"Every Wednesday from 10:00 to 12:00 I have Machine Learning class."}
```

HTTP 200 结果严格为以下三种之一，没有额外字段：

```json
{
  "status": "parsed",
  "proposal": {
    "kind": "course",
    "title": "Machine Learning",
    "recurrence": "weekly",
    "weekday": 3,
    "date": null,
    "start_time": "10:00",
    "end_time": "12:00"
  }
}
```

```json
{"status":"needs_clarification","message":"A specific start and end time are required."}
```

```json
{"status":"unsupported","message":"This request is outside TimeRule parsing scope."}
```

clarification/unsupported 是正常 classification，不是服务故障。proposal 八字段必须齐全，nullable 字段必须显式为 null；拒绝 ID、active、时间戳等额外字段。kind 仅 course/protected，recurrence 仅 weekly/once，weekday 严格 integer 1–7，拒绝 bool/string；date 为 YYYY-MM-DD，time 为 HH:MM。之后完整复用既有 TimeRuleCreate 校验，不复制业务规则。字符串 title 去除首尾空格，必须非空。

支持按周或指定日期的课程与保护时间。weekly 的 date=null，once 的 weekday=null；开始必须早于结束，真实日期与时钟有效。日期/时间使用上海语义，backend 明确给 provider 当前上海日期。不允许猜缺失时间或把 Task/Plan 命令转换为保护时间。

| HTTP | detail.code | 安全的 detail.message |
|---|---|---|
| 503 | AI_NOT_CONFIGURED | AI parsing is not configured. |
| 503 | AI_UNAVAILABLE | The AI parsing service is temporarily unavailable. |
| 502 | AI_RESPONSE_INVALID | The AI parsing service returned an invalid response. |
| 422 | FastAPI 标准字段错误列表 | 非法 request text/schema |

例如 provider 故障：

```json
{"detail":{"code":"AI_UNAVAILABLE","message":"The AI parsing service is temporarily unavailable."}}
```

401/403/429/5xx、HTTP/network failure 和 timeout 统一 AI_UNAVAILABLE；无 text block、空 content、异常 response、非法 JSON/schema/TimeRule 为 AI_RESPONSE_INVALID。客户端不会暴露 provider token、headers、raw body 或 traceback。现有 Provider 根据 `AI_API_FORMAT` 分别使用 Anthropic Messages 或 OpenAI Chat Completions 兼容协议及其对应配置。

Parse 不创建/更新任何数据库对象，不访问 Session、不调 Scheduler、不 bump revision。用户编辑并点击 Apply 后，frontend 只向现有 `POST /api/time-rules` 发送 proposal 字段；正常的创建默认 active=true，revision 同事务 +1，旧 Candidate 使用原有 STALE_CANDIDATE 检查。Discard 不发送写请求。不存在 AI 专属 Apply endpoint。

## Phase 7B：只读 Candidate explanation

`POST /api/plans/{candidate_id}/explanation`。可省略 body；默认 `{"language":"en"}`，也支持 `{"language":"zh-CN"}`。strict/extra-forbid；其他语言或额外字段返回标准 422。读取 Plan 的 GET 不自动调用 provider。

成功响应结构：

```json
{
  "diff": {
    "confirmed_plan_id": 1,
    "candidate_plan_id": 2,
    "week_start": "2026-10-05",
    "summary": {"added_count": 0, "removed_count": 0, "moved_count": 1, "unchanged_count": 0},
    "added": [],
    "removed": [],
    "moved": [{"task_id": 7, "title": "Read Paper", "from_start": "2026-10-05T00:00:00Z", "from_end": "2026-10-05T01:00:00Z", "to_start": "2026-10-05T02:00:00Z", "to_end": "2026-10-05T03:00:00Z"}],
    "unchanged": []
  },
  "explanation": "Read Paper moved from 00:00–01:00 UTC to 02:00–03:00 UTC. The candidate is not official until you confirm it.",
  "explanation_status": "available"
}
```

added/removed/unchanged 条目均为 `{task_id,title,start_at,end_at}`；moved 为 `{task_id,title,from_start,from_end,to_start,to_end}`。title 使用保存的 title_snapshot，不 join 当前 Task 标题；title 改名本身不算移动。仅比较任务，Course 忽略。所有时间规范为 UTC，按相关 start 再 task_id 排序；moved 用 to_start。Removed 只表示旧 snapshot 中存在、新 Candidate 中未包含，不删除 Task。

baseline 始终读取 candidate.based_on_plan_id，即使它后来 superseded；diff.confirmed_plan_id 命名表示生成候选时的正式计划基线，不保证它现在仍 confirmed。没有 baseline 时为 null，所有任务 added；HTTP 200、explanation_status=deterministic、双语首次计划文案，不调用 provider。

| 条件 | HTTP / 结果 |
|---|---|
| candidate 不存在 | 404 PLAN_NOT_FOUND |
| status 是 confirmed/superseded | 409 PLAN_NOT_CANDIDATE |
| baseline 不是 confirmed/superseded | 409 PLAN_BASELINE_INVALID |
| stale candidate | 200，仍按保存的历史 snapshot 比较；不授权 Confirm |
| 缺配置、timeout、HTTP/network failure、非法 provider/text response | 200，完整 diff + explanation=null + explanation_status=unavailable |

explanation 是 1–3000 字符的纯文本，独立于确定性事实。模型仅消费 structured diff；不返回 raw response/usage/headers/model metadata。明确的最优性/因果措辞被保守拒绝，但不能把该检查理解为语义真实性证明。输出不保存数据库，Task、TimeRule、Plan、PlanItem、PlanningState 和 revision 全部不变。没有 Scheduler/Confirm/tool/SQL-from-AI 调用，读事务在等待 provider 前释放。请求仅在用户主动点击 Explain 时发出；Provider 超时上限 120 秒，前端请求期限 125 秒，无自动重试。

## 已知边界

旧入口继续使用单周连续任务启发式；Assistant 在原有界两周搜索外增加局部范围约束，均不保证全局最优，未找到方案不等于数学上无解。本阶段未新增任务层级、统计图表或数据库迁移。版本检查为单用户全局版本；无关资料变更仍可能令旧候选失效。可重复测试和 Conda 开发命令见 README。

独立审核补充：provider BASE_URL 支持 gateway origin 或 `/v1` base（去尾斜杠后规范化），不会重复拼接版本；不传完整 `/messages` endpoint。解释 prompt 要求引用的钟点保持 UTC；AI Explanation 区显式标注 UTC，deterministic Changes 使用上海 UTC+08。明确确认压力及肯定式删除断言也会安全降级，但词法检查不是完整语义验证。

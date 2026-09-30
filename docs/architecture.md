# Student Growth Assistant 架构（Phase 0 冻结版）

本文依据已审核的 Phase 0 降复杂度修订。文件按阶段逐步创建；当前已完成 Phase 2 的 Task 与 TimeRule 后端 CRUD，计划、排程、AI 和前端仍是后续设计。

## 技术与边界

- 前端：React、Vite、JavaScript、原生 CSS、`fetch`。Phase 3 才创建前端。
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
| PlanningState | 仅一行：`id = 1`，`revision` 为整数。成功修改 Task、TimeRule 或替换正式计划时递增；查询、生成候选和排程失败不递增。数据修改与递增在同一事务中。 |

同一周最多有一个 `confirmed` Plan，可有多个 `candidate`。Confirm 时旧正式计划变为 `superseded`，新计划确认且 revision 递增；三者在同一事务中完成，并由数据库唯一约束保护。

## 冻结的排程规则（Phase 4 实现）

- 时区固定为 `Asia/Shanghai`；用户指定从周一到下周一的完整周。Task deadline 的 API 输入必须带时区偏移，API 输出统一为 UTC。SQLite 以不含偏移的 UTC 钟面值保存日期时间；SQLAlchemy 读回时恢复为带 UTC 时区的 Python `datetime`，供后续代码安全比较。TimeRule 日期与钟面时间按上海本地时间理解。
- 用户明确选择本周的 `todo` 任务；不自动选择全部待办。
- 每天可用时间为 08:00–22:00，按 30 分钟网格尝试起点。任务必须连续完成，不拆分。
- 时间区间采用 `[start, end)`。课程与保护时间先占用时间；保护时间禁止安排灵活任务，但与课程重叠不代表课程取消。
- 任务按 deadline 升序、同 deadline 的 priority 从高到低、再按 task ID 升序排序。依次寻找截止时间前最早的连续合法时段；不回溯、不移动已排任务。
- 全部排入后由独立 Validator 检查任务恰好出现一次、时长、deadline、周范围、时间窗口、网格、相互冲突以及课程和保护时间。校验失败是实现错误，不能保存候选。
- 排不下时返回 `unschedulable` 和未安排任务；不保存可确认候选，不修改正式计划。界面使用原文：`Under the current MVP scheduling rules, a complete schedule could not be generated.`
- 不处理已开始/已结束任务块、实时执行状态或自动冻结历史；演示使用未来时间或完整指定周。

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

Phase 2 使用已有的 SQLAlchemy `Base`、engine、Session 和 `get_db`，启动时用 `Base.metadata.create_all` 创建缺失的 `tasks`、`time_rules` 表。课程 MVP 不使用 Alembic；`create_all` 不会迁移已存在的表结构。HTTP 输入输出由 Pydantic schema 处理，路由直接使用 Session；pytest 每例使用独立临时 SQLite 文件，不连接开发数据库。当前没有其他业务表或 React 文件。

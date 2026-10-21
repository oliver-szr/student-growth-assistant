# Student Growth Assistant V2：阶段 0 基线审计

审计日期：2026-10-21（Asia/Shanghai）。本轮仅做审计、设计、隔离验证及三份文档交付，**完成后停止，不开始阶段 1**。

## 1. 结论与证据边界

- 推荐开发基线：本地 `feat/planning-growth-upgrade` 的 **`5f953c91722408b484608e06c69280f9826e0080`**。它具有当前完整业务实现、测试、fixtures、CI，以及额外的拆解 Provider 传输/失败隔离测试。
- 初始工作区干净，当前已安全建立本地 `feat/v2-workspace-redesign`；本轮只新增本报告、[架构建议](v2-architecture-proposal.md)、[结构原型](v2-ui-wireframes.md)。未 push、merge、rebase 或创建远程 PR。
- 新建本地注释标签 `v1-v2-baseline-2026-10-21`，指向上述完整开发 SHA。既有 `v1` 指向旧 `acded0a`，未修改。标签只保护代码，不是数据库备份。
- 仓库内（含本地忽略目录，排除 Git/依赖目录）未找到《v2产品框架设计.md》。以本次粘贴的 V2 摘要为需求依据；**尚未完成完整产品文档逐条对照**。文中新增 API、模型、断点、组件名称均为建议，未当作已确认需求或已实现功能。
- 源码已证明主要业务可复用，但统一聊天、全年日期查询、用户确认后保存的复盘记录、通用长期记忆和多用户隔离存在实质缺口。阶段 1A 布局可准备开发；完整 V2 不具备直接一次性接入条件。

证据标记：**实现**=本次核对源码；**验证**=本次实际执行；**文档**=已有说明，不能代替验证；**建议**=后续设计，未实施。未读取个人数据库业务行或 `.env` 内容，未以真实 AI 请求验证模型效果。自动化通过不代表浏览器交互、真实并发、生产部署或模型质量已验收。

## 2. Git 基线与分支关系

### 2.1 本次只读检查与远程刷新

实际执行 `git status --short --branch`、`git status --porcelain=v1 --untracked-files=all`、`git remote -v`、`git branch -a -vv`、`git log --all --graph --oneline --decorate -35`、`git rev-parse`、`git tag -n`、`git ls-tree`、`git diff`、`git merge-base`，并安全执行 `git fetch origin`。首次 fetch 因沙箱不允许写 FETCH_HEAD 失败，获执行权限后重试成功；没有合并工作区。

origin（fetch/push）：`https://github.com/szt1107/student-growth-assistant.git`。

| 引用 | 完整 commit SHA | 核查结果 |
|---|---|---|
| 初始 HEAD / release/course-submission / origin/release/course-submission | `cf8853dd0e08b06405b7b980c96b4e15285b51d1` | 精简运行交付，删除正式测试/fixtures/CI |
| 本地 main | `acded0ae13b523ad16ca99b37cbd846e1081a0c2` | 跟踪 origin/main；fetch 后落后 13 个可达提交，未更新它 |
| fetch 后 origin/main | `16acda6dbde8f1a355139c0aade3a0d9d56f6428` | 合并 PR #1；其文件树与 release 完全相同 |
| feat/planning-growth-upgrade | `5f953c91722408b484608e06c69280f9826e0080` | 本地独有开发分支，没有同名远程跟踪引用 |
| release 与开发分支共同祖先 | `4d4a60b9a1ed102f043a6ff077c9cbaa84585023` | 完整业务集成后的共同版本 |
| 新 V2 分支起点 / 新 V1 回退标签解引用 | `5f953c91722408b484608e06c69280f9826e0080` | 保留完整开发资产；本轮提交为其文档后继 |

```text
acded0a  本地 main / 既有 v1
  └─ 5366e0f → 0ccc719 → 1a3d770 → e82e2b3 → 1c5b2cb
       → 54684a7 → 6995175 → e0ac6eb → 4de28b9 → a1a3e30 → 4d4a60b
                                                        ├─ 5f953c9 完整开发 → V2 文档
                                                        └─ cf8853d 精简交付
acded0a + cf8853d ──合并──> 16acda6 origin/main
```

### 2.2 为什么不从 main 或 release 开始

1. `git diff feat/planning-growth-upgrade release/course-submission -- backend/app frontend/src backend/alembic frontend/package-lock.json` **为空**。开发基线不是依据名称选取，而是实际业务、迁移与前端锁文件一致。
2. 精简分支相对开发分支有 83 个文件差异，合计 152 行新增、8804 行删除；主要是测试、fixtures、CI、开发脚本、验收文档及安装/测试入口的删除。`frontend/package.json` 删除 `test`，`backend/requirements.txt` 删除 pytest 声明。
3. `5f953c9` 比共同祖先多一项测试提交，在 `backend/tests/test_task_breakdown.py` 增加 88 行，覆盖传输与失败隔离；它没有改变业务实现。
4. 相对本地旧 main，开发基线还包含局部重规划、确认安全修复、任务层级、成长统计、性能优化、备份碰撞修复、CI、目标编辑修复等实际文件。不能把本地旧 main 当成当前 GitHub main。
5. `git log --all --oneline --not feat/planning-growth-upgrade` 只列精简提交和 PR 合并；`git diff origin/main release/course-submission` 为空。当前可达 refs 中没有发现遗漏的其他合并业务功能。此结论不覆盖不可见/已删除远程分支或他人未提交工作。

重要提交：`5366e0f` 确认约束、`0ccc719` 局部重规划、`e82e2b3` 任务拆解、`1c5b2cb` 统计、`54684a7` 性能、`6995175` 备份、`e0ac6eb` CI、`4de28b9` 目标编辑/集成、`5f953c9` 传输回归。旧历史中的两项团队合并提交也位于基线祖先链，原作者历史保留。

未来与 origin/main 集成时必须专门审查精简删除：从开发分支直接合并 main 可能再次删除测试资产。本阶段没有为消除分叉而自动合并或恢复远程文件。

### 2.3 已完成的本地保护动作

```powershell
git switch -c feat/v2-workspace-redesign feat/planning-growth-upgrade
git tag -a v1-v2-baseline-2026-10-21 5f953c91722408b484608e06c69280f9826e0080 -m 'Full V1 development baseline before V2 stage 0 documentation'
```

创建前分支/标签不存在，工作区没有已修改或未跟踪文件；切换由 Git 自身保护未跟踪内容，未发生覆盖。未改其他本地分支指针、提交历史和既有标签。回退操作应先保存届时工作，再从该标签建立独立检查分支；不要直接 reset 当前分支。数据库回退须另用匹配版本的备份，不能靠切换 Git 恢复数据。

## 3. 架构现状

前端 React 19 + Vite + JavaScript，`frontend/src/App.jsx` 条件挂载三页：`AssistantPage`（规划，内含 `TasksPage`）、`GoalsGrowthPage`（导出为 ReviewPage）、`MyProfilePage`。规划聊天与复盘/档案 `WorkspaceChat` 分别持有会话、运行和本地表单；`WorkbenchLayout` 是聊天/结果双列及窄屏切换，不是 V2 四区壳。切换顶层 tab 会卸载原页。

所有 HTTP 包装集中在 `frontend/src/api.js`；路由在 `backend/app/routers/`，业务在 `backend/app/services/`，持久模型在 `models.py`，Pydantic 契约在 `schemas.py`、`assistant_schemas.py`、`task_breakdown_schemas.py`、`analytics_schemas.py` 等。服务仍有路由内编排和模块间调用，并非所有业务已抽成独立 service；后续只在接入点逐步抽取，不能大规模搬动。

SQLite 正常默认 `backend/data/app.db`，`SGA_DATABASE_PATH` 可覆盖；`UTCDateTime` 保存 UTC，时间规则使用上海本地日期/钟面，任务起点/时长为 5 分钟网格。`planning_state.planning_transaction` 使用 `BEGIN IMMEDIATE` 与全局 singleton revision，保护正式写入和确认。Provider 等待释放事务；部分同步排程路径仍持有写事务。

`main.lifespan` 启动会备份、调用 `schema_migrations.upgrade_database`、初始化成长数据及把遗留 running 标成 interrupted，故本轮没有向默认个人库启动应用。Alembic head=`0002_task_hierarchy`，冻结基线保存在 `backend/alembic/baseline_models.py`；不是启动时随意重建表。

## 4. 功能与代码复用矩阵

下列 API 均为**当前已存在**；路径默认 `/api`。正式数据都存于上述 SQLite，表名为模型 `__tablename__`，不是浏览器本地存储。

| 模块 / 实现程度 | 前端入口与调用 | 后端关键实现 / API | 正式存储 | 直接复用 | V2 适配及兼容风险 |
|---|---|---|---|---|---|
| 任务创建/编辑/取消、两级父子：已实现；硬删除未实现 | `pages/TasksPage.jsx` 的 save/setStatus/convert；`TaskForm.jsx`、`TaskHierarchy.jsx`；getTasksDashboard/createTask/updateTask | `routers/tasks.py:list_tasks/create_task/update_task`；GET/POST `/tasks`、PATCH `/tasks/{id}`；`services/task_hierarchy.py:validate_task_change/serialize_tasks` | tasks、task_growth_contexts；Task 保留 ID 和状态 | CRUD、两级树、汇总、分类/目标关联 | UI 的“删除”不能映射成不存在的 DELETE；当前仅 cancelled。父容器不能直接执行/取消/排程；最多20子项，子DDL≤父DDL，转换类型有事实保护 |
| AI/手动拆解及审核：已实现 | `components/TaskBreakdown.jsx` generate/persist/adopt；`taskHierarchy.js`；api 的 create/edit/confirmTaskBreakdown | `routers/task_breakdown.py` `/tasks/breakdown-drafts` 创建/列表/详情/PATCH/confirm/discard；`services/task_breakdown.py:create_draft/edit_draft/confirm_draft` | growth_change_drafts(scope=task_breakdown) 的 payload/version/created_task_ids；assistant_sessions/messages；确认后 tasks/context | 强类型建议、1.2秒合法编辑自动保存、乐观版本、幂等整树创建 | 目前独立于规划聊天；未保存的无效编辑刷新会丢。不能把删除草案子项当删除正式任务；建议顺序不是依赖网络 |
| 两周智能排程、三策略、局部重规划：已实现 | `pages/AssistantPage.jsx` send/manualSubmit/act；`ScopedChanges.jsx`；sendAssistantMessage/replanAssistant/previewAssistant/confirmAssistant | `routers/assistant.py:proposal_payload/_create_run_proposal/preview/confirm`；`assistant_state.py:proposed_world/build_proposal`；`assistant_scheduler.py:arrange/validate_assistant`；`scoped_replanning.py:identify_scope/validate_scope` | assistant_proposals.payload/source_revision；plans、plan_items；task_scheduling_profiles.settings | 原引擎、权重、候选对比、独立复验、两周原子保存、历史/锁定保护 | 年视图不等于全年排程；不得从日历拖拽直接写正式 PlanItem。扩大范围需要显式授权；SEARCH_LIMIT 不等于无解 |
| 旧单周候选：兼容已实现，当前页面不主要使用 | api.js createCandidatePlan/getConfirmedPlan/getPlan/confirmPlan；旧页面逻辑仅留 tests/fixtures | `routers/plans.py:create_candidate/confirm_candidate`；`scheduler.py:schedule_week`、`validator.py`、`plan_safety.py:prepare_plan_rules/validate_saved_plan` | plans/plan_items；planning_state | 历史按周查询、旧客户端兼容、安全拒绝 | 重复 confirm 返回409 PLAN_NOT_CANDIDATE，与 Assistant 的幂等成功不同；不能统一包装后宣称所有确认均可重复成功 |
| 课程/保护时间/偏好/冲突：部分完整 | `pages/TimeRulesPage.jsx` save/deactivate/applyProposal；`TimeRuleForm`、`NaturalLanguageTimeRule`；`MyProfilePage` 规则编辑 | `routers/time_rules.py` GET/POST/PATCH `/time-rules`；`constraints.py` POST `/constraints/parse`；`taxonomy.py`；`course_import.py`；validator/assistant_scheduler | time_rules、course_imports、preference_rules、task_categories、assistant_preferences | 规则CRUD、停用、周期展开、偏好编译、独立排程冲突检查 | 保存时间规则不等于自动修复所有已有日程。自然语言旧 parser 只接受周期课程，结构化规则可支持单次课程；无学期起止/节假日例外字段，全年展开不能暗示真实全年课表 |
| 执行反馈/计时/状态：已实现 | `TasksPage` submitFeedback/timerAction/setStatus；api feedback、work-sessions 系列；复盘聊天可生成反馈草案 | `routers/execution.py:save_task_feedback/start_work_session/_change_session`；`growth_tracking.py:record_feedback/record_unknown_completion/retract_latest_completion` | task_feedback（含快照/撤回/更正链）、task_work_sessions、tasks/context | 幂等反馈、暂停继续、剩余时长、有效事实归集 | 计时结束仅帮助填写，不能自动完成。Task done 的直接编辑会生成耗时未知事实；计时不应与反馈耗时重复相加；父容器拒绝执行 |
| 统计、目标、周复盘：已实现部分 V2 能力 | `GoalsGrowthPage` refresh/generateReview/afterChatDraftConfirmed；`GrowthAnalytics.jsx`；getReviewContext/getGrowthStatistics/createGrowthReview/getGrowthReviews | `growth_statistics.py:get_statistics` → service同名；GET `/growth/statistics?weeks=4|8|12&end_week=周一`；`growth_reviews.py:_review_facts/create_growth_review` GET/POST `/growth/reviews`；goals.py | 统计只读无新表；growth_goals/revisions；growth_weekly_reviews(facts,narrative,version)；feedback/plan snapshots | 事实聚合、未知/零值区分、目标进展、旧周复盘快照 | 只有周复盘，4/8/12周趋势不等于日/月回顾；当前 POST 生成时直接持久保存，不具备用户编辑并确认结论的“复盘记录”。前端确认反馈后还会自动调用 createGrowthReview，应在新记录流程中明确拆开 |
| AI聊天、异步运行：部分实现 | `AssistantPage` 本周localStorage会话；`WorkspaceChat` openWorkspaceSession/poll/confirmDraft；`ChatMessages`、`SafeMessage` | `routers/assistant.py:create_session/open_workspace_session/create_run/get_run/retry_run/get_session/_process_run`；POST `/assistant/sessions/{id}/runs`，GET `/assistant/runs/{id}`，cancel/retry | assistant_sessions/messages/runs/proposals、growth_change_drafts | 消息持久化、幂等消息、阶段反馈、刷新恢复、取消重试、受控业务草案 | 尚无列表/搜索/置顶/归档/删除/分页 API，scope隔离，普通自由聊和跨工具路由缺失。进程内 asyncio worker 不等于持久队列；重启仅标 interrupted |
| 档案/目标/偏好/分类/课表：已实现；通用记忆未实现 | `MyProfilePage` refresh/saveGoal/saveRule/saveCategory/linkTask；内嵌 TimeRulesPage；档案聊天 | `/profile/context`、`/growth/profile`、`/goals`、`/task-categories`、`/assistant/preference-rules`；`growth_profile.py:record_profile_revision`、taxonomy 服务 | growth_user_profiles/revisions、growth_goals/revisions、preference_rules、task_categories、time_rules | 现有编辑器、来源标记、历史版本、明确确认的偏好 | ai_note 是给AI的偏好说明，不是带来源/失效/删除/检索的通用长期记忆。既有 profile/PlanningState/WorkspaceMetadata 都含单例设计 |
| JSON导出/恢复、备份、迁移：已实现 | `MyProfilePage` exportData/importDataFile；exportGrowthData/importGrowthData/getLocalBackups | `routers/data.py` GET `/data/export`、POST `/data/import`、GET `/data/backups`；`growth_data.py:build_snapshot/_prepare_snapshot/restore_snapshot/create_sqlite_backup`；schema_migrations.upgrade_database | JSON v2 的26业务表、SQLite副本；alembic_version 不导出 | 在线备份、严格v1→v2转换、整库事务恢复、恢复后候选失效 | 新表/新列会破坏当前严格表列集合；必须升级JSON格式/转换器和fixtures，不能只新增Alembic；回退旧代码不等于能读取新schema |
| Provider、超时、重试、确认：已实现部分 | api.js request默认15秒，AI显式125秒、导出恢复60秒；规划轮询700ms/270秒，WorkspaceChat轮询800ms且无总期限 | `claude_client.py:get_claude_config/request_claude` 支持 Anthropic Messages/OpenAI Chat Completions；`assistant_ai.py` JSON校验；assistant runs；各confirm事务 | run状态、草案版本、planning revision；密钥仅进程配置/.env，不入业务表 | Provider边界、错误脱敏、1–120秒总请求限制、用户显式重试和后端校验 | 不流式返回；没有通用自由聊协议。手动preview/replan默认15秒可能小于多策略搜索耗时；这是代码层风险，未证明实际发生超时故障 |

### 4.1 聊天能力的精确边界

- AssistantSession 有 week_start、scope、latest_proposal_id、created_at；没有标题、updated_at、归档、置顶或归属用户字段。AssistantMessage 有 text/content/proposal_id，没有独立 created_at 或结构化多业务引用表。
- 规划页 `localStorage` 键为 workspace_id+本周，刷新可恢复对应 ID；新周重新创建。`require_current` 阻止旧规划会话继续跑当前业务；GET 旧会话仍能读取消息。因此“持久化”不等于“支持独立长期聊天”。
- review 按指定周找最新会话，profile 使用 `1970-01-05` 哨兵周复用；拆解使用 task_breakdown 专用scope。不同工具尚不能自然共享同一会话，不能只把scope改为 unified 就宣称兼容。
- 复盘/档案上下文最多带最近8条消息、最近20条反馈；不是全历史记忆。规划解析输出动作/问题/偏好，空动作会落入 needs_input；复盘/档案允许空 operations 回复，但仍是业务限定提示词，不是统一自由聊天契约。
- `GET /assistant/runs/{id}` 会在revision变化时把run标失败并取消本进程任务；不能笼统声称所有 GET 都无写入。统计 GET 有专门只读事务保障。
- 规划proposal关联message是列级FK；growth draft ID放在消息JSON；无跨任务/复盘/档案的通用卡片关联、版本协议或跨会话事件广播。
- 规划页和 WorkspaceChat 的轮询分别实现，卸载/切会话时迟到响应及重复轮询需专门测试。旧 messages GET 一次取全量，长对话会放大数据库、网络和渲染成本。

## 5. V2 Gap Analysis

优先级：P0=接入安全前提，P1=核心体验，P2=后续完善。建议阶段名称统一为：1A布局，1B保留现有契约的功能接入，2A会话/工具/草案，2B日期/回顾，3记忆，4身份与部署。这里只划分工作，不授权开始。

| V2需求 | 状态 | 复杂度 / 优先级 | 建议阶段 | 依赖 | 主要风险 |
|---|---|---|---|---|---|
| 四区工作台 | 尚未实现 | 中/P1 | 1A | 壳与尺寸模型 | 嵌套旧双列会挤压日历 |
| 首页/日程/复盘/档案统一导航 | 部分实现 | 中/P1 | 1A→1B | App拆壳、页面适配器 | 原页卸载丢本地编辑 |
| 工作区收起/普通/展开及日期/编辑恢复 | 尚未实现 | 高/P0 | 1A→1B | UI状态与编辑缓存 | CSS隐藏不等于刷新持久化 |
| 会话列表、新建、搜索、置顶、归档、删除 | 尚未实现 | 高/P1 | 2A | 服务端会话元数据与分页/归属 | 历史消息、未确认草案的删除关系 |
| 统一AI主聊天/允许自由聊 | 部分实现 | 高/P1 | 2A | 意图路由、自由回复、上下文边界 | 空闲聊天被强制变成任务或记忆 |
| 业务卡片与工作区跳转 | 部分实现 | 中/P1 | 1B→2A | 类型化引用、导航命令 | 显示旧版本为可确认 |
| 天/周/月/年日历 | 部分实现 | 中/P1 | 1B周→2B其他 | CalendarAdapter、范围查询 | 年浏览误触扩大排程范围 |
| 日期范围查询 | 尚未实现 | 中/P0 | 2B | 有界正式计划查询 | 只查两周导致历史/年视图虚假空白 |
| 周期课程跨范围展示 | 部分实现 | 中/P1 | 2B | 既有规则展开、有界范围 | 无学期/假期语义；课程重复 |
| 聊天/工作区双向草案同步 | 部分实现 | 高/P0 | 1B局部→2A完整 | 同一draft资源、版本、失效通知 | 两组件编辑同一草案互相覆盖 |
| 版本校验和幂等确认 | 已有可复用 | 高/P0 | 1B复用→2A补齐 | 现有revision/事务/索引 | profile/review草案缺编辑version；旧plans确认非幂等 |
| 日/周/月回顾 | 部分实现 | 高/P1 | 2B | 范围统计、真实口径 | 4周不能冒充自然月；零/未知混淆 |
| 用户确认后保存的复盘记录 | 部分实现 | 高/P1 | 2B | 快照、草案/正式记录区分 | 现有周复盘生成即保存，不是确认结论 |
| 档案（目标/时间课程/偏好/类别/数据） | 已有可复用 | 中/P1 | 1B | 复用表单、单源读取 | 历史快照被当前资料覆盖 |
| 可管理长期记忆 | 尚未实现 | 高/P2 | 3 | 来源、确认、修改/删除与检索 | 把AI猜测当事实；与正式偏好重复 |
| 手机端切换与编辑保留 | 部分实现 | 中/P1 | 1A结构→1B验收 | 单视面导航/焦点恢复 | 旧CSS仅切聊天/结果，未覆盖四区 |
| 用户归属、权限隔离 | 尚未实现 | 高/P0(上线前) | 4，2A设计预留 | 身份上下文、单例拆分、全部查询审计 | 仅加user_id不能解决ID越权与共享revision |
| 组件在本机真实浏览器的交互/性能 | 有待验证 | 中/P1 | 1B前技术验证 | 候选精确版本、隔离页面 | peerDependencies不是渲染/拖拽/触摸验收 |

## 6. 本次环境和运行验证

### 6.1 保护措施

复用 `C:\Users\27064\anaconda3\envs\app_env\python.exe`，Python **3.11.16**；Node **v24.13.0**、npm **11.6.2**。CI声明Python3.11/Node22，因此本地通过不代表本次重跑了GitHub CI。未安装/升级依赖，未覆盖锁文件，未调用真实付费AI。

先读 `backend/tests/conftest.py`：每项API测试使用新UUID SQLite并覆写 get_db/app.state.db_engine；禁用 `.env` 加载、移除Provider key、使用MockTransport/模拟AI。迁移、备份、demo_init单测只操作它们新建的匿名数据库；本轮没有启动演示服务器、导入私人课表、重置演示数据或结束已有服务进程。

本轮设置 `SGA_DATABASE_PATH` 指向新目录中的 bootstrap.db，防止默认engine被意外使用；备份目录也独立指定。pytest basetemp指向本轮专属新路径，不使用已有pytest目录。测试产生的临时库/备份、构建dist均Git忽略，不作为交付文件提交。

正式 `backend/data/app.db` 本轮开始SHA256：`0DB97D1D9760B66C414F9E17C8C0369ECFC1D6DDDD0050972E18D68F3FC439CB`。结束时复核结果见下表；哈希核对不读取私人行，不代表已替用户备份数据库。

### 6.2 命令和结果

以下从仓库根目录运行，后端pytest在backend目录运行。`$py`仅为本报告命令简写：

```powershell
$py = 'C:\Users\27064\anaconda3\envs\app_env\python.exe'
& $py --version
& $py -m pip check
node --version
npm.cmd --version
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build

# 初次普通沙箱目录：scripts/.local/v2-stage0-1792551943727
# 隔离重试目录（以下命令已实际执行）：
$env:SGA_DATABASE_PATH='E:\homework\student-growth-assistant\scripts\.local\v2-stage0-1792551943727-retry\bootstrap.db'
$env:SGA_BACKUP_DIR='E:\homework\student-growth-assistant\scripts\.local\v2-stage0-1792551943727-retry\backups'
$env:SGA_AUTO_BACKUP='0'
$env:SGA_SKIP_IMPORT_BACKUP='1'
$env:PYTHONUTF8='1'
# working-directory = E:\homework\student-growth-assistant\backend
& $py -u -m pytest -q -p no:cacheprovider --basetemp='E:\homework\student-growth-assistant\scripts\.local\v2-stage0-1792551943727-retry\pytest'
```

| 验证组 | 本次结果 / 数量 | 问题性质 / 是否阻碍V2 |
|---|---|---|
| pip check | 通过；No broken requirements found | 检查环境兼容，不是依赖逐项与constraints一致性证明 |
| 前端测试 | **89通过、0失败、0跳过** | 原有SVG title复合children触发React警告；无业务改动，属于基线现象，后续处理，不阻碍布局 |
| 前端生产构建 | **通过，59 modules**；Vite7.3.6 | 生成约344.12kB JS、60.87kB CSS（未gzip）；未做加载性能/浏览器验收 |
| 后端首轮 | 中断，不能记为通过；无可确认测试数量 | 普通沙箱长时间无输出，停止本轮自己创建的进程；未把环境限制算业务失败 |
| 后端隔离重试 | **689通过、0失败、0跳过，208.18秒** | 1条现有Starlette TestClient/httpx弃用警告；未修改业务，不阻碍1A，但未来升级测试依赖要单独验证 |
| 迁移/恢复/无Key核心链路 | **通过，包含在689项内，不重复累计** | test_revision_migrations_dashboard、test_task_breakdown、test_growth_data、test_growth_migrations、test_engineering_quality覆盖空库/已知旧库/重复升级/未知结构拒绝、v1/v2恢复、Mock拆解→排程→反馈→统计 |
| 迁移CLI新空库/重复执行 | **2次命令均通过**；head=0002_task_hierarchy、26张业务表、integrity_check=ok、tasks=0 | 仅新建测试库；CLI验证与套件用例分开，不计为新增pytest数量 |
| 文档与CI定义检查 | **通过，196个发布文件，0个坏本地链接**；`& $py scripts/check_repository.py` | 本地静态检查，不等于GitHub运行 |
| 正式app.db结束哈希 | **与开始时完全相同** | `Get-FileHash -Algorithm SHA256 -LiteralPath backend/data/app.db`；只核对文件，未运行个人库迁移 |
| 真实Provider、浏览器、100任务压力、移动触摸、生产部署 | 跳过，测试数量不适用 | 按阶段0不收费/不集成边界；不影响1A，但不能据此批准完整V2上线 |

后端现有轻量性能回归比较7个固定小场景指纹，不等于本次测得10/30/100任务压力延迟。默认前端15秒与服务端多策略20秒预算的差异只是静态风险；未观察到用户环境的实际超时事故。

迁移CLI补充实际命令（根目录，先确认目标不存在）：

```powershell
$env:SGA_DATABASE_PATH='E:\homework\student-growth-assistant\scripts\.local\v2-stage0-1792551943727-retry\migration-cli-20261021.db'
if (Test-Path -LiteralPath $env:SGA_DATABASE_PATH) { throw 'CLI test target already exists; refuse reuse' }
$env:SGA_BACKUP_DIR='E:\homework\student-growth-assistant\scripts\.local\v2-stage0-1792551943727-retry\cli-backups'
& $py scripts/migrate.py
& $py scripts/migrate.py
```

随后用Python sqlite3的`mode=ro`连接该新库，核对Alembic版本、`PRAGMA integrity_check`、业务表数和tasks行数，结果如上。没有在正式库运行此命令。

## 7. 风险及开发入口条件

| 风险 | 影响 | 进入下一阶段前的处理 |
|---|---|---|
| 开发/精简main分叉，测试可能二次丢失 | 后续集成失去回归保护 | 固定本报告SHA；每次对main集成审核tests/fixtures/CI保留情况 |
| 多个页面复制正式数据、切tab卸载与迟到响应 | 未保存编辑丢失、错误会话被更新 | 壳级UI状态、按资源ID编辑缓存、单一正式数据读取层和失效刷新 |
| 三种草案确认协议不同且scope/周耦合 | 多端编辑覆盖、旧草案越过确认 | 复用事务与revision，补编辑version与引用；不能把所有确认路由当同一语义 |
| 范围读取/回顾事实尚未统一 | 年视图空白/重复课程、错误统计 | 展示范围独立于两周规划；设计有界只读API及上海日/月边界测试 |
| JSON严格schema+单例+无身份控制 | 升级无法恢复、部署后数据越权 | 新增模型同步制定格式转换；上线前完成全链路归属/权限，不仅添加字段 |

另有进程内后台任务重启丢执行、WorkspaceChat无总轮询期限、长消息列表无分页、搜索预算与HTTP期限不一致等工程风险。先增加可测量验收，再决定是否引入队列、流式协议或查询库。

阶段1A可以在用户审核通过后开展；阶段1B应先完成状态/请求隔离测试和现有业务回归，明确它仍接入旧scope能力。统一长期聊天、全部日历视图与复盘记录属于后续API/模型阶段，不能靠换壳宣称完成。

## 8. 交付自查

仅新增三个约定Markdown文件；未编辑frontend/src、backend/app、迁移、运行依赖或锁文件。切换基线恢复的开发资产是原有提交内容，不是本轮重写业务。最终提交/工作区状态以本轮最终汇报中的实际Git输出为准，避免在提交文件中记录自身尚不存在的SHA。

**阶段0结束后停止，等待审核。**

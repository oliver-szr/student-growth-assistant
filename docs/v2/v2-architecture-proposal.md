# Student Growth Assistant V2 开发主文档

更新日期：2026-10-21。本文合并阶段0审计、架构建议与关键结构原型，后续V2开发直接更新本文，不再按阶段新增报告。
产品规则以[《v2产品框架设计》](../v2产品框架设计.md)（2026-10-20版）为准；已完整对照其第1–14节及核心验收清单。产品原文独立保留，本文只记录技术约束、证据和实施边界。
2026-10-21用户最终确认交互修订：左导航提供中央完整功能，右侧始终是独立的极简预览；四主体共用辅助栏宽度、页签和三态，但主辅日期、视图、复盘范围及档案分区彼此独立。右侧日程固定单日，正式数据同源；四主体复用一个自动更新的北京时间。此规则覆盖原主辅同步日期/视图、异类辅助页签显示完整页面及未提交表单提示的设计；产品原文按要求保留。最近补丁基线04f8017，最新实现与验证见11.7；11.5/11.6是历史快照。
旧业务接口与数据库继续参考[现行架构](../architecture.md)、[API契约](../api-contract.md)、[数据库说明](../database.md)，会话后端契约以12.1及实际迁移为准，前端接入与刷新编辑恢复见12.2。除第11节与12.1/12.2明确标注的已实现内容外，其余新增API、模型、组件、协议及选型仍为建议，不能视为已实现功能。
阶段0.5仅整理文档和明确安全的本地临时产物，已于阶段1A开始前单独本地提交 `afa731d`。阶段1A的范围与验证见第11节；阶段1B-1A真实会话后端基线为 `8691fb5`。本批1B-1B接入真实会话与刷新恢复，未开发统一AI聊天；未push/merge/创建PR。

## 1. 目录与维护边界

```text
student-growth-assistant/
├── frontend/
│   ├── src/                 React页面、组件、api.js、样式及纯函数
│   └── tests/               前端测试与fixtures
├── backend/
│   ├── app/                 FastAPI路由、模型、契约与业务服务
│   ├── alembic/             冻结基线与有效增量迁移
│   ├── tests/               后端测试与匿名fixtures
│   └── data/                正式本地数据库（忽略，保护）
├── scripts/                 迁移、演示、验收及基准工具
│   ├── .local/              本地验收/历史副本，逐项审计后处理
│   └── .runtime/            运行状态、数据库与备份，保护
├── docs/
│   ├── v2产品框架设计.md    正式产品基线，保留原文
│   ├── v2/
│   │   └── v2-architecture-proposal.md  本开发主文档
│   └── architecture.md、api-contract.md、database.md等现行文档及archive/
├── .github/workflows/       CI
└── codex/                   历史本地工具及运行资料，来源不明不删
```

目录链接/junction不跟随、不递归清理。数据库、备份、密钥、配置、测试源码、fixtures、迁移、锁文件和node_modules不是清理目标。
源码与文档的当前未提交移动/修改必须保留，不能先清空工作区。Git标签保护代码，不替代数据库备份。

## 2. Git基线与回退证据

以下为2026-10-21首次阶段0审计的引用快照，整理时未重新fetch。阶段0.5开始时实际分支为 `feat/v2-workspace-redesign`，HEAD仍为已知阶段0提交，工作区有文档移动/修订及未跟踪文件，暂存区为空；不能宣称干净。

| 引用 | 完整SHA / 结论 |
|---|---|
| 推荐完整开发基线：feat/planning-growth-upgrade | `5f953c91722408b484608e06c69280f9826e0080`；本地分支，无同名远程跟踪引用 |
| 初始HEAD / release/course-submission / origin同名分支 | `cf8853dd0e08b06405b7b980c96b4e15285b51d1`，精简运行交付 |
| 本地main / 既有v1标签解引用 | `acded0ae13b523ad16ca99b37cbd846e1081a0c2`；首次fetch后本地main落后远程13个可达提交 |
| 首次fetch后的origin/main | `16acda6dbde8f1a355139c0aade3a0d9d56f6428`，合并PR #1，文件树与release一致 |
| release与完整开发共同祖先 | `4d4a60b9a1ed102f043a6ff077c9cbaa84585023` |
| V2工作分支上的阶段0文档提交 | `b8e57b0d4714a9cb5c83035a44af986d31062d5e`；其父提交为推荐基线 |
| 本地注释回退标签 | `v1-v2-baseline-2026-10-21` → 推荐基线5f953c9；未推送，既有v1未移动 |

origin为 `https://github.com/szt1107/student-growth-assistant.git`。首次执行status/remote/branch/log/rev-parse/merge-base/ls-tree/diff及安全fetch；fetch先因沙箱无法写FETCH_HEAD失败，获执行权限后成功，无自动合并。

选择5f953c9的依据：
- 对比完整开发与release的 `backend/app`、`frontend/src`、`backend/alembic`、前端锁文件，差异为空，业务与迁移一致。
- release相对完整开发有83文件差异、152行新增/8804行删除，主要删测试、fixtures、CI、开发脚本及报告，同时删除npm test入口和pytest依赖声明。
- 5f953c9在共同祖先后额外增加88行拆解Provider传输/失败隔离测试；不能用README或分支名替代这些文件证据。
- 完整开发包含确认安全5366e0f、局部重规划0ccc719、任务层级e82e2b3、统计1c5b2cb、性能54684a7、备份6995175、CI e0ac6eb、目标/集成4de28b9等提交，保留团队作者历史。
- 当时全部可达refs中，开发分支之外只见精简提交及合并，未发现遗漏业务；不覆盖不可见分支或他人未提交工作。

未来与main集成须审查测试/fixtures/CI的精简删除，直接合并可能再次丢资产。回退先保存届时工作，从回退标签另建检查分支；不得reset --hard/clean/强制checkout/擅自stash。新schema回退要匹配旧应用和升级前数据库备份，不能只切Git标签。

## 3. 当前能力与复用矩阵

以下为首次审计源码证据，主路径均相对仓库根目录；1A只调整前端编排与布局，后端业务契约保持不变。正式数据默认在 `backend/data/app.db`，`SGA_DATABASE_PATH`可显式覆盖。

| 模块 | 入口、关键实现与存储 | 复用及V2缺口/风险 |
|---|---|---|
| 任务与父子层级 | frontend的TasksPage/TaskForm/TaskHierarchy，经api.js调用GET/POST /api/tasks、PATCH /api/tasks/{id}；backend/app/routers/tasks.py、services/task_hierarchy.py；tasks、task_growth_contexts | 复用CRUD/汇总；仅两级、每父最多20项、子DDL≤父DDL。无硬删除，取消不等于DELETE；父容器不直接执行/取消/排程，有计划/执行事实时限制类型转换 |
| AI/手动拆解 | frontend/src/components/TaskBreakdown.jsx；/api/tasks/breakdown-drafts的创建、查询、PATCH、confirm/discard；services/task_breakdown.py；GrowthChangeDraft(scope=task_breakdown)、AssistantSession/Message | 合法编辑1.2秒自动保存、version/source_revision、幂等整树创建可复用；原始预期保留，顺序非依赖网络；确认创建任务后仍需另行确认日程 |
| 排程、策略、局部重规划 | AssistantPage、ScopedChanges、assistant.js；routers/assistant.py的preview/confirm；services/assistant_state.py、assistant_scheduler.py、scoped_replanning.py；assistant_proposals、plans/items、task_scheduling_profiles | 本周剩余+下周、5分钟网格、三策略、有限分段、独立校验、局部范围和两周原子保存可复用；扩大范围须显式同意，锁定/已开始/历史不被移动 |
| 旧单周兼容 | api.js的createCandidatePlan/getConfirmedPlan/confirmPlan；routers/plans.py、services/scheduler.py、validator.py、plan_safety.py；plans/items | 保留兼容/历史按周读；重复confirm返回409 PLAN_NOT_CANDIDATE，与Assistant重复applied幂等成功不同，不能统一假设所有确认同语义 |
| 课程、保护时间、偏好 | TimeRulesPage、NaturalLanguageTimeRule、TimeRuleForm；/api/time-rules、/api/constraints/parse、taxonomy相关接口；services/course_import.py、taxonomy.py；time_rules、course_imports、preference_rules/categories | 复用CRUD/停用/周期展开/偏好编译。规则保存不自动修复正式日程；旧AI parser只支持周期课程，结构化可有单次课程；无学期/节假日字段，全年展示须说明依据 |
| 执行反馈与计时 | TasksPage submitFeedback/timerAction；routers/execution.py、services/growth_tracking.py；task_feedback、task_work_sessions、tasks/context | 复用幂等反馈、暂停继续、更正/撤回及快照。计时结束/日历过去不自动完成，计时不叠加反馈耗时；直接done可能只有未知耗时事实 |
| 统计、目标、旧周复盘 | GoalsGrowthPage、GrowthAnalytics；/api/growth/statistics?weeks=4/8/12及end_week、/api/growth/reviews、/api/goals；growth_statistics、growth_tracking、routers/growth_reviews.py | 复用有效反馈/去重/目标汇总、只读统计与周快照；4周不是自然月，旧周复盘生成即保存，无用户认可结论的正式记录流程。现前端反馈确认后会自动生成周说明，须与新记录流程拆开 |
| 聊天与运行 | AssistantPage、WorkspaceChat、ChatMessages、SafeMessage；routers/assistant.py create/open session、create/get/cancel/retry run；assistant_sessions/messages/runs/proposals、growth_change_drafts | 消息/运行持久化、失败输入和确认边界可复用；无完整会话列表/重命名/搜索片段/置顶归档删除/分页/小结，缺统一自由聊与回复文本增量 |
| 档案与记忆 | MyProfilePage、TimeRulesPage；/api/profile/context、growth/profile、goals、task-categories、assistant/preference-rules；growth_user_profiles/revisions、goals/revisions、偏好与时间规则 | 表单/来源/历史可复用；ai_note只是偏好说明，不是带来源、确认、失效与删除管理的通用长期记忆 |
| 导出恢复与迁移 | MyProfilePage export/import；routers/data.py、services/growth_data.py build_snapshot/restore_snapshot/create_sqlite_backup、schema_migrations.py；backend/alembic | JSON v2严格26业务表，冻结v1转换、事务恢复、在线备份可复用；新表/列需同步升级JSON格式/转换器/fixtures，不能只加Alembic |

现有会话的具体限制：planning按周，localStorage使用workspace_id+本周；旧会话GET可读，但require_current限制旧规划继续运行。review按周，profile用1970-01-05哨兵周，拆解有专用scope；不能只改scope名称实现独立长期聊天。profile/review上下文最多带最近8消息/20反馈，消息缺created_at和通用多业务引用，GET消息一次全取。
异步worker在进程内，重启把running标interrupted，不是持久任务队列；GET run还可能因revision变化标失败。前端规划轮询700ms/270秒，WorkspaceChat轮询800ms无总期限，切页卸载/迟到响应须测试。
api.js默认15秒，显式AI125秒、导出恢复60秒；Provider支持Anthropic Messages/OpenAI Chat Completions，超时1–120秒且脱敏，无通用流式协议。单策略20秒/50,000扩展/64状态不保证整个HTTP硬超时；15秒与多策略预算差异是静态风险，未证明发生用户环境故障。

## 4. 总体架构与数据流

保留React/Vite/JavaScript、FastAPI、SQLAlchemy/SQLite、Alembic和Provider。routers负责HTTP，services负责业务，models/schemas负责持久化/契约；现有assistant路由仍有编排，不为整理大规模搬代码。

```mermaid
flowchart LR
  N[导航 / 会话列表] --> U[壳级UI状态]
  C[唯一主聊天] --> A[消息与业务适配层]
  W[固定三页签工作区] --> A
  A --> R[统一只读服务端缓存]
  A --> API[FastAPI白名单工具/路由]
  API --> P[Provider理解 / 程序查询计算]
  P --> D[持久草案 / 事实快照]
  D --> Q[用户确认 + 版本/当前约束复验]
  Q --> S[原服务 / Validator / 事务]
  S --> DB[(正式SQLite数据)]
  DB --> R
```

聊天是交流和引用，Task/Plan/Feedback/Goal等是正式事实源。AI可查询、解释、提草案，不能直接SQL、写PlanItem、确认操作或扩大调整授权。手动正式表单“保存”本身是明确提交，不额外层层确认。
正式写入复用BEGIN IMMEDIATE、source_revision和Validator；Provider等待释放事务，部分同步排程路径仍持写事务。UTCDateTime保存UTC，业务日期/钟面为Asia/Shanghai，5分钟粒度不静默取整。
启动main.lifespan会备份、升级、初始化与中断旧run；审计/演示不得指向个人库。正常启动不导入Mock工具。

## 5. 关键结构原型与交互

以下均为目标结构，数据为示意。颜色、像素、断点、动效、登录方式/部署商未冻结；引用Notion Calendar时间网格与滴答清单侧栏原则，不复制品牌资产/源码。

### 5.1 默认首页与四区

```text
┌──────┬──────────────┬──────────────────────┬────────────────────────┐
│ 导航 │ 会话 [收起]  │ 本次对话 [改名]       │ [日程●][复盘][档案]    │
│ 首页●│ ＋新对话     │                      │ 今日 [收起][展开]      │
│ 日程 │ 搜索标题/正文│ 你：看看今天怎么推进。 │ ‹ 日期 › [回到今天]   │
│ 复盘 │ 置顶 / 最近  │ 助手：简短结果…       │ 09:00 课程             │
│ 档案 │ 当前对话     │ [查看任务/草案]       │ 14:00 正式任务         │
│      │ 其他对话     │                      │ 少量待确认事项提示     │
│ 账号 │ 已归档       │ [输入消息____][发送]  │                        │
│ 预留 │              │ [停止/失败重试]       │                        │
└──────┴──────────────┴──────────────────────┴────────────────────────┘
```

首次首页聊天为主、右侧今日，无复杂看板；之后聚焦聊天并恢复工作区，显式“回到今天”才重定位。账号区先留空。
左导航选择中间主体：首页聊天、日程日历、复盘正文、档案正文。右侧辅助页签独立选择日程/复盘/档案，不改变主体；首页首次右侧今日，之后恢复用户选择。左导航打开工具时收起会话列表，右侧辅助栏的页签、宽度与收起/展开状态保持不变。辅助栏在四个主体间共用，主动收起后主体使用增加的空间。导航不创建会话、不清输入、不自动确认。
每类工具保留一个数据控制器与完整编辑缓冲，完整页面固定在中央且隐藏时保留挂载。右侧始终只读预览：日程复用原Calendar的单日过滤，只显示正式课程/任务及少量待确认提示；复盘显示本周确认完成、记录投入和有效反馈；档案显示少量已保存目标/偏好。主辅UI各自独立，不因同类数据就共享日期、视图、范围、展开或表单状态；正式保存通过原数据刷新更新摘要，不复制业务事实或增加轮询。聊天的安排偏好/查看方案入口直接打开对应中央完整功能，辅助页签只切预览。四个中央页头右上角共用一套自动更新的日期时间，辅助栏自身调宽/展开/收起操作保留。
用户点击或明确说“查看日程/复盘”就直接打开并简述；AI只认为可能有用时给“打开查看”入口。编辑中顺带提别话题不跳页；明确跳页也保留原编辑。

### 5.2 主体日历、辅助栏与宽度调整（用户新确认修订）

```text
首页：[导航：首页●][会话/收起入口][聊天主体 ⇔ 拖动分隔线][辅助：日程/复盘/档案]
日程：[导航：日程●][主体周日历 ⇔ 拖动分隔线][共用辅助栏]
复盘：[导航：复盘●][主体复盘正文 ⇔ 分隔线][共用辅助栏]
档案：[导航：档案●][主体档案正文 ⇔ 分隔线][共用辅助栏]
主动收起辅助栏后：[导航][             主体使用剩余宽度             ][‹辅助栏]

主体日程主动收起辅助栏后的示意（进入页面不会强制收起）：
┌──────┬──────────────────────────────────────────────┬────┐
│ 首页 │ 日程                            当前日期时间 │ ‹  │
│ 日程●│ [单日][本周/下周] [查看日期] [回到今天]     │ 辅 │
│ 复盘 │ 时间 │ 一 │ 二 │ 三 │ 四 │ 五 │ 六 │ 日    │ 助 │
│ 档案 │ 09   │课程│    │    │    │    │    │       │ 栏 │
│      │ 14   │    │任务│    │    │    │    │       │    │
└──────┴──────────────────────────────────────────────┴────┘
```

主体日程首次使用完整周视图，复用原日历且保留选中日期；此后保留用户的视图选择。所有主体右侧日程始终为单日预览，默认今天，可上一天/下一天、选日期、回到今天；展开或调宽也不切周视图。两个日期状态独立，主体修改日期/视图不影响右侧，右侧选日期不影响主体。当前数据窗口仅本周与下周，日期控件明确限定已有查询范围，不暗中扩大排程。
四个主体桌面普通布局均使用同一分隔线调整主体/辅助栏；支持键盘方向键、Home/End及Enter恢复默认，也有恢复默认按钮和双击复位。主体偏好比例默认58%，全局限35%–75%，另保证主体至少360px、辅助栏至少320px；窄桌面按可用宽度进一步约束。按本机保存宽度偏好，缩放窗口不覆盖原偏好。
辅助栏保留收起/普通/展开。展开可临时隐藏首页会话栏，恢复时保留原偏好；切换主体不重置同一个辅助栏的宽度、页签及三态；用户可随时主动收起/恢复。两个区域的日期、表单与业务状态不因调整空间清空。隐藏区域不接受Tab焦点。
手机在会话/主体/辅助栏之间单视面切换，主体标签随左导航显示“聊天/日程/复盘/档案”，辅助页签不改变左导航。移动端不显示或启用分隔线拖动。

事件详情复用编辑/执行/生成调整入口，正式、候选、课程有文字及样式区分；父容器不占日历，未安排任务在列表。多段是多个事件但一项任务；计时结束不代表完成。
日/周显示时间轴、空闲与冲突；月显示任务概览、真实截止/重要事项；年为12月概览及真实重要阶段/长期节点。年点月、月点日，切视图围绕selectedDate，“回到今天”定位所在日/周/月/年。浏览范围不扩大两周排程，无数据不造节点，加载失败不显示成空数据。

### 5.3 会话与主聊天

列表固定置顶/最近/归档/搜索，无复杂文件夹；跨多天，用户决定新建。形成话题生成短标题、允许改名，手动标题不被覆盖；最近按活动排序。搜索标题与正文，返回片段及匹配原消息；归档可搜索/恢复。
删除说明不连带删正式任务/日程/反馈或独立记忆，运行/未决草案单独处理；具体保留期/最终销毁待定。阶段3按需会话小结附原消息跳转，不自动成为记忆或复盘。
主聊天不让用户选规划/复盘/档案模式；先结果、依据按需展开。回复文本逐步显示，同时标理解/查询/计算，只有阶段轮询不算文本增量。停止/失败保留输入，重试不换幂等ID；已保存操作仍显示真实receipt。
后续语音先“转文字→用户检查修改→发送”，不自动发送，连续语音/播报不列首轮验收。

### 5.4 主体复盘与档案

```text
[中央主体：复盘]                      [统一日期时间]
[回顾●] [复盘记录]
[日] [周●] [月] ‹ 范围 › [回到当前]       默认本周
已记录完成 [查看]  已记录投入 [查看]  待反馈安排 [补录]
时间分布 [按天/按类别] → 点击同范围来源事项
事项 [全部/已完成/部分完成/待反馈] [查看全部]
目标进展（有关联目标和记录才显示）
[和AI复盘] [自己写几句]；详细比较按需展开

复盘记录：[搜索标题/正文] [日/周/月] [时间范围]
标题｜时间｜短摘要｜下一步 → 全文/编辑/关联任务与依据/返回聊天
待保存草案另设入口；旧周说明标“历史生成”，不标用户已确认

档案：[目标｜时间与课程｜偏好｜记忆｜数据管理]
只显示所选分区；复用已有表单，不强迫首次填完
```

以上完整统计、筛选、编辑和记录入口属于中央主体；右侧只提供本周极简摘要，不共享主体筛选/展开状态。档案右侧只读正式目标/偏好，中央二级分区和未提交表单不投射到右侧。

回顾先读事实不依赖AI；待反馈≠未完成≠缺耗时，未知不当零。完成、投入和安排分别按完成时间、发生时间、原安排时间，数字/图表可查来源且同范围；不重复计父子，不虚构历史完成率，不做效率评分/排名/人格或复杂情绪标签。
“和AI复盘”带所选范围/必要记录进入同一主聊天，保留右侧；先事实再讨论具体问题。聊天主动点“整理为复盘记录”才给可编辑预览并确认；“自己写几句”无需AI/问卷，直接保存即提交。编辑字段包括标题/范围、回顾摘要、我的结论、下一步（可空）和关联来源；感受可原样保留。
保存复盘保留当时快照/来源，不随数据变化暗改，编辑/再整理有版本及变更提示；应用任务/排程/档案调整是另一草案和确认，优先更新已有任务并回链结果。空白可补反馈或自由聊。
档案区分当次聊天、正式事实、确认记忆；“今天很累”不自动成长期标签，长期偏好提议确认后生效。个人信息可查依据/修改；ai_note不能冒充通用记忆。数据管理说明导出/恢复影响与保护范围。

### 5.5 手机与恢复规则

```text
[会话] 当前对话 [工作区]
消息 / 业务卡片 / 新回复提示
[输入][发送]；运行中可停止，失败可重试
[首页][日程][复盘][档案]
会话 → 全高列表；辅助栏 → 单视面预览；完整工具由主导航进入
```

手机切换列表/主体/辅助栏，不挤四列；软键盘不遮保存/发送，返回关闭当前层再回来源，保留编辑。1A/1B保证基本可用，3完善触摸/无障碍等实测。
切会话保留各自输入/草案，迟到响应只写所属会话；只停止观察，不默默取消后端。新回复沿用ChatMessages的“有新回复”，不强拉历史阅读者到底部。
切页/收起/刷新恢复日期、视图、输入与编辑；本地缓存按workspace/资源/baseVersion分区，恢复先读服务器版本。存储失败需提示，未提交编辑不承诺跨设备恢复；服务器已保存草案才可继续。恢复数据库/切身份使正式缓存失效并隔离旧编辑，不能向新资料应用旧草案。

## 6. 前端状态与复用设计

| 状态 | 唯一归属 / 更新规则 |
|---|---|
| 当前会话、主体页、辅助页与三态 | 顶层UI独立字段navigation/auxiliaryPage；辅助栏panel/splitRatio为四页共享状态，导航与会话选择独立；持久ID先经服务端验证 |
| 共享宽度偏好 | 只存设备级比例，渲染时按视口/会话栏计算上下限；不复制正式数据或编辑缓冲 |
| 日期/日历视图/滚动与二级分区 | 主体和辅助预览分别归属；主体日历日期/视图与previewDate独立，复盘摘要固定本周、不读主体统计范围，档案摘要不读编辑/二级分区；展开只改空间 |
| 中央页头日期时间 | WorkspaceApp唯一时钟，以首次settings.now为锚加本机经过时间，每分钟更新并沿用Asia/Shanghai与演示前缀；四页传入相同文字，不请求轮询 |
| 未提交编辑 | 按实体/ID/归属/baseVersion的编辑缓冲，dirty/error保留 |
| 业务草案 | 服务端资源单一缓存，UI持type/id/version/status/source_revision引用 |
| 正式业务数据 | 服务端事实；本地只读缓存，成功receipt触发相关查询失效，不多组件各改数组 |
| 消息关联与run | 历史摘要+当前资源权限，按conversation/run隔离，generation token防迟到覆盖 |

1A先用现有App的React state/reducer及回调，复用workbench.js纯函数；不默认建features/state/workspace目录。需要跨层共享再引入最小Context，状态库不是前提。后续若评估TanStack Query，必须成为唯一server cache，不能再保留另一份可变正式store；URL不放私人输入/密钥。

双向草案：聊天与面板引用同draft → 手动dirty编辑协调 → 带expected_version保存 → 两边更新同缓存 → 用户确认 → 后端当前约束复验 → receipt刷新正式数据。
AI继续操作该草案前，先保存有效手动编辑并等版本，或走明确临时预览契约；无效编辑保留并要求修正，不能用旧服务器草案覆盖。普通闲聊不强制保存。
409保留本地对照/重建，确认先等保存结束；网络超时先按原ID查结果，不乐观宣布成功、不换ID重发。source_revision防正式数据变化，draft version防草案自身并发，不能替代彼此。

## 7. 技术选型与依据

| 方案 | 能力、成本与决定 |
|---|---|
| FullCalendar React标准插件 | React19/Vite适配；timeGridDay/Week、dayGridMonth、multiMonthYear，interaction支持点击选择和后续拖拽；首次适配中等、四视图维护较省。标准插件MIT，个人纵向时间网格不需资源Timeline。优先推荐，1B过渡周日历，2B独立接入 |
| React Big Calendar | React19 peer、MIT，日周月/agenda、localizer和拖拽addon；无内置year，需自定义年视图和时区验证，作为备选 |
| 扩展旧Calendar | 当前React/Vite已用、短期周视图改动最少；固定08–22、绝对定位，补日/月/年、重叠/触摸/键盘成本高。只作过渡，不能以周视图替代最终四视图 |
| 复用聊天组件 | ChatMessages、SafeMessage及现有composer/run控制优先；保留中文错误、历史跟随、受控确认；需统一重复轮询、会话/卡片/消息增量，并非换布局即有自由聊 |
| assistant-ui / 开源聊天UI借鉴 | ExternalStoreRuntime可桥接自有后端/store，React18/19、MIT；仍需202轮询/增量、会话和草案适配，增加依赖/样式成本。后续实证收益再引入，不要求Next.js/换FastAPI，不复制未核授权源码 |

首次审计于2026-10-21核官方源码/npm元数据；文档站403后改核上游，不表示本次重查或本机集成通过：
- FullCalendar React 6.1.21 [peer/许可证](https://github.com/fullcalendar/fullcalendar-react/blob/v6.1.21/package.json)、[标准MIT](https://github.com/fullcalendar/fullcalendar/blob/v6.1.21/LICENSE.md)、[年视图源码](https://github.com/fullcalendar/fullcalendar/blob/v6.1.21/packages/multimonth/src/index.ts)、[multimonth发布许可](https://registry.npmjs.org/@fullcalendar/multimonth/6.1.21)已核。
- resource-timeline当次6.1.22发布包LICENSE列Commercial付费、CC BY-NC-ND 4.0、GPLv3三选一，[发布元数据](https://registry.npmjs.org/@fullcalendar/resource-timeline/6.1.22)不是MIT；未承诺课程自动免费或价格，当前仓库无GPL声明，选定方案不依赖Premium。
- React Big Calendar当次仓库1.20.0：[package](https://github.com/jquense/react-big-calendar/blob/master/package.json)、[MIT](https://github.com/jquense/react-big-calendar/blob/master/LICENSE)、[内置视图](https://github.com/jquense/react-big-calendar/blob/master/src/Calendar.js)。
- assistant-ui React当次0.15.30：[package](https://github.com/assistant-ui/assistant-ui/blob/main/packages/react/package.json)、[MIT](https://github.com/assistant-ui/assistant-ui/blob/main/LICENSE)、[ExternalStoreRuntime](https://github.com/assistant-ui/assistant-ui/blob/main/apps/docs/content/docs/runtimes/custom/external-store.mdx)。开源UI不等于云服务免费。

后续安装锁定兼容精确版本并核实际发布包/转依赖，测试Vite、上海时区/浏览器不同时区、短块重叠/跨日/多段、键盘触摸。named timezone须使用受支持适配器或明确转换策略，不能误用UTC coercion。
CalendarAdapter纯转换ref/plan_item_id/occurrence/draft_version/segment为稳定event键及extendedProps；候选用独立overlay。复用visibleSchedule的保留/移动语义，课程live occurrence与历史PlanItem快照明确来源并去重。截止/目标日期独立kind，不伪造安排分钟。
初期editable=false；后续拖拽先还原视觉位置并生成有源版本草案，再确认，不能直接写PlanItem。课程移动与任务重规划分开。

## 8. 后端与数据演进（仅设计）

### 8.1 会话、消息、增量与工具

1B优先扩展AssistantSession/Message而非另存复制正文。建议title/updated_at/pinned_at/archived_at/删除状态、created_at/schema_version、归属及索引；聊天不绑定week_start，规划周放tool context。旧scope/哨兵周只作兼容，历史确认继续require_current，不编造旧消息发生时间。
列表/消息稳定分页；搜索后端按owner/归档过滤标题和正文并返回片段/原消息，不把全库交前端搜索。重命名保护手动标题；删除不级联正式事实，未决运行/草案和保留期另定。会话小结保留source_message_ids，不自动变为记忆。
复用AssistantProposal/GrowthChangeDraft，统一只读envelope(type/id/version/status/source_revision/origin_message_id)和消息业务引用；多态引用必须校验存在、类型、归属。profile/review preview目前缺编辑version，需补；planning latest链、拆解version/created_task_ids与旧confirm差异保留。
统一useAssistantRun并设计可恢复text delta/sequence/terminal/receipt；SSE或游标增量轮询待比较，不默认WebSocket。断线续读去重、停止不掩盖已保存结果，不转发密钥/原始推理/未校验工具。消息分纯reply/查询/needs_input/draft/receipt/导航，空闲交流不产生业务。
导航只接受白名单page/date/period/resourceRef及用户明确请求标记；AI建议仅给入口。工具调用按需取事实和已确认相关记忆，避免全历史外发。

| 建议接口 | 范围及阶段 |
|---|---|
| /api/conversations列表/创建、/{id}修改/删除、messages分页 | 1B会话管理、标题/正文片段搜索、置顶归档恢复；保留旧sessions兼容 |
| conversations/{id}/runs及run增量events | 1B自由回复/停止重试，2A完整查询/业务白名单工具 |
| conversations/{id}/summaries | 3按需小结与原消息引用 |
| GET /api/calendar/events?start&end | 2B有界正式安排、当前周期课程、独立deadline/goal节点，end不含，不写数据或生成计划 |
| GET /api/reviews/facts及来源明细 | 2B自然日/周/月范围、as_of/口径、按天/类别和状态筛选/下钻 |
| /api/review-drafts创建/编辑/confirm；review-records列表/创建/详情/版本编辑 | 2B AI草案确认与手写直接保存共用服务；记录搜索/周期筛选/关联与版本 |

范围读取用区间相交(start_at < end且end_at > start)，非只按week_start；限制跨度/条数，年可分月/季度加载。当前周期规则逐周有界展开，无学期/假期信息明确说明。Task.deadline、Goal.due_date等节点读真实记录，额外重要事件/里程碑模型另评估，不造数据。
统计抽共享范围聚合复用growth_tracking有效反馈/完成去重，不能复制另一套口径。待反馈按原安排与有效反馈关联定义，先明确多段/部分反馈覆盖规则，不能用todo或actual_minutes空代替。所有下钻共用范围/as_of；回顾GET不需AI、不写复盘。

### 8.2 复盘记录、记忆与兼容

ReviewRecord可评估扩展GrowthWeeklyReview或新表：title/period/start/end/timezone、summary、user_conclusion、next_actions可空、facts_snapshot/schema_version/as_of、task/goal/source refs、conversation/message、version/confirmed_at/owner。手写无需会话/AI，事实不足不造依据；AI整理草案确认后共用保存服务。
旧GrowthWeeklyReview没有用户确认证据，标legacy_generated，不能补造confirmed_at。正式记录按时间/搜索/周期筛选，编辑expected_version并留历史；再整理提示基础事实变化，旧快照不暗改。保存记录和应用行动独立，更新原任务避免重复并回链receipt；产品场景A不自动意味着拆解与排程必须合为新大事务。
目标/偏好/课程继续在原表。后续MemoryEntry区分草案/确认、来源、版本、适用范围、失效/删除；只检索已确认未失效信息。先可管理列表/确定性筛选，再按证据评估向量检索，删聊天与删记忆范围分别说明。

1A开始设计owner/workspace，1B首批新增模型/索引/查询预留本地owner映射；4实现身份与全部权限。当前PlanningState、GrowthUserProfile、AssistantPreference、WorkspaceMetadata等单例和唯一计时/每周正式计划索引都需按owner演进，不能只加user_id就宣称隔离。服务端解析身份，不能信请求体owner，禁止跨用户父子/目标/草案引用。
新增结构用新Alembic revision，不改0001/0002及冻结baseline_models；SQLite重建、FK/索引、空库/旧库/重复升级/未知结构拒绝和备份均须测。JSON严格全表/列，扩展必须新格式及显式v1/v2转换，冻结旧v2契约和匿名fixtures，不能旧JSON恢复清空新表。恢复整事务，提高revision、旧草案stale、running interrupted，刷新/隔离UI缓存；重要备份独立于5份轮换。
主要业务本地保存不等于数据不离机：外部模型会收到必要上下文，密钥只在服务端，个人信息可查依据与修改。4设计用户级导出/删除/恢复，当前整库恢复不能用于多用户自助。5验脱敏日志、费用承担/额度、灾备和试用，服务型数据库依实际并发决定。

## 9. 首次阶段0验证与风险基线

以下是阶段0首次实际运行证据；阶段0.5仅做静态检查，阶段1A新增验证另列于第11节，不把旧结果作为新一轮运行：
| 验证 | 结果与边界 |
|---|---|
| 环境/依赖 | app_env Python3.11.16，Node24.13.0/npm11.6.2；pip check通过；CI为Python3.11/Node22，本机通过不等于本次跑了远程CI |
| 前端npm.cmd --prefix frontend test | 89通过/0失败/0跳过；原SVG title复合children有React警告 |
| 前端npm.cmd --prefix frontend run build | 通过，Vite7.3.6、59 modules；JS344.12kB/CSS60.87kB，非加载性能/真实浏览器验收 |
| 后端pytest | 首轮普通沙箱长期无输出后仅中断自建进程，不能记通过；隔离重试689通过/0失败/0跳过，208.18秒，1条Starlette TestClient/httpx弃用警告 |
| 迁移/恢复/无Key核心链 | 包含在689项内，不重复计数：test_revision_migrations_dashboard、test_task_breakdown、test_growth_data、test_growth_migrations、test_engineering_quality；覆盖新/旧库、重复、未知结构拒绝、v1/v2与失败回滚、Mock拆解→排程→反馈→统计 |
| 迁移CLI | 新空库连续2次scripts/migrate.py成功；head=0002_task_hierarchy、26业务表、integrity_check=ok、tasks=0 |
| 文档/CI静态 | 首版scripts/check_repository.py和git diff --check通过；整理后的静态结果以本轮最终汇报为准 |
| 未执行 | 真实付费AI、100任务压力、实际浏览器/移动触摸/全浏览器/多人并发与生产部署；不以自动测试替代 |

后端实际命令为app_env解释器在backend目录运行 `-u -m pytest -q -p no:cacheprovider --basetemp=<本轮新隔离目录>/pytest`；当时目录是 `scripts/.local/v2-stage0-1792551943727-retry`，全局SGA_DATABASE_PATH指其bootstrap.db、SGA_BACKUP_DIR指其backups，SGA_AUTO_BACKUP=0、SGA_SKIP_IMPORT_BACKUP=1、PYTHONUTF8=1。conftest按项新建UUID库、覆写get_db/engine、禁.env/真实key及Mock传输，无付费调用/个人库启动。
CLI只对上述隔离目录中新migration-cli-20261021.db运行；没有正式库迁移。首次及阶段0.5开始时app.db SHA256均为 `0DB97D1D9760B66C414F9E17C8C0369ECFC1D6DDDD0050972E18D68F3FC439CB`；哈希核对不是已替用户备份。7个轻量排程指纹回归不是10/30/100任务延迟实测。

| 关键风险 | 进入相关阶段前的约束 |
|---|---|
| 精简main再次删回归资产 | 集成前审核测试/fixtures/CI；不自动合并分叉 |
| scope/周耦合及多处可变事实 | 独立聊天+内部旧API适配；单一事实缓存、按会话请求隔离 |
| 草案版本/dirty和确认契约不同 | 同draft引用、版本协调、原ID查询结果、独立Validator与原事务 |
| 年浏览/回顾范围和事实混淆 | 有界范围API、真实节点、上海边界、来源下钻、零与未知分开 |
| schema/JSON/单例/权限 | 新迁移与格式转换一起设计；早期预留归属，4权限通过后5部署 |

## 10. 产品阶段与验收边界

| 阶段 | 交付与验收 |
|---|---|
| 1 新工作台 | 1A四区/固定三页签/状态与归属设计；1B真实会话管理、无模式主聊天、逐步回复和既有能力接入，能聊天切工具不丢进度；空壳不算1完成 |
| 2 AI办事 | 2A白名单工具/导航、双端最新草案、确认/receipt；2B四视图/范围查询、日周月回顾与手写/AI复盘记录，完整跑A聊天到日程、C复盘到调整 |
| 3 秘书体验 | 按需上下文、小结、可管理记忆、异常恢复与手机完善；场景B自由交流不自动生成业务；基本输入/幂等恢复早期已有要求 |
| 4 账号与隔离 | 登录/退出/必要账号恢复、单例/全查询/worker权限、用户级导出删除恢复，互不可见不可改 |
| 5 小范围部署 | 公开上线前隔离/可靠性通过；服务、灾备、脱敏日志、费用额度与试用；主体开发可先验证环境，不预设供应商或数据库迁移 |
| 后续扩展 | 语音转文字供检查发送；主动提醒/外部集成按试用安排，连续语音/播报非首轮 |

基础可靠性不能全部推迟3：失败保留输入、取消/已保存结果、网络重试幂等、切页刷新恢复、stale复验和窄屏基本可用从1开始。任何阶段目标尚未实现都须明确标注，不用占位图通过验收。

## 11. 阶段1A：四区工作台布局与状态骨架

以下11.1–11.5保留首版及a53a68b补丁的范围和验证快照；现行辅助栏规则以11.7为准，不沿用旧版工具页默认折叠、仅首页可调宽或主辅UI联动行为。

### 11.1 实际实现与文件边界

2026-10-21实施。开发前检查分支、HEAD、暂存区及未跟踪文件：只有阶段0.5的文档合并/移动和产品文档加入，无其他源码修改。产品全文与敏感信息模式核查未发现私人信息，保持原文SHA256不变，精确暂存相关5个路径，先提交 `afa731d`，再开发UI。产品原文两处行末双空格为Markdown换行，未为消除空白检查提示而改写。

| 文件 | 本轮实现 |
|---|---|
| frontend/src/App.jsx | 默认新工作台；单一reducer驱动导航/固定页签/三态/手机视面及已访问页集合；保留原任务版本刷新、调整回调和旧版编排 |
| frontend/src/components/WorkspaceShell.jsx（唯一新增文件） | 独立薄壳负责四区、会话区域、三页签、账号预留、手机单视面、焦点与无障碍属性；不管理业务请求、Provider或确认事务。单独成文件避免App/旧双列布局承担过多职责 |
| frontend/src/components/WorkbenchLayout.jsx | 可选renderLayout复用chat/children插槽；旧chat/children/view/resultLabel调用继续走原双列布局和尺寸测量 |
| frontend/src/pages/AssistantPage.jsx | 复用唯一规划聊天、ChatMessages/SafeMessage、运行与草案流程；分离现有聊天/日历/拆解及执行区域的呈现位置；现周日历可筛选单日，首次今天，支持本周/下周内选日期及回到今天 |
| frontend/src/pages/GoalsGrowthPage.jsx、MyProfilePage.jsx | embedded只展示现有正文，旧版仍使用WorkspaceChat；已访问页保留挂载，重新激活读取最新事实，不重置本地表单 |
| frontend/src/workbench.js | 纯状态转换与可见性函数；只改变工具页、布局和手机视面，不操作正式数据或业务草案 |
| frontend/src/styles.css | 带v2-shell作用域的四区、三态和手机样式；展开给日历主要宽度，普通周视图局部横向滚动，页面本身不横溢 |
| frontend/tests/workbench.test.js | 扩展现有文件：导航/页签唯一性、三态与会话偏好、手机单视面、非法动作保护、SSR语义/禁用入口及hidden/inert |

未新建features/state/workspace目录或引入状态/UI/日历依赖。WorkspaceChat和ChatMessages源码原样复用；不将review/profile旧聊天嵌入右侧。旧版入口通过 `?layout=legacy` 在新标签页打开，原工作台的未提交编辑留在原页；旧版可返回新工作台。无schema变化，代码回退无需恢复数据库。

### 11.2 状态与交互

- 首版首页以聊天为主、右侧今日；首版导航/页签共用工具页的行为已由第11.5节替代，现为主体与辅助栏独立选择。
- 会话栏独立收起；展开工作区临时隐藏会话栏，恢复普通布局时恢复先前偏好。工作区收起/普通/展开不改变页签、日期、日历显示或未提交表单。
- 1A只显示实际当前规划会话。新建/搜索禁用并说明尚未开放，不伪造历史列表、搜索结果、登录、置顶或归档能力。
- 选中工具页和布局由App负责；日期/日历显示、规划输入/手动表单由原AssistantPage保留；复盘筛选、档案表单等由各自页面保留。已访问页面不因切页/隐藏卸载，保留滚动与details展开状态；重新读取服务端事实不覆盖编辑缓冲。
- 手机在会话/聊天/工作区之间切换，底部导航仍可用。hidden与inert共同阻止隐藏内容参与交互；页签支持方向键/Home/End，工作区收起/恢复及视口变窄时把焦点移回可见入口。手动编辑任务会切回手机聊天面。
- 未来身份归属使用服务端workspace/owner；当前沿用既有workspace_id+规划周会话键，未新增可信客户端owner字段或数据表。切身份/恢复数据库后的编辑隔离及baseVersion协调留给1B及后续，不声称已实现多用户隔离。

首版阶段1A保留的是当前页面生命周期内的状态，当时刷新后的未提交表单/日期/布局恢复尚未实现；这是历史快照。现行真实会话与刷新恢复范围以12.2为准，未提交编辑不承诺跨设备或长期本地持久化。

### 11.3 首版ad586df验证与边界

前端实际运行 `npm.cmd --prefix frontend test`：96通过、0失败、0跳过（原89项+新增7项）；既有SVG title复合children的React警告仍在。`npm.cmd --prefix frontend run build`通过：Vite7.3.6、60 modules、JS355.33kB/CSS70.07kB。状态测试在现有workbench.test.js中扩展，不能用SSR冒充真实DOM验收。

实际浏览器使用已安装Edge headless、新浏览器上下文、匿名Mock后端：既有 `scripts/integration_demo.py --serve --port 8181` 每次创建全新demo DB；额外设置独立临时SGA_BACKUP_DIR，关闭自动备份/真实AI。Vite使用 `VITE_API_BASE_URL=http://127.0.0.1:8181`、端口5187（既有CORS允许）。没有启动默认app.db应用、付费AI或运行写报告的验收CLI；截图只在内存检查，没有新增截图/日志/脚本。

| 浏览器检查 | 实际结果 |
|---|---|
| 1440×1000普通布局 | 会话192px、聊天约639px、工作区约533px，聊天主体；首次今天 |
| 1280×900普通布局 | 会话192px、聊天552px、工作区460px；无页面横向溢出 |
| 1440展开 | 会话临时隐藏、聊天280px、工作区1084px；周日历七列在工作区内完整展示 |
| 390×844手机 | 会话/聊天/工作区每次只显示一面；底部主导航可达，页面无横向溢出 |
| 状态保留 | 会话栏收起/恢复、工作区三态、三个页签和导航往返后，输入、手动任务名称、所选日期/日历显示、目标和偏好未提交内容保留；重新激活读事实后仍保留 |
| 键盘 | 页签方向键/Home/End、收起后焦点返回、45次Tab不进入隐藏区；桌面输入聚焦后缩至390时转到可见手机入口 |
| 旧版 | 规划、复盘、档案及其旧聊天均可访问；新工作台只挂一个中央聊天 |
| 业务安全 | 导航/布局操作没有追加会话或业务写入；匿名手动生成候选→查看调整可用，未点采用时正式tasks仍为空；无浏览器pageerror |

桌面检查另用了America/Los_Angeles浏览器时区。以上为真实浏览器引擎验证，未覆盖实体手机软键盘、Safari/Firefox或触摸设备；不宣称全设备验收。后端业务、迁移、API与依赖未修改，不重复运行689项后端测试；正式数据库及产品原文已再次核对SHA256，与第9节及阶段0.5基线一致。`git diff --check`通过；未改后端服务、迁移、依赖、锁文件或CI。

### 11.4 明确保留的后续工作

1A完成布局和已有规划能力的有限接入，不单独算完整阶段1。统一自由聊天、跨天持久会话、新建/标题/搜索/置顶归档删除、回复文本增量、刷新编辑恢复与完整业务卡片适配在1B继续；复盘仍是旧周复盘正文，未冒充产品目标中的日周月回顾与确认复盘记录；完整日周月年日历在2B，当前单日只是原周日历的过滤。账号区仅预留。没有自动创建正式任务、确认草案或扩大排程范围。

本轮可在验证通过后将1A源码、测试及本文更新单独本地提交，不push/merge/创建PR；完成1A后停止，等待审核。

### 11.5 a53a68b交互补丁快照：主体导航与独立辅助栏

本补丁来自用户在 `ad586df` 后新确认的需求修订，属于1A范围内交互纠正，未进入1B。开始时实际HEAD为 `ad586df0dff309911bf95aa01afb008c46209398`、分支feat/v2-workspace-redesign、工作区和暂存区均干净。

原关联：左导航、右侧页签和打开工具回调都发出open动作，共写state.page，只改变右侧内容。现拆为navigation（左侧主体）与auxiliaryPage（右侧辅助页签），navigate与auxiliary动作互不改写对方选择。首页panel与工具页toolPanel分开，返回首页恢复原辅助栏、会话和宽度偏好；点击左导航工具页默认折叠不必要辅助栏。

只修改已有文件，没有新增文件：
- App.jsx编排独立页面/辅助意图，沿用原版本刷新及业务回调；只持久保存设备宽度比例。
- WorkspaceShell.jsx保留每类工具唯一挂载位置节点，以CSS Grid在主体/辅助位置间排列，不重建表单、移动React子树或复制业务数据；同类冲突显示主体引用。聊天始终保留挂载，非首页隐藏。处理分隔线Pointer Capture、取消拖动、键盘调整及焦点回收。
- workbench.js定义独立状态动作、工具位置和宽度边界函数；移动端沿用单视面，辅助切换不改变主体。
- styles.css调整主体/辅助网格及分隔线；原日程/复盘/档案正文继续复用。AssistantPage.jsx仅增加主体日历首次进入周显示，日期及后续用户选择保留，原请求/排程/确认流程未改。
- workbench.test.js扩展现有状态/SSR测试：主体与辅助双向独立、主体全宽、首页偏好恢复、单实例、手机可见性、宽度限制/复位/存储容错及可访问分隔线。

宽度偏好使用localStorage的sga-v2-home-split-ratio，仅存数字；有效范围和360/320px最小尺寸在纯函数中统一。存储失败时本次页面内调整仍可用。收起/展开、移入主体、调整比例均不清空输入/日期/编辑；刷新后的业务编辑恢复仍属于原1B待办，不因为保存宽度而声称业务草稿已持久化。

补丁验证使用全新匿名Mock服务8183、Vite5187以及独立临时备份目录，未打开正式数据库应用、未发送付费AI请求、未确认正式任务。真实Edge浏览器已验证：
- 1440×1000首页主体/辅助独立；左导航日程主体宽1320px，中央聊天与会话栏隐藏，完整七列周日历可见。
- 1280×900主体日程宽1160px，周网格在主体内完整展示，无页面横向溢出。
- 390×844保留会话/主体/辅助单视面；移动端辅助切档案不改变左侧日程；隐藏分隔线，35次Tab没有进入隐藏内容。
- 鼠标拖动首页聊天由约675px增至799px，键盘Home/End限制尺寸，辅助栏下限320px；取消拖动恢复原比例。恢复默认、收起/恢复、展开/普通、窗口变化及刷新恢复宽度偏好均通过；1024px断点仍满足360/320px且不横溢。
- 聊天输入、手动任务名称、日历日期、目标与偏好未提交编辑、档案200px滚动位置在切页/换位置/调宽后保留；档案DOM实例身份未变，没有第二份表单。
- 页面导航及尺寸操作没有产生额外会话/业务写入，匿名正式tasks仍为空，无浏览器pageerror。原旧版入口仍保留。

当前前端测试103通过/0失败/0跳过；生产构建通过（Vite7.3.6、60 modules、JS359.60kB/CSS71.55kB），scripts/check_repository.py及git diff --check通过。原SVG title的React警告仍在。正式数据库开始时被进程占用，未停止该进程；随后用只读共享文件句柄计算SHA256，与第9节原基线一致，产品原文SHA256也未变化。未改后端、数据库、迁移、API、依赖或锁文件，未生成新报告、截图文件或配置。

本补丁只创建独立本地提交，不push/merge/创建PR，完成后停止等待审核。

### 11.6 04f8017历史快照：四主体共用辅助栏交互

本次是用户在a53a68b后进一步明确的产品要求，仍限1A，不进入1B。开始时实际HEAD为 `a53a68ba8ff50ec8e5bac667f5e5ca0028bd970c`，分支feat/v2-workspace-redesign，工作区及暂存区干净。

现将原首页panel/工具页toolPanel合为一个panel；navigate只选主体/手机主体视面，不改auxiliaryPage、panel、splitRatio或会话栏偏好。所有主体使用同一WorkspaceShell、辅助页签、分隔线及比例变量，删除非首页固定列宽规则和仅首页可调宽限制。展开、收起/恢复、键盘调宽、取消拖动、默认宽度和持久偏好在四页一致。宽度仍复用旧sga-v2-home-split-ratio键以兼容已保存设置；键名不代表首页专属。35%等偏好跨页不改写；视口不足时按360/320px最小尺寸约束实际比例，保留原偏好。刷新恢复安全有效的宽度，非法值回默认。

以下为04f8017当时的实现与验证证据，其中同步日期/视图、异类完整辅助页面及未提交表单提示已由11.7取代，不作为现行规则：

同类内容当时同时展示，取消旧“已在主体显示”的替代占位：
- AssistantPage仍是唯一会话/正式安排/草案控制器。主辅Calendar共用同一data、proposal、日期及视图setter，副日历不发请求；独立事件详情使用useId避免重复DOM ID。拆解、执行与方案确认仅保留原一套。
- ReviewPage与MyProfilePage各自只挂一个完整页面/编辑器，通过既有ReactDOM Portal把只读内容投射到共用辅助容器，不再挂第二个业务页面。复盘读同一已保存周说明和版本；档案读同一goals/rules及未提交表单提示。数据保存后由原load刷新，两处同源显示，没有第二份可变事实、表单版本或额外统计/课程加载器。
- 辅助页签与主体不同类时，继续使用原完整页面。所有完整页面保留挂载与原编辑状态，主辅相同类时保留一个编辑缓冲，辅助视图提供“在主体编辑”入口。只读摘要是明确的显示范围，不宣称复制了完整编辑功能。
- Portal不增加接口、轮询或AI调用；三态及隐藏区域仍以hidden/inert与焦点回收控制，手机不显示分隔线且保持会话/主体/辅助单视面。

只修改现有文件：App.jsx、WorkspaceShell.jsx、workbench.js、styles.css、WorkbenchLayout.jsx（转交副日历插槽）、AssistantPage.jsx（共享日历投影）、GoalsGrowthPage.jsx/MyProfilePage.jsx（同源只读投影）、workbench.test.js和本文。未新增组件、目录、依赖、配置、脚本或报告。刷新后的业务编辑恢复仍不在本补丁范围；保存宽度不代表业务草稿已经长期持久化。

实际验证使用新匿名Mock库（8185）、Vite5187及独立备份目录，禁用真实模型网络；在匿名库显式准备目标/偏好和未确认日程候选，正式用户库没有启动或写入。Edge headless真实浏览器结果：
- 1440×1000四页分别鼠标拖动及键盘调宽通过；35%偏好跨四页一致，恢复默认不改变页签。
- 四页分别收起/恢复、展开/普通并跨页验证：模式与宽度均未重置。日程主动收起辅助栏后主体由约786px扩大到1320px，再恢复保留日期。
- 1280与1440下四页均可拖动且页面不横溢；390×844四页均为单视面，辅助页签不改主体，分隔线隐藏，40次Tab未进入隐藏内容。
- 同类档案同时显示已保存匿名目标/偏好、未提交目标/偏好提示，完整goal-editor仅一份；同类复盘只有一份GrowthAnalytics。主辅日历双向改日期同步、显示同一未确认候选，正式tasks仍为空。
- 聊天输入、手动任务名称、日期、未提交目标/偏好、档案180px滚动及原DOM实例身份保留。页面初始读取稳定后，逐页拖动/键盘调宽没有任何API请求，布局/导航没有业务保存；同类投影与收起恢复不新增profile/review context请求。
- 刷新恢复同一宽度偏好，损坏值回默认。未测实体手机软键盘/触摸及其他浏览器，截图仅在内存查看，没有保存副本。

本轮前端105项测试通过/0失败/0跳过，涵盖共享模式/比例跨页不重置、四页分隔线、同类共享视图与保留完整编辑实例、存储和边界；生产构建通过（Vite7.3.6、61 modules、JS362.27kB/CSS71.83kB），scripts/check_repository.py及git diff --check通过；原SVG title的React警告仍在。后端、排程、迁移、API与依赖均未改；产品原文保持原样。正式app.db与产品原文已只读复核SHA256，分别与第9节/阶段0.5基线一致；没有终止其他运行进程。

验证完成后仅创建一个本地提交，不push/merge/创建PR，停止等待审核。

### 11.7 阶段1A最终交互修订：完整主体与极简辅助预览独立

本轮基于 `04f8017836e402a254ccd390c76bd83884d09e42`，分支feat/v2-workspace-redesign，开始时暂存区及工作区干净。用户最终确认本节规则，属于1A小范围修正，不进入1B，产品原文保持原样。

```text
左导航 → 中央：首页聊天 / 完整日程 / 完整复盘 / 完整档案  [统一日期时间]
                     ⇔ 共用分隔线（桌面）
右页签 → 辅助：单日日程 / 本周回顾摘要 / 已保存档案摘要
                ↓ 仅预览；独立日期/范围/展示状态
共用正式后端事实 ← 原控制器和正常保存后刷新 → 中央完整功能
```

回退原因是toolPlacement把异类完整页面移至辅助位置，而同类副日历共用了主体calendarView和selectedDate setter。现完整页面只留中央原DOM实例，辅助容器始终展示预览，不再由主辅是否同类决定显示完整工具。AssistantPage增加独立previewDate，始终传selectedDate给原Calendar单日分支；formalOnly读取同一data.courses/confirmed_items，不叠候选事件，待确认仅提示。原主体周日历、草案及业务确认逻辑不变。

ReviewPage复用GrowthAnalytics既有统计响应中的overview（当前周，与主体4/8/12周趋势范围独立），没有第二次统计请求；只显示完成数、投入与有效反馈，未知耗时沿用原口径，不编造待反馈数量。MyProfilePage从同一正式goals/rules展示最多三项及剩余数量，不渲染表单、未提交字段或主体编辑错误。Portal复用一个辅助容器，不新增业务控制器。隐藏完整页面、聊天和日程预览保留挂载，辅助页签不控制主体功能。

WorkspaceApp保留原首页时间格式和北京时间，用一次settings读取建立时间锚与单个按分钟调度的时钟，四个主体页头传同一clock。只替换中央工具页头的辅助栏按钮，右侧恢复默认宽度/展开/收起、收起后的恢复入口、桌面拖动与键盘调宽均保留。辅助栏页签/panel/splitRatio继续四页共享，导航不重置；手机单视面及hidden/inert焦点回收继续沿用。刷新仅恢复已实现的宽度偏好，不声称恢复未提交业务表单。

本轮只改现有App.jsx、WorkspaceShell.jsx、workbench.js、styles.css、AssistantPage.jsx、GoalsGrowthPage.jsx、GrowthAnalytics.jsx、MyProfilePage.jsx、workbench.test.js及本文；不新增源码/报告、依赖或后端能力。统计刷新保留同范围已加载DOM，以免切回主体刷新时丢失details展开项和滚动位置，后台读取失败仍显示错误。

本轮实际验证：

- 新建匿名Mock数据库（8018）与独立备份目录，Vite5187；先核实X-SGA-Integration-Mock标记，再显式准备匿名正式课程/任务、已完成反馈、目标/偏好及未确认候选。真实模型被脚本禁止，正式用户库未启动或写入。
- Edge headless真实浏览器在1440×1000、1280×1000逐页验证：右侧始终一个day-column，无周切换/横向周表；主体保留七列周表。左右日期双向互不影响，右侧上一天/下一天/回今天可用。右侧仅显示正式课程/任务，候选只提示；正式任务列表前后相同。
- 左右页签双向独立；主体统计范围4→12周，右侧固定本周摘要（匿名夹具1项完成、25分钟、1条有效反馈）；档案只读已保存目标/偏好，不显示未提交字段。展开/收起跨四主体保留，拖动确有比例变化，键盘方向/Home/End/Enter、恢复默认及刷新恢复宽度均通过；拖动不产生API请求，布局/导航不写业务数据。
- 保留聊天输入、手动任务名称、未提交目标/偏好、主体日期、统计范围、details展开项、档案180px滚动、原DOM身份及服务端未确认草案。统一时钟四处相同，浏览器推进61秒由18:00变18:01，无API读取或轮询。
- 390×844四主体/辅助页签均保持单视面，无分隔线和页面横溢；40次Tab未进入隐藏/inert区域。旧版入口仍可进入档案。另查看1280日程、390单日与复盘摘要的实际截图，截图仅在内存检查。未测实体手机软键盘/触摸及其他浏览器。
- 前端109项测试通过，0失败/跳过；生产构建通过（Vite7.3.6、61 modules、JS363.26kB/CSS72.79kB）。scripts/check_repository.py验证196个文件/本地链接/CI语法，git diff --check通过；原有SVG title React警告仍在。后端、数据库迁移、排程、API、CI、依赖/锁文件与产品原文均未修改；正式数据库及产品原文的只读SHA256与本轮开始值一致。

完成后只创建本轮本地提交，停止等待审核，不push/merge/创建PR，不进入1B。

## 12. 阶段1B：真实会话后端与后续边界

### 12.1 本批1B-1A实际实现

起始分支feat/v2-workspace-redesign，HEAD为 `41bf8b89110190498d5bb526716b3d42dc9ada21`，工作区与暂存区干净。本批只做后端，阶段1A的中央完整主体、独立极简辅助预览、左右UI状态独立和正式数据同源规则不变，前端源码没有修改。

**存储与归属**：扩展原AssistantSession/AssistantMessage，不另存聊天正文，不新增业务表。新scope=conversation，week_start=NULL，可跨天/跨周持续写入用户消息；旧planning/review/profile/task_breakdown的scope/周或兼容哨兵周保留。会话增加title/title_source、client_request_id、version、owner_id、updated_at/last_activity_at、pinned_at/archived_at/deleted_at；消息增加owner_id和可空created_at。历史正文、ID、proposal/draft/plan引用保留，历史消息created_at及旧会话last_activity_at/updated_at保持NULL，不伪造发生时间；历史列表只用既有created_at作排序回退。新消息保存时同事务更新活动时间，手动改名/置顶不冒充聊天活动。

WorkspaceMetadata新增稳定的本地owner_id映射。会话owner由服务器读取该映射，消息继承父会话owner；列表、搜索、详情、写入都按当前本地owner过滤，客户端不能通过body指定user_id/owner_id/scope/角色/时间。owner是未来迁移到真实身份的准备，不是登录身份；未实现认证、全业务授权或多用户隔离，原单例业务表不在本批大改。

| 实际API | 契约 |
|---|---|
| POST /api/conversations | 必填client_request_id，可选title；默认“新对话”，显式title标manual。按owner+请求标识幂等，重试返回原会话的当前元数据，改名后不被重试覆盖；同一标识不能再创建另一个会话 |
| GET /api/conversations | scope默认conversation，可选planning/review/profile/task_breakdown/all；archive=active/archived/all，无q默认active，有q默认all。置顶优先，再按活动时间（历史缺失则created_at）及id降序；limit=1–100、offset=0–10000，返回items/next_offset |
| GET /api/conversations?q=… | 标题或正文的字面子串搜索，q去空白后1–100字符；不解释%/_为通配符。每会话最多3条纯文本snippet及原message_id/session_id，另有more_message_matches；归档会话可查，已删除不参与 |
| GET /api/conversations/{id} | 返回会话元数据，正文走独立分页接口；归档可读，删除返回410 |
| PATCH /api/conversations/{id} | 必填expected_version；可改title/pinned/archived，未给字段保持原值；成功版本+1。手动title标manual，内部automatic_title契约使用SQL版本条件且永不覆盖manual；本批不调用AI生成标题 |
| DELETE /api/conversations/{id}?expected_version=N | 逻辑删除，不物理抹除正文；返回deleted_at/version/deletion_mode=soft及明确保留说明。同一删除重试返回原结果，不复活、不连带删除正式事实 |
| GET /api/conversations/{id}/messages | 按不可变id排序；limit=1–100，after_id前向或before_id后向，二者互斥，输出均按id升序，返回下一游标/has_more；可加q查完整匹配消息。旧消息时间未知仍能稳定分页 |
| POST /api/conversations/{id}/messages | 仅对conversation scope持久保存user文本，必填client_message_id/text（1–2000字符），同标识同内容幂等，不同内容409。没有AI回复、工具执行或自动任务；旧工具会话仍用原业务接口 |

列表/搜索为有界offset分页且有确定的次序，并非跨并发修改的冻结快照；后续前端应按id合并/去重。消息使用id游标，等时间戳、追加消息及历史NULL时间不影响顺序。搜索只返回纯文本，前端不得当HTML插入。新建和消息幂等、修改/删除版本冲突均在SQLite写事务内处理；会话元数据/纯文本保存不递增业务PlanningState revision、不使正式业务草案无故失效。

**生命周期**：归档或删除遇到running请求，返回409 CONVERSATION_BUSY；任何非applied/discarded/superseded的规划或业务草案（包括stale）返回409 CONVERSATION_HAS_DRAFTS，保留原状态，须用户通过原入口明确处理。归档后新正文/旧业务执行被拒绝，恢复后才能继续。软删除后新旧入口返回410，正文及receipt仍在本地/整库备份；本批没有物理清除或自动到期策略，不将“删除”宣称为隐私数据彻底销毁。正式Task/Plan/Feedback/Goal/Review及独立资料均不级联删除。旧open/拆解入口跳过归档和已删除会话，不复用墓碑。

错误语义包括404 CONVERSATION_NOT_FOUND、410 CONVERSATION_DELETED、409 CONVERSATION_ARCHIVED/CONVERSATION_VERSION_CONFLICT/IDEMPOTENCY_CONFLICT及上述运行/草案冲突；非法字段/范围为422，未初始化工作区为503。旧planning消息、候选确认及运行重试继续验证scope和当前规划周；新会话不能经旧API绕过周限制。

**迁移与恢复**：仅新增0003_conversations，不修改0001/0002或baseline_models。为了使旧week_start可空，SQLite会话表以原ID复制重建；Alembic连接在事务外临时关闭FK执行检查，用显式BEGIN IMMEDIATE覆盖DDL/数据/版本表，提交前PRAGMA foreign_key_check，失败则整体回滚，finally恢复FK=ON；仅该升级连接受影响。已有升级前在线备份继续保留，禁止破坏性downgrade。空库/已有v1-v2库和无版本兼容库均走同一升级链，已到head重复启动不重建。

JSON导出为v3，仍严格要求完整26张业务表及当前列；v1先按冻结baseline校验并补任务层级列成v2，v2按冻结baseline+0002三列校验，再显式补本地owner、标题和可空时间等v3字段。旧v1/v2恢复只允许目标没有升级后会话/元数据/消息的情况；目标存在新会话、编辑过的元数据、新消息或删除墓碑时，409 LEGACY_RESTORE_CONVERSATIONS_PRESENT，在任何DELETE前拒绝。不得静默丢弃新数据或自动合并冲突ID；用户应先导出v3，在独立空库恢复旧备份。v3恢复校验消息owner与父会话一致，整事务保留已有恢复的revision递增、待确认草案stale及running interrupted规则。

实际新增文件仅0003迁移、conversations路由/服务及test_conversations.py；其余适度修改models/assistant_schemas、main注册及DELETE CORS、旧assistant/task_breakdown生命周期入口、Alembic env/schema_migrations、growth_data、原迁移/导出/拆解测试和本文。没有新依赖、前端接入、UI布局重构、报告或私人配置修改。

本批最终验证（独立于阶段0的689项旧证据）：

- 在backend目录执行app_env Python3.11的完整pytest tests，**734通过、0失败、0跳过**，89.83秒；仅原Starlette TestClient/httpx弃用警告。覆盖会话CRUD、跨天/跨周、活动排序、标题保护、字面搜索/片段/归档、双向消息分页、幂等/版本冲突、运行与草案阻断、正式数据保留、旧API/当前周确认及重试限制、服务端owner过滤、旧JSON转换/保护与v3恢复。
- 迁移专项验证真实0002库升级、v1匿名fixture升级、空库与重复升级；保留原session/message/proposal/task/plan/feedback ID和引用，历史消息时间NULL。注入最后一个索引DDL失败，验证列、原数据、Alembic版本均回滚且无残留临时表，FK恢复ON，之后可正常重试。
- 迁移CLI在全新匿名临时路径连续两次运行scripts/migrate.py成功；head=0003_conversations，26业务表，integrity_check=ok、foreign_key_check为空、foreign_keys=1、tasks=0。
- 所有测试库、启动bootstrap路径及备份都显式指向匿名临时目录；conftest覆写get_db/engine、禁.env与真实模型。初次沙箱临时目录权限导致setup失败，改正常隔离临时路径；首次从仓库根目录全量运行723通过/2子进程导入失败，改在backend执行后消除，未把这些尝试记作通过。
- scripts/check_repository.py通过（200文件、本地链接及CI语法），git diff --check通过。没有前端、依赖/锁文件、CI、0001/0002或冻结baseline变更；产品原文SHA256仍为69F03B739C66F58572960967247948D5574784B56F52ADA60359FEECB09BC020，正式app.db只读共享句柄SHA256仍为0DB97D1D9760B66C414F9E17C8C0369ECFC1D6DDDD0050972E18D68F3FC439CB。没有对正式库执行迁移/测试/启动，没有读取或修改.env及私人备份，未调用付费AI。

本批可供1B-1B审核接入后端。前端仍未接真实会话列表/消息API；下一批需处理当前会话切换、分页/归档删除提示、版本冲突及刷新编辑恢复，尊重旧scope专用写入口。统一AI自由聊、流式回复、完整工具、登录隔离和新日历/复盘/记忆继续等待各自授权。仅本地提交后停止，不push/merge/rebase/reset/创建PR，不进入1B-1B或1B-2。

### 12.2 本批1B-1B：真实会话前端与刷新编辑恢复

起始分支 `feat/v2-workspace-redesign`，HEAD为 `8691fb5399b4f8b5824fd1eca0ce83b72dec1073`，工作区与暂存区干净。本批只扩展前端及本文，不改后端、Alembic、JSON格式、排程、依赖或产品原文，不进入1B-2。12.1末尾“前端尚未接入”为该批交付时的历史状态，现由本节更新。

**会话管理与旧入口边界**：现有会话栏改用12.1真实API，保持置顶、最近、归档和标题/正文搜索结构，不增加文件夹。支持新建、打开历史、手动改名、置顶/取消、归档/恢复、删除确认与列表刷新；使用服务端活动排序及30条列表分页，按ID去重。搜索读取纯文本snippet和原message_id，点击定位原消息；消息30条一页，可向前/向后加载并按不可变ID合并。

api.js增加列表、新建、详情、PATCH、DELETE、分页消息及用户消息保存封装。PATCH/DELETE带expected_version；新建client_request_id和发送client_message_id在失败重试及刷新中保留，成功后仅清理对应标识。版本冲突保留用户改名输入，刷新元数据后可显式重试；运行中/未处理草案的409显示中文原因，不自动取消请求、放弃草案或采用候选。删除前说明软删除及正文/整库备份保留范围，正式任务、日程、目标和反馈不受影响。

普通会话仅向 `/api/conversations/{id}/messages` 保存用户消息，明确显示“已保存；AI回复尚未接入”，不伪造回答，不向旧规划scope发送。历史工具会话在列表中标记只读；“本周规划入口”继续使用原AssistantPage、草案/确认和当前周限制。当前选择归档时保持打开并禁止发送；删除/不存在返回410/404时保持选择并显示原因，不静默新建替代。切换普通会话按workspace和真实ID挂载，generation gate与卸载检查阻断迟到读取/响应写入新会话；不改变后台运行。离开规划聊天停止观察轮询，返回后重新读取服务端继续观察，没有自动cancel。

**刷新恢复与数据保护**：使用小型useEditRecovery，不引入状态库。缓存key为sessionStorage中的 `sga-edit-v1:[workspace,resource]`，payload含schema、base与明确列出的编辑字段；不缓存API Key、凭证或整份后端响应。先成功读取工作区及相关服务端资源，再校验缓存结构和base。缓存读取/写入失败如实提示刷新恢复限制，基本输入和消息保存仍可用；旧格式、损坏内容保留，不静默覆盖。移除/保存只处理当前资源key，不清空其他会话或表单。

| 当前恢复范围 | 策略与边界 |
|---|---|
| 当前会话、普通会话输入 | workspace+真实会话ID隔离；先读详情/分页后自动填回输入。正文输入不绑定易变化的会话元数据version，归档/删除仍受服务端状态约束；保留消息幂等ID |
| 旧规划聊天输入、手动任务编辑 | workspace+规划会话ID隔离；输入可自动填回。手动任务先比较当前tasks/proposal快照，人工确认后填编辑器，不能自动提交 |
| 正式任务表单、任务编辑/反馈选择 | 任务ID/新增子任务父ID独立key；比较当前任务或任务列表快照，人工恢复。成功保存仅移除本表单缓存；不恢复或自动启动计时器 |
| 目标、偏好、类别编辑 | 比较服务端goals/rules/categories快照，人工确认。无可靠独立版本，快照不同只展示旧JSON供对照，不直接覆盖或宣称安全合并 |
| 拆解输入、选择及未保存草案内容 | 选择从服务端草案列表核实；内容base含草案id/version/source_revision/status。恢复内容需人工确认，并暂停原自动保存，直到用户显式保存/确认；无效编辑也能保留 |
| 主/辅日历日期、日/周显示、导航/辅助页签及三态 | 服务端工作区/规划周读取后校验并恢复；主辅日期独立且限当前已支持窗口。宽度继续使用原有安全localStorage偏好，不受会话切换影响 |

服务端base变化时不提供“恢复到编辑器”，旧内容仅作对照；不自动提交、确认或改正式事实。没有可靠版本的旧表单采用快照比较加人工确认，不能替代后端并发控制。编辑发生在当前页面后再有服务端变化时，缓存仍保留编辑起点base。只覆盖新工作台上述编辑；旧版专用聊天、课程/保护时间编辑等未作全面刷新恢复升级，复盘筛选/details/滚动仍只承诺当前挂载周期保留。sessionStorage通常仅限当前标签页和浏览器会话，不承诺跨设备、关闭浏览器后或存储配额耗尽时恢复。

布局仍是四个完整主体和共用独立极简辅助栏，右侧单日日程不会变周表，右侧复盘/档案只读；左右UI独立、正式数据同源，统一北京时间、拖动/键盘调宽、展开/收起/复位和旧版入口保留。新增仅ConversationManager.jsx（真实会话及消息职责）、EditRecovery.jsx（共享缓存恢复）和conversations.test.js；其余复用App、WorkspaceShell、AssistantPage、TaskForm/TasksPage、TaskBreakdown、MyProfilePage、api/workbench/localization、CSS及现有测试。

本批实际验证：

- `npm.cmd --prefix frontend test`：**121通过、0失败、0跳过**。覆盖真实API参数/版本/分页与中文错误、迟到响应gate、消息合并、workspace/会话/资源隔离、损坏/旧缓存/存储失败、可选字段序列化及布局恢复；保留原有布局/业务测试。既有SVG title复合children的React警告仍在。
- `npm.cmd --prefix frontend run build`通过：Vite7.3.6、63 modules、JS383.33kB/CSS74.50kB。没有把构建当成浏览器验收，也没有将上一批734项后端测试作为本轮结果；本批未重跑完整后端回归。
- Edge headless真实浏览器，使用integration_demo新建匿名数据库、独立临时备份目录、8019端口及Vite5187，先核实 `X-SGA-Integration-Mock:1`。API准备匿名夹具、页面故障使用Mock；禁真实AI，未启动默认正式库。
- 真实列表超过30项分页、65条正文分页及第45条搜索定位；新建/改名/置顶取消/归档恢复/软删除均成功。实际版本冲突保留输入重试；A响应延迟900ms切B不混入；A/B输入独立并可刷新恢复。丢失已保存消息响应后刷新，以原client_message_id重试仍只一条；不存在选择保持404且没有替代新建。
- 真实旧规划未处理候选阻止归档/删除且草案不变；运行中409采用浏览器Mock核验提示。Mock运行观察离开停止、返回恢复，零cancel请求；历史工具只读，普通会话没有调用旧规划消息或AI run接口。
- 规划输入、手动任务、正式任务表单及选择、目标/偏好、页面/辅助页签/比例和独立日期刷新恢复。7分钟无效子任务编辑恢复后等待1.5秒无自动PATCH；真实服务端目标修改后本地编辑仅供对照。禁用Storage get/set/remove后仍可编辑/保存消息并显示限制；损坏缓存及其他资源key保持，浏览器无pageerror。
- 1440/1280桌面四主体逐页验证拖动、键盘、展开、收起恢复、同一时钟、单列辅助日程及输入保留；调宽没有API请求。390手机四主体/辅助保持单视面，无拖动分隔线，40次Tab未进入hidden/inert区域；查看实际截图但不写截图副本。未验实体手机软键盘/触摸或其他浏览器。
- scripts/check_repository.py通过（203文件、本地Markdown链接及CI语法），git diff --check通过。后端、迁移、CI、依赖/锁文件未改变；正式app.db和产品原文的只读SHA256分别仍为0DB97D1D9760B66C414F9E17C8C0369ECFC1D6DDDD0050972E18D68F3FC439CB和69F03B739C66F58572960967247948D5574784B56F52ADA60359FEECB09BC020，与开始值一致；未读取/修改.env或私人备份。

统一AI自由聊、自动回复、流式、工具调用、自动标题、登录/完整权限仍未接入，待1B-2及后续授权。当前本地workspace只是缓存归属，不是认证身份。完成本批后停止审核，不自动进入1B-2。

### 12.3 后续批次前提（尚未实施）

1B允许必要后端演进，不以“后端完全不改”推迟产品必需会话能力：
1. 会话存储、元数据API、owner准备与JSONv3由12.1实现；接入前端前固定这些实际契约。run增量/统一AI消息属于后续授权，不改冻结迁移。
2. 真实会话前端和指定编辑恢复已由12.2接入；1B-2不能把现有规划助手换个scope就当自由聊天。自动标题只走受保护的内部契约，正文中的业务引用/独立记忆范围需后续设计。
3. 接单一自由聊天、回复增量/阶段状态/停止重试/receipt，无用户选模式；无Key如实提示且手动业务可用，复杂工具在2A完善。
4. api.js及原assistant服务最小扩展，统一useAssistantRun/查询失效；提取AssistantPage日历/策略/ScopedChanges，复用TaskForm/Hierarchy/Breakdown/执行；分离Review/Profile正文与旧WorkspaceChat，保留旧包装回退。
5. 旧周日历过渡，四视图/范围/回顾记录独立到2B，小结/记忆/全面手机验收在3。首批新增模型预留owner，不提前实现完整账号。

1B整体验收：真实会话/无模式跨天自由聊/回复增量、搜索恢复和删除范围、各入口同工作区、切页刷新不丢；匿名Mock目标→拆解审核→父子确认→局部排程/冲突→采用→反馈→统计/目标刷新可用；未确认不改正式事实。历史回归加新行为测试、旧API/JSON兼容均通过，89/689仅是旧基线数量，不预定后续通过数。
必要测试：跨周续聊与旧确认限制并存、手动标题保护、搜索片段/归档恢复/删除、增量断线去重/取消receipt、迟到响应、无Key输入、draft双端编辑/无效dirty/409、重复确认响应丢失、新旧JSON与归属、上海午夜/分段去重；2A补完整工具和dirty协调。浏览器用新匿名库，业务测试Mock AI，不以真实付费API换通过。
回退按模型/转换、API、聊天及各业务适配独立提交，涉及schema先独立备份/恢复演练，旧应用读兼容须证明。阶段2前固定范围/事实与草案版本契约，4前完成全链路权限设计，5前完成隔离/灾备/额度验收。

本主文档保留阶段0关键证据、技术决策、原型及1–5阶段边界；未来继续更新本文。本批1B-1B完成后停止，等待审核，不自动进入1B-2。

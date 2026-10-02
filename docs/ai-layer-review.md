# Phase 7A + Phase 7B AI Layer 独立代码审核

日期：2026-10-01，Asia/Shanghai。结论：**PASS WITH FIXES**。

审核当前未提交工作区中的既有实现；没有将所有既有 Git diff 当作本轮改动。只修复现有 AI Layer，没有 Phase 8、新产品能力、自动 retry、延长 timeout、commit 或 push。

## 新发现与最小修复

1. Provider BASE_URL 若以 `/v1` 或 `/v1/` 结束，原代码会请求 `/v1/v1/messages`。新增 4 个 URL 形态测试，其中两个在修复前失败；客户端规范化末尾 `/v1` 后统一拼接。原 origin 配置行为保持不变，无 env 名称迁移。
2. 7B 原有 guard 会放过明确的 “You should definitely accept this candidate.” 和 “Task #2 was deleted from the database.” 等文本。6 个新 endpoint 用例修复前均错误返回 available。补充狭窄的中英文确认压力/肯定式删除断言拦截，降级为 HTTP 200、完整 diff、explanation=null/unavailable；另测试 “was not deleted” 正常保留。不是通用语义验证器。
3. 真实 smoke 的 A/B 引用 UTC 时间却省略时区，而同一区域 Changes 的钟点是上海时间，存在 8 小时理解歧义。解释 prompt 明确保留 UTC 并标注；前端 AI Explanation 增加 UTC 说明，Changes 继续使用上海时间。未改 deterministic diff 或时间换算代码。
4. 补足测试证据：五条越权输入在模型故意误分类为合法 proposal 时仍不执行 SQL、不修改五张表；Infinity/-Infinity、仅 start 改动、Protected 非 task 排除、禁止 Session.commit、旧请求晚到 rejection 及关闭后不再发请求。没有把 mock 分类当作真实模型语义证明。

修改的生产代码只有 provider URL 拼接、explanation 的词法 guard/时区 prompt，以及解释区一行时区文案。其余为测试、配置示例和文档。保留 `claude_client.py` / `CLAUDE_*`，准确表述为 Anthropic Messages-compatible gateway with configurable model；本轮实际模型 MiniMax-M3。

## 审核矩阵

| 项目 | 证据 / 结论 |
|---|---|
| Provider shape | `/v1/messages`，顶层 system，仅 user message；model/version 来自配置；600 max_tokens，无 tools；text-only extraction。 |
| Provider errors | 401/403/429/5xx、网络和 timeout → AI_UNAVAILABLE；空 content、missing text、错误类型、非法外层 JSON/过深嵌套 → AI_RESPONSE_INVALID；无配置 → AI_NOT_CONFIGURED。固定安全消息，不返回 raw headers/body。 |
| Timeout/cost | 后端总 deadline 与 HTTP timeout 20 秒，前端 AI 请求 25 秒；无自动重试。显式重试测试检查一次调用一次请求。 |
| 配置与 secret | backend .env lazy loading，process env 优先；key repr=False；frontend 无 provider key 配置；真实 .env、app.db、缓存、node_modules、dist、smoke 报告和本地截图均被 ignore。扫描不输出 secret。 |
| 7A scope | 仅 weekly course、weekly protected、once protected；prompt 禁止 Task create/edit、priority/deadline、移动/删除/确认、规划建议，用户内容只作数据。 |
| 7A 执行边界 | 即使五条指定越权输入获得模型合法 proposal，也只有 JSON 数据返回；测试确认无 SQL、无五表变化。模型不能确认计划/创建 Task/执行工具。分类正确性不等于权限边界。 |
| 7A JSON safety | 完整外层 fence 或纯 JSON；json.loads + unique_object + reject_constant；拒绝自由前缀、duplicate keys、NaN/Infinity、数组、额外顶层/proposal 字段、bool weekday、错误 enum。无 eval/exec/literal_eval fallback/任意 object 提取。 |
| 7A deterministic validation | 复用 TimeRuleCreate，非法 course/recurrence/weekday/date 组合、缺字段、非法标题、end<=start、跨午夜均拒绝，没有第二套业务规则。 |
| 上海当前日期 | `datetime.now(SHANGHAI)`，固定 UTC+08；UTC 9/30 16:30 → 上海 10/1 测试通过；endpoint 允许日期 dependency override。 |
| Parse read-only | 无 get_db/Session/SQL；完整 DB dump + 禁止 SQL/DB dependency 测试覆盖三状态及失败，Task/TimeRule/Plan/PlanItem/PlanningState 不变。 |
| Apply | AI proposal → preview → TimeRuleForm → 用户 Apply → 既有 createTimeRule/POST time-rules；无 constraints/apply。revision +1、旧 Candidate stale 集成通过。 |
| 7A frontend | 开始 Parse 清除旧 proposal；失败无旧 Apply；clarification/unsupported 无 proposal；Discard 清空；手动表单独立。mapping 清 weekly.date/once.weekday，course 固定 weekly。 |
| Pure diff | plan_diff.py 只依赖标准库，既无 ORM/provider 也无 Scheduler；不修改输入。 |
| Identity/四类 | task_id 身份；仅 new→added，仅 old→removed，任一端点变化→moved，两端相同→unchanged；同标题不同 ID 不合并，改标题不等于移动。 |
| removed | 只表示 not included in new candidate，没有任何 Task 删除。UI 标题 Not included in candidate，prompt 明确区分。 |
| Stable ordering | 各列表按规范化时间和 task_id tie-break；反转输入顺序得到相同完整输出；等价 timezone instant 不算移动。 |
| Course/Protected | 所有 kind 非 task 条目排除；不进入四类 Task 变化。 |
| Historical baseline | 读取 candidate.based_on_plan_id；测试 A confirmed→B based_on A→A superseded 后 B 仍比较 A，保留 title_snapshot，不 join 可变 Task 标题。 |
| First plan | null baseline 时所有任务 added，API 返回 deterministic，完全不调 provider；UI 显示 First plan。 |
| Stale | 可解释持久化 snapshot；Confirm 仍返回 STALE_CANDIDATE。UI outdated warning 与 disabled Confirm 不受解释影响。 |
| Prompt/input | 只传 structured diff，不传整个 ORM/数据库 dump、priority/deadline 或可变规则；标题作为不可信数据。禁止最优承诺、确认压力、删除断言、隐藏原因与虚构策略因果。 |
| Hallucination protection | prompt + 有限词法 guard；拒绝已知因果/策略外推、最优性/确认压力/删除断言。不能证明所有自然语言事实正确，diff 才是事实来源。 |
| Failure fallback | AI 三类错误均变为 HTTP 200 diff + unavailable，不冒充 plan invalid；client mock ReadTimeout/503/invalid body 经真实 client 链路到 endpoint 的测试通过。 |
| Business errors | PLAN_NOT_FOUND=404；非 candidate 为 PLAN_NOT_CANDIDATE=409；非法基线 PLAN_BASELINE_INVALID=409，与 provider 故障分开。 |
| 调用时机 | 用户显式 Explain Changes 才 start；Generate 不调 AI；first plan 不调 AI。pending 防重复。 |
| Async race | Candidate ID key + session.close 隔离晚到 success/rejection；新 Candidate 新 state；换周/成功 Confirm 卸载；错误不可污染下一 Candidate。无新全局状态管理。 |
| Explanation read-only | endpoint 只读 snapshot，provider 前 rollback 释放读事务；新增 Session.commit 禁止测试。全五表所有行列比较，成功/失败/first/stale 不变，无 revision/status mutation。 |
| No new AI power | AI 源码无工具/执行代码、动态导入、shell/subprocess、生成 SQL、Scheduler 或 Confirm 调用；React 文本节点显示解释，不使用 dangerouslySetInnerHTML。 |

## Regression 与测试质量

最终命令（backend 使用现有 app_env Python 3.11.16）：

```powershell
python -m pytest --basetemp=../.pytest_tmp/ai-layer-review-final -o cache_dir=../.pytest_tmp/ai-layer-review-cache --tb=short -q
```

**395 passed，1 warning（已有 Starlette/httpx 弃用）**。使用新的项目内 isolated basetemp/cache 避开本机旧目录 ACL，不修改业务逻辑或全局权限。7A client 28、constraints 73、7B diff 22、explanation 41；覆盖独立边界，不以总数代替证据。修复前专门复现到 8 个失败，修复后完整通过。

Frontend `npm test`：**46 passed**；`npm run build`：**成功，Vite 7.3.6，44 modules**。没有增加依赖或测试框架。

本轮 React 生命周期为源码 + 实际使用的 session helper 测试；没有重新跑浏览器 E2E。上一轮浏览器证据保留为历史记录，不冒称本轮复测。

## Real provider smoke（本轮有界四次调用）

实际 MiniMax-M3，Anthropic Messages-compatible `/v1/messages`，max_tokens=600、timeout=20，无产品自动重试。前三次由既有 smoke 脚本在全新隔离 SQLite 中构造 A/B/C；发现时区歧义后，只单独再请求一次 A 检查最终 prompt。没有重复调用挑选成功结果。

| Case | 耗时 | 结果 | 实际内容审查 |
|---|---|---|---|
| A one moved | 3.656s | available | 同一任务后移两小时，无 invented reason/optimal/confirm pressure；UTC 钟点未显式标注，触发本轮第三项修复 |
| B added + moved | 4.312s | available | 新增 Emergency Report，Read Paper 后移一小时；描述占用旧时间段的事实，无推断优先级原因；同样缺显式 UTC 标注 |
| C removed | 4.765s | available | Practice Problems not included in new candidate，Read Paper unchanged；不是数据库删除，时间明确 UTC |
| A final timezone check | 6.156s | available | 明确 `00:00:00Z–01:00:00Z (UTC)` → `02:00:00Z–03:00:00Z (UTC)`，same task、same duration、later 2h；无违规承诺或原因 |

四次都 HTTP 200，完整隔离 DB 五表 digest 前后相同，无 timeout。本轮没有真实 D timeout 可观察，因此 D 的 fallback 证据明确是自动测试中的 mock ReadTimeout，不伪造真实故障记录。B/C 在最终时区 prompt 前执行，不宣称全部样本都验证过最终 prompt。

报告：`.pytest_tmp/ai-layer-review/real-7b-smoke.json`、`final-timezone-smoke.json`；仅 validated diff/prose、状态、model、latency、DB digest 比较，不含 key/raw provider headers/envelope。

7A 不重跑，保留此前真实结果：最后 gate recheck 的 Delete 输入已在 1.81s 得到 unsupported、无 proposal；Confirm 两次 timeout（20.02/20.01s），control 两次 timeout（20.02/20.02s）。目录 `.pytest_tmp/phase7a-final-gate-20261001/` 保留原记录。不得继续把 Delete 说成完全未取得分类，也不得把本轮四次成功当成 gateway 已稳定。

## 数据、Git 与最终限制

开发 app.db 前后 SHA-256 一致：

```text
067DA30A177C38A70C40D7FEB00A23A5304B63F9A8D67E2D9572E708BD782FBA
```

当前可提交文件、frontend bundle、本地 smoke/review JSON 报告使用真实 key bytes 和常见凭证模式扫描，0 命中；只输出计数/路径，摘要在 `.pytest_tmp/ai-layer-review/secret-scan.json`。git check-ignore 确认敏感/生成物忽略；git diff --check 与 untracked 文本 UTF-8/尾空白检查通过。global ignore 的既有读取权限 warning 不影响退出码，没有修改全局 Git 配置。

Scheduler、Validator、models、CRUD schemas、PlanningState、Plan/Task/TimeRule routers、WeeklyPlanPage 对 HEAD 无 diff。本轮未修改数据库 schema、Scheduler、Candidate/Confirm/revision 语义。

Remaining limitations：词法 guard 不能证明不幻觉，普通标题含相关关键词也可能造成安全降级；AI 故障的 diff-only 依赖 backend 响应能到达浏览器，首次客户端到 backend 的传输故障无法凭空获得 diff，已有 diff 会保留。没有新浏览器 E2E。此前 7A 真实 confirm 分类仍受 availability 阻塞；没有把模型永远正确作为程序权限安全的前提。

**Phase 8 建议：代码审核无剩余阻断，可在明确范围后进入下一阶段；若 Phase 8 依赖稳定 AI 可用性或声称通用语义正确，则暂不具备该前提。** 本轮只完成审核与小修复，没有进入 Phase 8，没有 commit/push。

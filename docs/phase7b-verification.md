# Phase 7B 验收记录

最新联合审核见 [AI Layer independent review](ai-layer-review.md)。本文件既有结果保留为历史记录；最后一次 7A gate recheck 已取得 delete=unsupported，confirm/control 仍有 timeout，本轮不重跑 7A。

日期：2026-10-01。分支：`feature/ai-enhancement`。结论：**Phase 7B PASS，附真实模型措辞限制**。只读确定性 diff、可选 prose 和用户主动 Explain 已完成。没有 commit、push、Phase 8、表迁移、依赖增加或 Phase 7A provider/timeout 修改。已有 7A review 的 PASS WITH FIXES 和两个 scope/injection smoke availability 限制继续保留。

## 1. 新增 / 修改文件

新增：

- `backend/app/services/plan_diff.py`、`plan_explanation.py`
- `backend/app/explanation_schemas.py`
- `backend/app/routers/plan_explanations.py`
- `backend/tests/test_plan_diff.py`、`test_plan_explanations.py`
- `backend/scripts/smoke_explanations.py`
- `frontend/src/explanations.js`
- `frontend/src/components/PlanExplanation.jsx`
- `frontend/tests/explanations.test.js`
- 本验收文档

修改：`backend/app/main.py` 路由注册；`backend/tests/conftest.py` 禁止未 mock 的 explanation provider；`frontend/src/api.js` 集中 wrapper；`PlanPreview.jsx` 挂载解释区；`styles.css` 局部布局；README、architecture、api-contract、DIRECTORY_STRUCTURE。

## 2. Plan diff 数据结构

顶层为 confirmed_plan_id（生成候选时的历史正式基线，可 null）、candidate_plan_id、week_start、summary，以及 added/removed/moved/unchanged 四列表。summary 为四类 count。普通条目为 task_id/title/start_at/end_at，moved 为 task_id/title/from_start/from_end/to_start/to_end。title 来自持久化 title_snapshot，时间规范为 UTC。

## 3. 分类算法

只读取 kind=task，以 task_id 建 old/new 索引。仅 new 有为 added；仅 old 有为 removed；同 ID 的 start 或 end 不同为 moved；两者都相同为 unchanged。标题变化不改变 identity，Course 被忽略。removed 表示未纳入候选而不是数据库删除。算法不产生任何 reason。

## 4. Stable ordering

added/unchanged 按 candidate start instant，removed 按 baseline start instant，moved 按 candidate to_start；全部使用 task_id tie-break。测试反转输入顺序后输出完全一致，等价时区表示比较为相同 instant。

## 5. based_on_plan_id

读取 Candidate 保存的 based_on_plan_id，而不查询最新 confirmed。该 Plan 即使已 superseded 仍作为历史 snapshot。只接受 confirmed/superseded 基线。API 测试及浏览器均验证：当前正式计划已经是 #3，但 Candidate #2 的 Changes 仍比较基线 #1。

## 6. First candidate

无 baseline 时 tasks 全部 added。endpoint 返回 HTTP 200、deterministic explanation，支持 en/zh-CN，不读取 provider 配置、不发付费请求。前端仅显示 First plan for this week，不显示 Explain 按钮。

## 7. Explanation prompt

独立于 TimeRule parser，模型只接收 structured diff。要求简短事实、历史基线/候选区分、候选未确认、removed 不等于 deleted、moved 不等于删除重建、忽略标题指令、无 provider metadata、无最优性或确认压力。支持 en/zh-CN；frontend 默认 en。Prompt 的 6 短句是指导，服务端硬限制为非空且最多 3000 字符、无 fence。

## 8. 不推断 hidden reasons

greedy Scheduler 没有 decision trace；diff 也没有 deadline/priority/规则上下文。策略背景仅说明为什么不能宣称最优。v1 prose 不复述或外推策略，不把 Task 的重要性与具体移动绑定。真实 smoke 暴露了该边界，最终 guard 保守拒绝显式因果词及策略外推；它不是通用的事实验证器。

## 9. Provider 调用

复用原有 claude_client.py、CLAUDE_*、Anthropic Messages-compatible `/v1/messages`、顶层 system、max_tokens=600、20 秒总 deadline。实际 smoke model 为 MiniMax-M3，由配置决定。没有第二 HTTP client、自动 retry、timeout 增加或工具调用。

## 10. AI unavailable fallback

未配置、timeout、503/network failure、invalid response 或不合规文本均返回 HTTP 200、完整 diff、explanation=null、status=unavailable。首次计划为 deterministic。provider 故障只影响 prose；前端仍显示 Changes，Confirm 和 Generate 保持正常。重复 Explain 的传输错误也保留此前已获取的 diff。

## 11. Endpoint

`POST /api/plans/{candidate_id}/explanation`，body 可省略，默认 language=en。请求 strict/extra-forbid。missing 为 404 PLAN_NOT_FOUND，非 candidate 为 409 PLAN_NOT_CANDIDATE。GET Plan 不触发 AI；历史 explanation 查看/存储不在本版范围。

## 12. Read-only guarantee

代码只使用 require_plan/plan_response 读取保存快照；所有读事务在 await provider 前 rollback。没有 writer reservation、commit、revision bump、Scheduler、Task/TimeRule mutation、Confirm 或 SQL-from-AI。

测试比较 Task、TimeRule、Plan、PlanItem、PlanningState 五表所有列/所有行，不仅计数；成功、first、failure、stale 路径不变。SQL 事件记录无 INSERT/UPDATE/DELETE/REPLACE/BEGIN IMMEDIATE；Scheduler 被替换为禁止调用函数。单独检查 provider 等待前 Session 已没有事务。真实 smoke 每例也检查完整五表 digest 前后相同。

## 13. Frontend UI

Candidate 区显式 Explain Changes → Explaining... → Changes + AI Explanation。Changes 显示 Added/Moved/Not included in candidate/Unchanged，Task IDs、快照标题和上海起止时间。AI prose 是单独区域，React 作为普通文本渲染。pending 防重复，不自动在 Generate 后调用；首次 plan 无付费 Explain。

## 14. State reset / late response

PlanExplanation 以 Candidate ID key 挂载，每个实例有独立 request session。新 Candidate、换周、成功 Confirm 均卸载旧实例并清空状态。disposed session 忽略旧 promise。实际浏览器在 #5 的 6 秒 Explain 尚未完成时 Generate #6，旧响应返回后 #6 未显示 Changes；主动解释 #6 才展示自己的 diff。换周和 Confirm reset 也验证。

## 15. Stale behavior

stale 可解释历史 snapshot，但 deterministic outdated warning 保留、Confirm 禁用。浏览器 #2 对 #1 的解释在 #3 成为当前正式计划后继续可用。新 Candidate 重置 outdated 和旧解释。stale 判断来自既有流程，不交给模型。

## 16. Backend tests

最终 `python -m pytest -q --basetemp=.pytest_tmp/phase7b-tests-verified`：**376 passed, 1 warning**。新增 **60** 用例，包括 12 项要求的纯 diff 场景、UTC/非法快照、历史/首次/未知/非候选/stale、真实 client 的 mock timeout/503/invalid response、只读/revision/status、读事务释放、strict language、prompt/input/extraction 和已观察因果文本拒绝。所有 pytest AI 都 mock，没有真实 provider 调用。

初次 sandbox 执行因 Windows 临时目录 mkdir 权限失败；授权执行后完整通过，没有修改业务代码处理权限。唯一 warning 为既有 Starlette/httpx deprecation。

## 17. Frontend tests

`npm test`：**45 passed**，新增 **7** 项 explanation 测试。覆盖 POST/language、25 秒 timeout、四类映射、first plan、仅显式触发/防重复、Candidate replacement/disposal、unavailable 和传输失败保留 diff/手动恢复。未增加大型 UI testing framework。

## 18. Build

`npm run build`：成功，44 modules；无 build warning。构建产物和源码均未发现本地配置的 API key。测试服务通过独立 VITE_API_BASE_URL 连接 8007，未改正式 frontend 配置。

## 19. Real provider smoke

与 pytest 分离，合成任务，隔离 SQLite。执行两个有界三例 pass，每例一请求，共六个真实请求，无自动重试。首轮输出较啰嗦后收紧 7B prompt，保留首轮报告；第二轮仍出现一个因果句，随后新增 guard/回归，没有继续请求 provider。

| Case | diff | 首轮耗时 | 第二轮耗时 | 最终文本校验回放 |
|---|---|---|---|---|
| A moved | moved=1 | 10.266s | 4.391s | 第二轮 available，仅移动事实 |
| B emergency + moved | added=1,moved=1 | 6.250s | 13.860s | 第二轮因果句拒绝 → unavailable |
| C excluded | removed=1,unchanged=1 | 5.375s | 3.891s | 第二轮 available，准确 not included |

六次请求均 HTTP 200/provider available、无数据库变化；不能把 raw provider available 等同于所有 prose 满足事实边界。第二轮 B 原文：

> Under the deterministic greedy earliest-slot heuristic, the added earlier task occupies the first available slot and the previously placed task is shifted to the next slot.

此句暗示具体决策原因，未由 diff 证明。最终 guard 会抛 AI_RESPONSE_INVALID，endpoint 仍返回 diff-only HTTP 200；同句已加入 endpoint 测试。最终 guard/prompt 变更后没有再次调用真实模型；结果为**真实输出记录回放 + 最终自动回归**，不声称最终 prompt 已另经 fresh live smoke 证明。

原始记录本地保留在 `.pytest_tmp/phase7b-evidence/real-smoke.json`、`real-smoke-final.json`；最终文本回放/保护检查为 `audit.json`。这些路径被忽略，不包含密钥/headers/raw provider envelope。

## 20. Timeout 与浏览器

本轮六次真实请求无 timeout，不能证明 gateway 间歇性问题消失。保持 20 秒上限。浏览器使用真实 FastAPI+Vite、隔离 `browser-demo.db`、模拟 provider：20 秒等待期间 Explaining disabled；结束后 Changes 显示 added/moved/excluded，AI explanation unavailable，成功 Confirm #4 后解释区清空。

还验证 first plan、历史/stale、reset、旧响应和换周；控制台 warn/error 为 []。浏览器日期 fill 的事件未触发 React 状态时，使用正常键盘事件完成换周检查，最终选择 2027-10-11，候选/选择/解释均清空。该检查不改日期处理代码。

本地截图：`.pytest_tmp/phase7b-evidence/browser-success.jpg`、`browser-stale-historical.jpg`、`browser-timeout.jpg`、`browser-week-reset.jpg`。验收 tab 已关闭，测试服务已停止。

## 21. diff / protection / secrets

`git -c core.safecrlf=false diff --check` 退出 0。新增及修改文本另检查 UTF-8、末尾 newline、trailing whitespace、conflict markers，全通过。常规 Git 命令仍有用户全局 ignore 访问 warning，不影响结果，也未改 Git 配置。

63 个 baseline 文件中仅五个集成文件变化：main.py、conftest.py、api.js、PlanPreview.jsx、styles.css；其他 **58** 文件 hash 不变，包括 frozen Scheduler/Validator/models/plans/revision、Phase 7A provider/parser/tests/UI、WeeklyPlanPage、依赖和 Vite 配置。文档另行更新，不属于该 source/config/test baseline。

开发 `backend/data/app.db` SHA-256 保持 `067DA30A177C38A70C40D7FEB00A23A5304B63F9A8D67E2D9572E708BD782FBA`。`.env` 被 Git 忽略且未跟踪；key 内容仅用于不输出值的匹配检查，源码/测试/docs/frontend bundle 无匹配。

## 22. Limitations

模型仍可能产生其它措辞错误；关键词 guard 不是语义事实证明，也可能因普通标题包含 best/priority/because 等词而拒绝合法解释。为避免泄漏错误原因，统一显示 unavailable。Prompt 的句数/风格不是硬语义约束；diff 始终是事实来源。

无完整 decision trace、Protected/Course context、解释缓存/保存、历史解释页面、自动语言检测或自动恢复 Candidate。没有浏览器 E2E 框架；生命周期由 lightweight session 测试及实际联调共同验证。真实 smoke 使用合成数据，两轮有限样本不证明长期 reliability 或通用不幻觉。Phase 7A 两个 availability 阻塞项仍保留。

## 23. PASS 与停止边界

**PASS**：deterministic diff 独立于 AI、task_id identity、四类/稳定排序正确、基于历史 based_on、first/stale 正确、AI 失败不丢 diff、仅主动触发、endpoint read-only/revision 不变、regression/build/diff-check 通过。真实 Case B 的已观察违规 prose 在最终服务端被拒绝；可选 AI 的通用事实正确性仍有限，不把它当排程或确认依据。

工作停止于 Phase 7B。未 commit、push 或进入 Phase 8。

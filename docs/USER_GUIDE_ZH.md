# Student Growth Assistant 中文使用指南

## 1. 项目简介

这是面向大学生的个人任务与周计划助手。你可以管理 Tasks（任务）、Course（课程）和 Protected Time（保护时间），生成候选周计划，检查后确认，也可以在突发任务出现时重新规划。

AI 是可选增强：帮助理解自然语言时间约束，以及把程序计算的计划变化写成简短说明。核心规划功能在未配置 AI 时仍然可用。本指南覆盖 v1.1.x 的分钟级工作流；`v1.0.0` 为历史版本。

## 2. 系统启动

需要 Python 3.11+ 和 Node.js 20.19+ 或 22.12+。使用能运行 `conda` 的 Anaconda Prompt 或已初始化的 PowerShell。以下命令从项目根目录开始。

### Backend

首次准备环境：

```powershell
conda create -n app_env python=3.11 -y
cd backend
conda run -n app_env python -m pip install -r requirements.txt
```

如果 `app_env` 已存在，跳过创建环境；如果已在 `backend`，跳过 `cd backend`。接着启动后端：

```powershell
conda run -n app_env --no-capture-output python -m uvicorn app.main:app --reload
```

后端地址：http://127.0.0.1:8000。访问 http://127.0.0.1:8000/api/health 可检查服务是否正常。默认数据保存在 `backend/data/app.db`，重启后仍保留。

### Frontend

另开一个终端，从项目根目录执行：

```powershell
cd frontend
npm install
npm run dev
```

在浏览器打开 http://localhost:5173，保持两个终端运行。端口 5173 必须空闲；页面无法连接时先确认后端已启动。

## 3. AI 配置（可选）

参考 `backend/.env.example`，在本地 `backend/.env` 中填写：

```dotenv
CLAUDE_API_KEY=
CLAUDE_BASE_URL=https://your-gateway.example
CLAUDE_MODEL=
CLAUDE_API_VERSION=2023-06-01
```

上面是占位示例，不可直接用于调用。API key 和模型名由你的服务方提供；base URL 使用 gateway 地址或其 `/v1` 地址，不要添加 `/messages`。实际模型由 gateway 配置决定，不一定是 Claude。更改配置后重启后端，切勿把 key 放进前端或提交到 GitHub。

不配置 AI 时，仍可管理任务和时间规则、生成 Candidate、Confirm 和查看正式周计划。AI 请求只在手动点击时发生，可能产生服务方费用；服务不可用时不会自动重试。

## 4. Tasks 页面

1. 打开 **Tasks**，点击 **Add task**。
2. 输入标题、时长、截止时间和优先级；备注可选。
3. 点击 **Create task** 保存。

时长最小 **1 分钟**，可以输入任意正整数分钟，例如 **17、45、93**。零、负数和小数无效。截止时间按上海时间填写；优先级可选 Low、Normal、High。

待办任务显示 **TODO**。使用 **Edit → Save task** 修改，**Mark Done** 标记完成，或 **Cancel task** 取消。完成和取消后记录保留，但不能参与新的任务选择。修改任务不会自动更新已确认计划，需要重新生成并确认。

## 5. Courses & Protected Time

打开 **Courses & Protected Time**：

- **Course** 是每周固定课程，使用 **Add course**，选择星期和起止时间。
- **Protected Time** 是不希望安排任务的时间，使用 **Add protected time**；Repeats 可选 Every week（weekly）或 Once（once），再选择星期或具体日期。

例如，每周三 **09:07–10:23** 的实验室会议可录为保护时间；每周固定课堂可录为课程。一次性会议使用 Protected Time 的 Once。课程仅支持每周重复。

起止时间可以精确到分钟，必须开始早于结束，不支持跨午夜。**Edit** 修改记录，**Deactivate** 停用；停用记录保留但不占用新排程时间。课程显示在计划中，保护时间限制任务放置，不显示为独立任务块。

## 6. AI Natural Language

在时间规则页面输入：

> 每周三下午两点零七分到三点二十三分我要去实验室，这段时间不要安排任务。

流程为 **Parse with AI → AI Proposal 预览 → 用户检查或修改 → Apply time rule**。

检查类型、星期或日期、起止时间，确认正确后才 Apply。**Discard** 放弃提案。AI 不会直接保存；缺少明确时间时会要求补充，创建任务或确认计划等请求不在此功能范围内。解析失败可改用手动表单。

## 7. Weekly Plan

1. 打开 **Weekly Plan**，选择 Week date。所选日期会转换为该周周一。
2. 勾选本次要安排的 TODO Tasks。
3. 点击 **Generate Candidate**。
4. 查看右侧 **Candidate Plan**，检查任务、时间和课程。
5. 满意后点击 **Confirm Candidate**。

Generate 不会立即覆盖正式计划。只有 Confirm 成功，候选才成为左侧 **Current Confirmed Plan**。更换勾选的任务后，需要恢复为生成该 Candidate 时的原任务选择，或重新 Generate，才能 Confirm。首次计划显示 **First plan for this week**，没有旧计划可比较。

完整刷新浏览器会清空当前候选预览和勾选项；重新选择对应周即可加载已保存的正式计划。切换应用内页面会保留当前候选预览。

## 8. 自动排程规则

任务工作时间为每天 **08:00–22:00**，起点精度为 **1 分钟**，例如 **08:07、09:23、14:51** 均合法。任务必须连续完成，并且结束不晚于 22:00 和自身 deadline。

系统先考虑更早的 deadline；截止时间相同时，优先安排更高 priority；仍相同时按任务 ID 顺序。系统依次寻找最早可用的连续时段，避开课程、保护时间和已放入候选的任务。任务不能拆开，也不会回头调整已放置任务。

区间首尾相接允许：课程 **09:07–09:23** 后，任务可以从 **09:23** 开始。17 分钟任务 **21:43–22:00** 合法，**21:44–22:01** 越过工作窗口。

## 9. 突发任务重新规划

假设本周计划已确认，突然新增“实验报告”，时长 **93 分钟**，priority 为 **High**，并填写真实截止时间：

**创建 Task → 回到 Weekly Plan → 勾选仍需安排的原任务和突发任务 → Generate Candidate → 比较旧 Confirmed 与新 Candidate → Confirm Candidate**。

新 Candidate 未确认前，旧正式计划不会改变。不要只勾选突发任务，除非确实希望其他任务不包含在新计划中。Confirm 成功后，新计划替换同周旧正式计划。

## 10. Changes / AI Explanation

候选有旧正式计划时，点击 **Explain Changes**。程序确定性比较保存的任务和时间：

- **Added**：新候选增加的任务。
- **Moved**：同一任务的开始或结束时间改变。
- **Not included in candidate**：旧计划的任务未包含在新候选，不表示任务被删除。
- **Unchanged**：任务的起止时间保持一致。

**AI Explanation** 只是把这些变化转换为自然语言，AI 不负责排程，也不会确认候选。AI 不可用时，Changes 仍保留，Confirm 仍可使用。Changes 以上海时间显示；AI 说明中的时间标记为 UTC，阅读时注意时区。

## 11. 常见状态 / 错误

- **UNSCHEDULABLE**：当前规则下 greedy scheduler 没找到完整安排，不代表数学上一定无解。检查截止时间、连续时长和占用时段后再生成。
- **STALE_CANDIDATE**：候选创建后，Task、TimeRule 或正式计划发生变化。重新 Generate 后再 Confirm。
- **Selection changed**：勾选的任务与当前候选不同。恢复原选择或重新 Generate；这是前端选择状态提示。
- **AI unavailable**：AI 服务暂时不可用。仍可手动添加 TimeRule、Generate、Confirm 和查看 deterministic Changes。
- **输入校验失败**：检查必填项、正整数时长、日期和起止时间；按页面提示修正。
- **连接失败 / timeout**：确认服务正在运行；写入请求超时后先重新加载最新状态，再决定是否重试。

## 12. 时区

系统按 **Asia/Shanghai / UTC+08:00** 理解用户输入并显示计划，不依赖电脑当前时区。页面任务 deadline 和课程/保护时间均按上海时间填写。

## 13. 完整 Demo 示例

在独立、没有其他任务或规则的演示环境中操作；不要清空日常数据来演示。以下采用 **2026-10-05** 所在周，所有时间均为上海时间：

1. 创建 **Task A：17 分钟**、**Task B：43 分钟**，两者 priority 为 Normal，deadline 为 **2026-10-05 12:00**。先创建 A，再创建 B。
2. 创建每周一 **Course：09:07–10:23**，以及每周一 **Protected Time：13:11–13:46**。
3. 选择该周，勾选 A、B，Generate。没有其他数据时，A 为 **08:00–08:17**，B 为 **08:17–09:00**。
4. 检查后 Confirm，成为正式计划。
5. 创建 **Emergency Task：23 分钟**、High，deadline 为 **2026-10-05 09:07**。
6. 回到 Weekly Plan，勾选 A、B、Emergency，Generate。新候选为 Emergency **08:00–08:23**、A **08:23–08:40**、B **10:23–11:06**；旧正式计划此时保持原样。
7. 在确认前点击 Explain Changes，检查 Added 和 Moved；AI 未配置时，确定性变化仍可显示。
8. 最后 Confirm 新候选，确认左侧正式计划已替换。

需要演示 AI 输入时，可另外使用第 6 节的描述；Apply 会改变时间规则，因此应先完成输入，再重新 Generate。其他任务或规则会影响示例结果。

## 14. 当前 MVP 限制

- 仅单用户，无登录或多用户隔离。
- 使用 greedy，不回溯，不保证找到所有可能安排，不搜索最优解。
- 不拆分任务；任务需在同一天连续完成。
- 没有 Plan History 页面，刷新后不自动恢复候选预览。
- 不按当前时间冻结已执行或已开始的任务块。
- 不支持跨午夜时间规则；任务工作窗口固定为 08:00–22:00。
- 外部 AI 可用性不保证，AI 说明也需要用户核对。
- 排程支持整分钟，不支持秒级任务起点。

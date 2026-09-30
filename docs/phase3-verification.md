# Phase 3 verification

验收日期：2026-09-30（Asia/Shanghai）。结论：**Phase 3 PASS**。

本次从仓库已有的未提交 Phase 3 实现继续核对、修复并完成验收。未进入 Phase 4，未 commit，未 push。后端业务 API、schema、ORM 和数据库设计保持原有契约。

## 1. 新增 / 修改文件

以下按相对 Git HEAD 的工作区变化列出，包括本次开始时已有的未提交实现。

新增前端文件：

```text
frontend/.env.example
frontend/index.html
frontend/package.json
frontend/package-lock.json
frontend/vite.config.js
frontend/src/main.jsx
frontend/src/App.jsx
frontend/src/api.js
frontend/src/datetime.js
frontend/src/styles.css
frontend/src/pages/TasksPage.jsx
frontend/src/pages/TimeRulesPage.jsx
frontend/src/components/TaskForm.jsx
frontend/src/components/TimeRuleForm.jsx
frontend/tests/api.test.js
frontend/tests/datetime.test.js
```

其他新增文件：`backend/tests/test_cors.py`、`docs/phase3-verification.md`。

修改文件：`.gitignore`、`README.md`、`DIRECTORY_STRUCTURE.md`、`backend/app/main.py`、`docs/architecture.md`、`docs/api-contract.md`。

联调启动脚本和 SQLite 文件位于被忽略的 `.pytest_tmp/phase3_browser/`，不是产品源码，也不属于提交清单。`frontend/node_modules/`、`frontend/dist/`、`frontend/.env` 被忽略，`.env.example` 保留。原有数据库、Python 缓存和 pytest 临时目录忽略规则仍在。

## 2. React 页面结构

`App.jsx` 用 `useState` 切换 Tasks 与 Courses & Protected Time；不用 React Router。两个页面用 `useEffect` 加载已有数据，用 `useState` 管理列表、表单、错误和请求状态。`TaskForm`、`TimeRuleForm` 都复用于创建和编辑。

Task 展示 title、description（有值时）、duration、deadline、priority、TODO/DONE/CANCELLED。TODO 支持 Edit、Mark Done、Cancel task。TimeRule 按 Courses / Protected Time 分区，显示星期文字或日期、时间、recurrence、ACTIVE/INACTIVE；停用项继续显示并弱化。两页都有 Loading、Empty、Error 和 Retry。

提交及列表操作期间禁用按钮，事件处理器检查 pending；成功后使用后端返回的对象更新列表，不要求刷新，不做 optimistic update。Task 首次加载失败时禁用创建，避免用户在未知列表状态下重复创建；该禁用状态与 Saving 文案分开。

## 3. api.js 结构

所有 HTTP URL 和 `fetch` 集中在 `api.js`，统一使用 `VITE_API_BASE_URL`，默认 `http://127.0.0.1:8000`。导出 `getTasks`、`createTask`、`updateTask`、`getTimeRules`、`createTimeRule`、`updateTimeRule`。

统一请求函数负责 JSON、HTTP 错误、网络错误、不可读响应及 15 秒 AbortController 超时；finally 清除定时器。页面的 finally 解除 Loading / pending。写请求超时后可能已经在服务端完成，因此错误提示要求先查看列表再重试，不自动重复发送。

## 4. CORS 配置

`backend/app/main.py` 的 CORSMiddleware 明确允许：

- `http://localhost:5173`
- `http://127.0.0.1:5173`

允许方法为 GET、POST、PATCH，允许请求头为 Content-Type；没有通配 origin，没有凭证认证。Vite 使用 `port: 5173, strictPort: true`，端口占用时退出，避免自动切换到未允许的 origin。

两种 origin 的 PATCH 预检 pytest 均通过，5174 origin 被拒绝。实际浏览器从 127.0.0.1:5173 向 127.0.0.1:8000 的 POST/PATCH 及 OPTIONS 预检成功。

## 5. datetime-local 与 UTC / +08:00

`datetime.js` 集中实现：

- `toBackendDeadline('2026-10-05T22:00')` → `2026-10-05T22:00:00+08:00`。
- `toDatetimeLocalValue('2026-10-05T14:00:00Z')` → `2026-10-05T22:00`。
- `displayDeadline` 显示上海日期时间。

转换 API 响应前要求明确的 Z 或时区偏移；不接受无时区的日期时间。`Date` 仅解析带偏移的 instant，再加固定 8 小时并使用 `toISOString()` 的 UTC 输出，不使用电脑本地时区 getter 或本地日期格式化。

Node 时间测试在 UTC 与 America/Los_Angeles 下均通过。浏览器实际创建 22:00 任务，GET 返回 14:00Z；编辑表单预填 22:00，保存和刷新后列表仍为 22:00。

编辑时如果未改变 deadline 的分钟值，则保留原始 API 时间，避免修改标题或备注时丢失秒或微秒；用户改变 deadline 时仍发送明确的 +08:00 整分钟时间。TimeRule 的 start_time / end_time 也保留未修改字段的原始精度。

## 6. weekly / once 切换

Course 固定 `kind: course, recurrence: weekly`，没有 once 选项。Protected Time 可选 weekly / once；切换时清空 weekday 和 date 状态，再要求用户填写当前显示字段。提交完整合法组合：weekly 发送 `date: null`；once 发送 `weekday: null`。PATCH 同样发送这些明确的 null，后端校验最终规则。

实际 GET 验证：

```json
{"id": 2, "recurrence": "once", "weekday": null, "date": "2026-10-09"}
{"id": 3, "recurrence": "weekly", "weekday": 5, "date": null}
```

## 7. 422 error 解析

`readableDetail` 接受字符串或 FastAPI detail 数组。数组中每项去掉 loc 的 body 前缀，将字段路径与 msg 拼接，用分号连接。组合错误没有字段路径时直接显示 msg。未知结构回退到通用错误，不把对象直接插入页面。

浏览器真实 POST 空白标题得到：`title: Value error, title must not be blank`。TimeRule PATCH 结束时间早于开始时间得到：`Value error, start_time must be before end_time; overnight rules are not supported`。均无 `[object Object]`，失败后按钮重新可用。

## 8. 浏览器实际联调结果

启动真实 FastAPI app 与 Vite，使用独立 `.pytest_tmp/phase3_browser/browser.db`，通过 app 的数据库依赖覆盖隔离联调数据。

| 验证 | 结果 |
|---|---|
| Tasks 空状态 / 已有任务加载 | PASS；初始 No tasks yet，创建后刷新加载已有任务 |
| 创建 Task | PASS；默认 TODO，90 分钟、high、description、22:00 deadline 正常 |
| 编辑 Task | PASS；标题和时长立即更新，deadline 正确预填 |
| Mark Done / Cancel | PASS；DONE / CANCELLED 保留显示，操作按钮消失 |
| Task 422 | PASS；可读错误，无额外 Task 写入 |
| TimeRule 空状态 / 已有规则加载 | PASS；两区空提示和刷新加载正常 |
| 创建 weekly course / 编辑 course | PASS；Wednesday → Thursday，日期为空 |
| 创建 weekly protected time | PASS；Every Wednesday，18:00–19:00 |
| 创建 once protected time | PASS；2026-10-08，15:00–16:00 |
| protected weekly → once | PASS；GET weekday 为 null |
| protected once → weekly | PASS；GET date 为 null |
| Deactivate | PASS；INACTIVE 保留显示并弱化，没有 Reactivate |
| TimeRule 422 | PASS；非法时间组合未写入，表单保留可修改 |
| 刷新 / 后端重启后的持久化 | PASS；两个 Task、三个 TimeRule 保留 |
| 后端断线 / 恢复 | PASS；两页退出 Loading 并显示 Retry，恢复后规则 Retry 成功、任务重新加载成功 |
| CORS | PASS；浏览器请求和预检成功，pytest 验证两种允许 origin |
| 未修改时间字段的精度 | PASS；浏览器编辑标题后 GET 保留 deadline 的 45.123456 秒、规则时间的 15.123456 / 30.654321 秒 |

联调前后开发数据库 `backend/data/app.db` 的 SHA-256 相同：`067DA30A177C38A70C40D7FEB00A23A5304B63F9A8D67E2D9572E708BD782FBA`。

## 9. Backend pytest 实际结果

在 backend 目录运行：

```powershell
conda run -n app_env --no-capture-output python -m pytest
```

结果：**39 passed, 1 warning**，包括原有 36 个 Phase 1–2 测试及新增 3 个 CORS 测试。Python 3.11.16，pytest 8.4.2。

## 10. Frontend 安装 / 测试 / 构建

在 frontend 目录实际运行：

```powershell
npm install
npm test
npm run build
```

`npm install` 成功；Node 测试 **6 passed, 0 failed**；Vite 7.3.6 构建成功。依赖仅 React、React DOM、Vite 与 React Vite 插件；测试使用 Node 内置 test / assert，没有新增测试框架。

## 11. Warnings

- pytest 有一条环境依赖警告：Starlette TestClient 使用 httpx 的方式被标记 deprecated，提示未来使用 httpx2。没有影响测试结果，本阶段未扩大依赖升级范围。
- npm install 提示 9 个包可获得 funding，属于信息提示。
- npm run build 没有构建 warning。
- Vite 开发热更新时出现一次 WEEKDAYS 非组件导出的 Fast Refresh 提示；自动刷新上层页面后继续正常，随后浏览器验证使用完整刷新，生产构建通过。
- Git 检查提示 `.gitignore` 的 LF 将按现有配置转为 CRLF，且沙箱不能读取用户级全局 ignore 文件；仓库自身忽略规则已实际核对，`git diff --check` 通过。

## 12. Limitations

- 仅单用户本地开发 Demo，固定 Asia/Shanghai（UTC+08:00）。没有认证、计划、排程、AI 或恢复 Done/Cancelled/Inactive 的操作。
- 表单按分钟输入和显示时间。未修改的时间字段保留后端原始秒或微秒；用户改变时间时使用整分钟。
- 没有跨午夜规则、拖拽日历或多用户并发同步。页面切换 / 刷新会放弃未提交表单；其他客户端的修改需要重新加载列表。
- 写请求超时 / 断线不能保证服务端没有写入。没有幂等键或自动重发，用户应查看列表后再重试。
- 浏览器验证使用 Codex 内置 Chromium；未覆盖 Safari / Firefox，也没有添加持续运行的浏览器测试框架。

## 13. Phase 3 是否 PASS

**PASS。** 请求范围内的 Task / TimeRule UI、固定时区转换、recurrence 清空、CORS、错误状态、持久化、后端回归和前端构建均已实际验证。停止在 Phase 3，后续阶段未实现；所有变化留在工作区供审核。

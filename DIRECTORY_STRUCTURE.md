# 仓库结构与架构约定

本文描述当前三页 AI 工作台代码布局；阶段验收文档保留历史记录，不作为现行目录索引。现行入口为规划、复盘、我的档案；自定义类别与偏好规则由 `taxonomy` 路由和共用服务管理，复盘与档案聊天复用 `WorkspaceChat`。

## 目录结构

```text
student-growth-assistant/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI 装配、启动迁移、路由挂载
│   │   ├── database.py             # SQLite engine、Session 与依赖
│   │   ├── models.py               # ORM 表与约束
│   │   ├── schemas.py              # HTTP 请求/响应契约
│   │   ├── assistant_schemas.py    # AI 助手与偏好契约
│   │   ├── routers/                # HTTP 入参校验与响应
│   │   │   ├── assistant.py        # 会话、运行状态、候选预览与确认
│   │   │   ├── plans.py            # 周计划候选和原子确认
│   │   │   ├── growth.py           # 成长 API 兼容装配入口
│   │   │   ├── growth_attention.py # 任务关注排序、估时建议
│   │   │   ├── growth_profile.py   # 个人资料与偏好历史
│   │   │   ├── growth_reviews.py   # 周复盘
│   │   │   ├── growth_insights.py  # AI 习惯建议确认流程
│   │   │   ├── goals.py            # 长期目标
│   │   │   ├── execution.py        # 完成反馈和计时
│   │   │   ├── data.py             # 本地数据导入、导出和备份
│   │   │   ├── tasks.py            # 任务 CRUD
│   │   │   └── time_rules.py       # 课程与保护时间 CRUD
│   │   └── services/               # 可测试的业务规则与外部服务适配
│   │       ├── assistant_ai.py     # AI 解析、比较和解释编排
│   │       ├── assistant_scheduler.py
│   │       ├── assistant_state.py  # 助手上下文、偏好和任务状态
│   │       ├── claude_client.py    # Anthropic/OpenAI 兼容网关
│   │       ├── scheduler.py        # 确定性基础排程
│   │       ├── validator.py        # 独立日程约束校验
│   │       ├── planning_state.py   # 写事务和全局计划版本
│   │       ├── growth_tracking.py  # 执行记录与计时规则
│   │       ├── growth_insights.py # 行为证据统计与建议
│   │       ├── growth_profile.py  # 个人资料版本
│   │       ├── growth_data.py     # 备份、导入导出和数据恢复
│   │       └── growth_migrations.py
│   └── tests/                      # API、服务、事务和兼容性测试
├── frontend/
│   ├── src/
│   │   ├── App.jsx                 # 页面导航和跨页面动作
│   │   ├── api.js                  # 统一 HTTP、超时和业务错误映射
│   │   ├── assistant.js            # 助手纯数据映射
│   │   ├── datetime.js             # 北京时间转换
│   │   ├── planning.js              # 计划纯计算
│   │   ├── pages/                  # 今日、成长、资料、任务和课程页面
│   │   ├── components/             # 表单、时间线和安全消息组件
│   │   ├── styles.css              # 全局与成长页面样式
│   │   └── assistant.css           # 助手工作台样式
│   └── tests/                      # 纯函数、API 与交互状态测试
├── docs/                           # API 契约、架构边界和验证记录
├── codex/                          # 本地启动、演示、导入和验收脚本/说明
├── README.md
└── DIRECTORY_STRUCTURE.md
```

本地 `.env`、SQLite 数据库、个人课表、运行日志、`node_modules`、构建目录和测试缓存是运行产物，不属于源码或公共样例。个人数据和密钥不得加入 Git。

## 依赖方向

```text
React 页面 → api.js / 纯前端工具 → FastAPI routers → services → models / SQLite
                                             └→ AI client（只处理模型通信）
```

- `main.py` 只负责应用装配、启动生命周期和路由注册。
- Router 负责 HTTP 契约、鉴权（当前单用户 MVP 无账号层）和状态码；复杂规则放在 `services/`。
- 服务层不依赖 React，也不通过 HTTP 调用本项目自身 API。
- AI 输出先经过结构校验；排程和硬约束校验由程序执行；只有用户确认才写入正式计划。
- 计划状态修改统一通过 `planning_transaction`：先取得 SQLite 写锁，再执行业务变更和版本号更新，同一事务提交；异常统一回滚。
- 调用模型前释放数据库事务；不能在等待模型响应时持有 SQLite 写锁。
- 前端统一走 `api.js`；页面只组合界面状态，不自行拼接服务地址或重复实现错误提示。
- 日期与时间在边界层统一解释为北京时间；纯排程与映射函数保持无 UI/数据库副作用。

## 当前模块边界

- `routers/growth.py` 保留稳定的聚合入口；成长 API 按关注排序、资料、周复盘、AI 建议拆入独立 Router，路径仍为 `/api/growth/...`。
- `assistant.py` 负责长任务状态机和事务交接；AI 等待、方案校验、采用写入属于不同阶段，不合并成一个长事务。
- `planning_state.py` 的 `planning_transaction` 是一般业务写事务入口；助手运行状态机可分段提交时仍显式管理事务，避免把多个处理阶段误合并。
- `scheduler.py` 和 `assistant_scheduler.py` 分别服务旧版基础排程与当前多方案助手；`validator.py` 为生成后的日程提供独立校验。
- 模型适配集中在 `claude_client.py`，配置支持 Anthropic Messages 与 OpenAI Chat Completions；业务代码不直接读密钥或拼 Provider 请求。

## 验证入口

- 后端：在 `backend/` 运行 `..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider`。
- 前端：在 `frontend/` 运行 `npm test` 与 `npm run build`。
- 演示：在仓库根目录运行 `pwsh -NoProfile -ExecutionPolicy Bypass -File .\codex\启动演示版.ps1`；演示数据与正常数据库隔离。
- 更细的接口边界见 `docs/api-contract.md`；早期阶段实现和证据见 `docs/architecture.md` 及 `docs/phase*-verification.md`。

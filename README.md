# 个人成长助手 · Student Growth Assistant

通过 AI 对话整理任务、目标和偏好，根据真实执行记录改善下一次安排。本项目是 **本地单用户课程项目 MVP**，使用 React、FastAPI 和 SQLite。

## 三个工作台

| 页面 | 可以做什么 |
|---|---|
| **规划** | 输入新任务、DDL 和临时要求；查看冲突、比较候选安排，确认后保存日程 |
| **复盘** | 补录或更正完成情况、实际耗时和阻碍；查看目标进展、估时建议和周复盘 |
| **我的档案** | 对话整理长期目标、自定义类别与安排偏好；管理课程、固定时间与数据备份 |

**AI 理解表达 → 程序计算与校验 → 展示修改草案 → 用户确认保存。** AI 不直接修改正式日程。课程、锁定时段、截止时间和当前时间由后端检查，旧候选不能覆盖新数据。

## 页面预览

![规划工作台](codex/previews/planning.png)
![复盘助手](codex/previews/review.png)
![档案助手](codex/previews/profile.png)

截图使用匿名演示数据，不代表真实个人经历。

## 安装

推荐 Python **3.11**、Node.js **22**、Git；依赖版本通过 `codex/requirements.lock.txt` 固定。Windows 下建议使用较短的项目路径，避免 SQLite 备份超过系统路径限制。下列命令在项目根目录运行，示例使用 Windows PowerShell：

```powershell
git clone https://github.com/szt1107/student-growth-assistant.git
cd student-growth-assistant
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt -c codex/requirements.lock.txt
npm --prefix frontend ci
Copy-Item backend/.env.example backend/.env
```

macOS/Linux 的 Python 路径为 `.venv/bin/python`；前后端可以分别手动启动。

## 配置 AI

在本地 `backend/.env` 填写以下配置，文件已被 Git 忽略：

```dotenv
AI_API_FORMAT=openai
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=填写账号可用的模型名称
OPENAI_API_KEY=填写你自己的密钥
AI_TIMEOUT_SECONDS=120
```

支持 OpenAI Chat Completions 兼容接口，以及 `AI_API_FORMAT=anthropic` 对应的 Anthropic Messages 兼容接口。分别读取 `OPENAI_*` 或 `CLAUDE_*` 配置，不借用另一组密钥。`claude_client.py` 名称仅用于兼容。

没有有效配置也能启动并管理任务、目标、课程和执行记录；需要模型的聊天、分析和解释会提示不可用。单次模型调用最多 120 秒，可取消或重试。模型可用性和输出质量依赖配置的服务。

## 正常启动

打开两个终端，均从项目根目录运行：

```powershell
# 终端一：后端
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
# 终端二：前端
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

访问 **http://localhost:5173/**，API 文档为 http://127.0.0.1:8000/docs 。正常模式使用真实北京时间，数据库默认是 `backend/data/app.db`。

## 匿名演示

```powershell
& .\codex\启动演示版.ps1 -OpenBrowser
# 停止演示；正常数据不受影响
& .\codex\停止演示版.ps1
# 重新生成匿名样例
& .\codex\启动演示版.ps1 -Reset -OpenBrowser
```

演示地址为 **http://localhost:5174/**，后端端口为 8001。场景固定为 **2026-10-12 至 2026-10-18**，模拟时间是 **10 月 14 日 18:00，北京时间**。课程、任务、偏好和学习样本均为示例。

默认不会读取个人课表。如需使用自己的课程，显式添加 `-CourseSource <本地课程JSON路径>`；新场景可使用 `-Reset`。演示数据库独立保存在 `codex/.runtime/`，不会重置正常数据库。脚本不停止未知进程。

## 数据与使用边界

- 目标、偏好、对话、反馈和日程保存在本地 SQLite；“我的档案”提供导出与恢复。
- 备份不包含 API 密钥。导入校验结构和引用，失败回滚；恢复后旧运行和候选失效。
- 使用真实 AI 时，相关任务、目标、偏好和执行事实会发送给所配置的模型服务；不要在业务字段中填写密钥或敏感身份信息。
- 一次只安排当前周，每项任务使用一个连续时间段；未提供多人账号、公网部署或外部日历同步。
- 软偏好不能覆盖课程、保护时间、锁定和 DDL。有限搜索未找到方案不代表数学上无解。
- 耗时与习惯建议需要有效执行样本，用户采用后才生效；日程或计时结束不会自动证明任务完成。

## 验证

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest --basetemp=../codex/.local/pytest-public
cd ..
npm --prefix frontend test
npm --prefix frontend run build
.\.venv\Scripts\python.exe codex/publication_audit.py
```

测试使用独立数据库。实际发布结果见 [发布验收报告](codex/公开发布验收.md)。历史阶段文档保留原阶段上下文，不代表当前版本的全部验收已经通过。

## 进一步了解

[仓库目录](DIRECTORY_STRUCTURE.md) · [现行架构](docs/architecture.md) · [使用说明与演示讲稿](codex/公开版使用与演示.md)

## 小组来源与许可

本项目基于小组课程作业 [oliver-szr/student-growth-assistant](https://github.com/oliver-szr/student-growth-assistant) 持续完善，保留原提交历史与作者贡献。此仓库是个人整理展示版本，不代表原小组仓库已同步升级。

**本次没有新增开源许可证。** 公开可见不等于授予额外使用、修改或分发许可，后续许可由共同作者协商确定。
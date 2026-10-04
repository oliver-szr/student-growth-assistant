# DeepSeek 官方 API 接入

项目通过 OpenAI Chat Completions 格式调用 DeepSeek。模型仍为 DeepSeek，不需要 OpenAI 公司的 API 密钥。

在本地 `backend/.env` 保存以下设置，密钥不能写入公共 `.env.example`：

```dotenv
AI_API_FORMAT=openai
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-v4-pro
OPENAI_API_KEY=填写你的DeepSeek官方密钥
AI_THINKING_EFFORT=low
```

原 `CLAUDE_*` 配置可以保留。选择 `openai` 后只读取 `OPENAI_*` 的模型、地址和密钥，不回退到旧网关密钥。切回原接口时设置 `AI_API_FORMAT=anthropic` 并重启。

DeepSeek 官方地址默认使用低强度思考。可用 `AI_THINKING_EFFORT=none` 关闭，或用 `high`/`max` 增强思考；增强可能增加耗时。思考开启时，最大输出额度至少为8192 token，供思考和最终JSON共同使用；这是上限，并不意味着每次都会生成或收费8192 token。请求仍有20秒总上限，截断响应不进入候选排程。只读取最终回答，模型思考内容不展示给用户。

普通 OpenAI 兼容网关不会自动附带 DeepSeek 的 `thinking` 字段。若显式配置思考强度，网关需支持 `reasoning_effort`；默认留空。

从项目目录启动演示版：

```powershell
.\codex\停止演示版.ps1
.\codex\启动演示版.ps1
```

演示版沿用独立数据库。需要重新建立初始演示数据时使用 `-Reset`；该操作会保留旧演示库，不清空正常数据库。`-AiModel` 参数同时支持两种API格式，只覆盖启动实例，不修改 `.env`。

真实AI验收（自动创建另一个独立数据库和8002端口，不影响正在使用的演示页面；测试结束停止测试服务）：

```powershell
.\codex\验证DeepSeek接入.ps1
```

结果保存在本地忽略目录 `codex/evidence/real-ai-results-deepseek-openai.json`。通过测试前不能宣称模型已完成真实验收。

## 本机实际验收（2026-10-03）

`deepseek-v4-pro`、OpenAI兼容接口、低强度思考的完整真实流程已通过。8次消息请求包括一次临时调用失败和显式重试；还完成了一次真实中文AI解释。课程冲突、紧急插入、同时修改两个任务、缺信息追问与补充、原子采用和恢复均通过。正式保存后5项任务持久化，三项原任务DDL保留。不能据此承诺所有调用均在20秒内成功。

后端全量442项通过，保留一条既有Starlette/httpx弃用提醒。第一次在正在使用的演示版验收时，其他会话采用方案使测试候选过期，返回409；之后改用独立测试端口8002与专用数据库完成验收。对应失败记录与成功记录都保存在本地evidence目录。

官方文档：[接口与模型](https://api-docs.deepseek.com/quick_start/pricing/)、[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)。

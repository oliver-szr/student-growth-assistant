# 启动与展示

在项目目录打开PowerShell。依赖沿用《本地使用说明.md》。密钥与模型写在被Git忽略的backend/.env，公共backend/.env.example不要填密钥。

## 演示版

```powershell
& .\codex\启动演示版.ps1
```

打开 http://localhost:5174。后端8001，独立codex/.runtime/demo-*.db，固定2026-10-07周三18:00北京时间，界面明确显示演示模式与示例任务。

```powershell
& .\codex\启动演示版.ps1 -Reset
& .\codex\停止演示版.ps1
```

Reset停止本脚本的演示进程，创建新演示数据库，旧数据库保留；不会清空正常数据库。普通停止和重启保留已有演示任务及会话。

本机配置的MiniMax-M3在连续解析中出现多次20秒超时。同网关模型可仅在演示实例覆盖，保留backend/.env与正常版配置：

```powershell
& .\codex\启动演示版.ps1 -Reset -AiModel 'glm-5.3-flash'
```

切换模型须重启实例；正在运行的实例不会因再次执行普通启动而更换模型。模型必须在你的网关账户可用，实际验收结果见《MVP验收报告.md》。

本机私有课表位于codex/.local/基础课表.json。没有该文件的同学会使用匿名示例课程。私有原始PDF、课表、数据库与截图均不提交Git。

## 四分钟展示

1. 显示第6教学周真实课程和三项明确标注的示例任务，展开任务记忆查看各项DDL。
2. 输入“周五20:00前交实验报告，预计两小时，尽量周四下午做。”查看理解卡片与待确认安排。
3. 输入“实验报告改到周四14:00。”指出云计算课程冲突，展示备选；输入“实验报告改到周四19:00。”
4. 输入“明天中午12:00前还要交汇报稿，预计一小时，很重要。”查看文献阅读等任务如何移动，检查DDL。
5. 输入“实验报告改到今晚19:00，汇报稿明早做。”查看软件工程报告等任务的二次变化，点击AI解释调整。
6. 点击采用方案，刷新，展开任务记忆证明任务与DDL已保存。

模型可以追问明确时间或目标任务，按实际问题补充回答。不要提前承诺某个唯一时段；展示实际通过约束校验的结果。

备用：加入900分钟且次日截止的任务，查看无法安排的说明并放弃本轮。AI暂不可用时保留输入，可用手动卡片验证排程，但需明确这是手动流程。

## 正常版

```powershell
& .\codex\启动本地版.ps1
```

打开 http://localhost:5173，真实北京时间，正常backend/data/app.db。预览及导入已整理课表：

```powershell
.\.venv\Scripts\python.exe .\codex\import_timetable.py --source .\codex\.local\基础课表.json
.\.venv\Scripts\python.exe .\codex\import_timetable.py --source .\codex\.local\基础课表.json --apply
```

默认只预览；apply先备份正常数据库，再一次事务导入已核实课程。相同资料重复导入不新增课程。单双周歧义及缺每日时间的实训继续显示待补充，不假定全天占用。

## 复验

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest -q
Set-Location ..\frontend
npm.cmd test
npm.cmd run build
Set-Location ..
.\.venv\Scripts\python.exe .\codex\browser_mvp_acceptance.py
```

浏览器验收须先Reset演示版，使用明确标注的模型输出样例与真实后端。真实模型另用codex/live_ai_acceptance.py，同样先Reset；会产生演示任务并采用方案，不能针对正常数据库运行。日志与结果位于codex/evidence，不随Git发布。

记录演示覆盖模型的真实验收示例：

```powershell
& .\codex\启动演示版.ps1 -Reset -AiModel 'glm-5.3-flash'
$env:CLAUDE_MODEL='glm-5.3-flash'
.\.venv\Scripts\python.exe .\codex\live_ai_acceptance.py
Remove-Item Env:\CLAUDE_MODEL
```

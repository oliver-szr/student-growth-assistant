# 匿名演示与浏览器验证

## 启动和停止

从根目录使用 `scripts/启动演示版.ps1`、`scripts/停止演示版.ps1`；完整命令见 [README](../README.md)。脚本先通过 `conda run -n app_env` 解析已有环境，随后使用该环境的解释器和 PATH 启动 Python，不创建环境。PowerShell 文件使用带 BOM 的 UTF-8，兼容中文文件名与 Windows PowerShell 5.1。

默认前端 http://127.0.0.1:5174 ，后端 http://127.0.0.1:8001 。可显式设置 `-BackendPort 8002 -FrontendPort 5175`；前端端口应使用后端已允许的本机来源。端口被未知进程占用时拒绝启动，不会自动结束其他服务。

场景由 `scripts/demo_scenario.json` 定义，固定为 2026-10-14 18:00 +08:00，覆盖本周与下周。任务、课程和习惯样本均为匿名虚构数据；正常模式仍读取真实北京时间。

`-Reset` 新建 UUID 命名的 `scripts/.runtime/demo-*.db`，保留以前的演示库。默认不读取个人课表；只有显式传入 `-CourseSource <本地JSON路径>` 才导入指定文件。停止脚本仅关闭 PID、启动时间、执行文件路径均与记录一致的进程，不清除数据库。

## 课堂演示顺序

1. 规划：查看现有任务、DDL、本周/下周日程与优先处理项。
2. 手动添加任务，先展示待确认候选和完整时间，再点击“采用方案”；刷新证明数据持久化。
3. 在档案中添加临时课程或保护时间，回到规划点击“局部重规划”，查看保留、移动及冲突原因。局部失败时可拒绝，或明确允许扩大范围后重新计算。
4. 记录部分完成或完成，核对剩余工作；切到复盘查看事实，说明计时结束不等于完成。
5. 在档案查看目标、类别、偏好和导出/恢复入口。需要真实模型的对话或解释取决于有效 API 配置，不能用预览图替代实际成功结果。

[规划预览](images/planning.png) · [复盘预览](images/review.png) · [档案预览](images/profile.png)

## 保留的验收工具

- `scripts/browser_acceptance.py`：当前手动任务、反馈、目标关联、跨周分段、刷新和窄屏浏览器流程，默认使用上述演示端口。必须指向匿名演示，运行会增加合成任务。
- `scripts/check_ui_layout.py`：三页布局、表单展开及输入保留的浏览器检查，使用上述演示前端。
- `scripts/scoped_browser_fixture.py --api <隔离API地址> --scenario single|expansion`：阶段 1 的专用场景，仅接受空匿名库，模拟时间必须为 2026-10-05 07:50 +08:00；不能对已有默认样例库运行。
- `scripts/smoke_constraints.py --output <本地报告路径>`：显式真实 Provider 解析检查，可能产生费用；不会被 pytest 或演示启动自动调用。

浏览器脚本需要调用者已配置 Playwright 和可用浏览器，属于可选验收工具；不是核心安装依赖。本轮不自动安装它们，不自动调用真实模型。工具输出位于 `scripts/.local/` 等忽略位置。无 Playwright 时仍可用实际浏览器打开演示做手动检查。

旧版本本地演示库继续被路径白名单兼容，但新脚本不会读取、移动或清空旧本地数据。数据迁移与恢复见 [数据库说明](database.md)。

## 跨阶段 Mock 集成演示

无真实AI也能复核完整链路。先确认8001/5174未被其他服务占用；以下工具不停止未知进程。新开两个终端，从根目录运行：

维护者可直接使用 `& .\scripts\启动演示版.ps1 -MockIntegration`，每次新建空匿名 Mock 库，沿用现有 PID/启动时间/可执行路径记录；完成后用 `& .\scripts\停止演示版.ps1` 停止本次服务，保留数据库。该选项不会改写普通样例库的路径记录，切回普通演示仍使用原资料。

其他组员激活自己的 Python 3.11 项目环境后，以下命令的 `conda run -n app_env --no-capture-output python` 可直接替换为 `python`；第二个终端仍使用原有 npm 环境。

```powershell
# 终端一：每次创建新的 scripts/.runtime/demo-integration-UUID.db
conda run -n app_env --no-capture-output python scripts/integration_demo.py --serve --port 8001
# 终端二：已有Node环境，明确连接隔离后端
$env:VITE_API_BASE_URL='http://127.0.0.1:8001'
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

该进程固定2026-10-14 18:00+08，只Mock两项任务拆解建议，仍通过正式草案契约与确认流程；屏蔽dotenv、模型密钥与真实模型请求，不修改正常Provider或用户.env。Mock只用于这个显式启动的隔离工具，正常启动没有自动固定答案。

在实际浏览器打开 http://127.0.0.1:5174 ，生成拆解草案、编辑并确认、点击局部重规划和采用；在档案添加临时课程后重新规划，查看变化与原因，记录子任务完成后查看Review与父进度，并刷新验证持久化。演示完在两个终端分别Ctrl+C，保留演示库。

也可以在**另一份新启动的空演示库**上运行HTTP自动集成：

```powershell
conda run -n app_env python scripts/integration_demo.py --verify --output scripts/.local/integration-demo.json
```

该工具仅接受loopback HTTP和带本工具Mock标记、固定时钟、空任务的演示实例；正常演示服务缺少标记时在任何写操作前拒绝。运行后会产生匿名任务，不能对同一库重复要求“空库”验收。它验证Mock拆解→编辑时长/DDL/顺序→幂等确认→仅子任务排程→正式确认→新增课程→旧候选409拒绝且正式计划不变→局部修复移动1项并逐片段保留其他任务→确认→40分钟完成反馈→成长统计与1/2父进度。输出明确标为HTTP集成，不能当作浏览器E2E。

## 手动性能基准

使用README中的scheduling_benchmark命令。10个固定场景覆盖10/30/100任务、临近DDL、混合分段、锁定及既有历史、单任务局部调整、新课程、多周与确定不能完整排入。可用--cases指定小场景；默认普通场景3次、压力100任务1次，不修改算法预算。报告含Git版本、源码指纹、输入指纹、逐策略耗时、预算、有效候选、合法性、工作量和移动数。pure函数无SQL，query_count=0；未暴露的成功搜索扩展次数为null。

每个worker默认110秒保护，超时标为process_timeout并非成功；--profile指定本地.prof文件供标准库pstats检查，剖析会影响时间，不将剖析耗时与普通性能测量混用。原始输出应放在scripts/.local，CI只运行轻量正确性指纹及完整业务回归。

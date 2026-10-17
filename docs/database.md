# 数据库迁移与恢复

## 升级现有安装

在项目根目录执行，先停止正在写入同一个数据库的服务：

```powershell
conda run -n app_env python -m pip install -r backend/requirements.txt -c backend/constraints.txt
conda run -n app_env python scripts/migrate.py
```

正常默认库是 `backend/data/app.db`。指定其他本地库时，在同一终端设置路径：

```powershell
$env:SGA_DATABASE_PATH = '你的数据库完整路径'
conda run -n app_env python scripts/migrate.py
```

启动 FastAPI 也调用同一升级入口。空库依次执行 `0001_baseline` 与 `0002_task_hierarchy`；已有库先检查列、类型、主键、外键，仅接受已知旧结构，再补齐已知阶段字段和索引。成功才记录 Alembic 版本。重复执行不会重复导入任务或清空数据。达到 head 后仍检查模型字段与类型，不能靠一个版本号掩盖不匹配结构。

## 备份和失败处理

实际迁移前通过 SQLite 在线备份 API 生成备份，独立于正常每日备份次数限制。新安装默认备份位置为 `scripts/.runtime/backups`；若已有旧默认备份目录则继续使用该目录，既有备份不被移动或隐藏。可以使用 `SGA_BACKUP_DIR` 指定本地目录。数据库、备份和日志均不加入 Git。

遇到未知结构时拒绝迁移，不使用 `stamp head` 跳过检查。保留原库和备份，先核对版本及字段；不要删除数据库来消除错误。迁移失败不会把该库宣称为已升级。

日程片段拆分设置仍保存于既有任务排程资料 JSON，旧任务没有分段字段时按连续任务处理。任务层级属于独立的组织关系，不改变任务 ID 或历史执行快照。

## 正常库和演示库

正常环境使用真实北京时间。演示环境必须指定独立演示库和模拟时钟，不替换正常库。浏览器验收脚本创建新演示库，停止脚本只关闭身份记录匹配的预览进程，旧实例数据留在本地。

恢复请通过“我的档案”的数据恢复入口进行，不在运行中直接覆盖 SQLite 文件。恢复会提高全局版本并使旧候选、旧运行失效。对话草稿要重新读取正式数据后计算。

## 后续版本维护

迁移目录位于 `backend/alembic`；`baseline_models.py` 是冻结的基线，不随业务模型变化而修改。新增结构应增加新的 revision，并先验证空库、旧库、重复升级和失败备份。`growth_migrations` 保留既有数据初始化和历史转换；应用启动不再直接调用旧建表／加列流程。

本次目录整理仅搬迁 Alembic 资源并修复路径，三个冻结文件保持原字节内容，没有增加 revision、修改 Schema、改变导出格式或在个人库上执行验证。旧本地演示路径仍兼容，新演示默认写入 scripts/.runtime。

## 阶段 2 增量迁移与 JSON 兼容

`0002_task_hierarchy` 只向 tasks 添加列和索引，不批量重建被历史表引用的任务表：

| 字段 | 默认/约束 |
|---|---|
| parent_task_id | 可空自引用外键，ON DELETE RESTRICT，带索引；禁止自身引用，非空时必须 executable |
| task_kind | 非空 executable/container，旧行默认 executable |
| sort_order | 非空、非负，旧行默认 0，表示建议展示顺序 |

不修改冻结 `0001_baseline`、baseline_models 或 env。业务服务另行保证父容器存在、仅两级、最多20个子任务及父子 DDL 一致性。实际迁移前仍创建 SQLite 在线备份；降级继续拒绝破坏性删除，需使用升级前备份恢复旧版本。

JSON 导出现在为 **format_version=2**，仍含全部26张业务表（不含 alembic_version），包含任务层级与已有草案 JSON。

- v2：严格校验当前表集合、全部列、类型、主键和引用，额外验证任务树、时长、分段资料以及父容器不得含执行/日程事实。
- v1：先使用冻结 baseline_models 严格校验原表集合与原字段；通过后仅给 tasks 补 `parent_task_id=null, task_kind=executable, sort_order=0`，再执行完整 v2 校验与恢复。不能把新版 JSON 改个版本号冒充 v1。
- 同一事务中替换全部行，保留原 ID 及自引用关系，延迟外键检查；任一失败完整回滚。恢复提高全局版本，待确认排程候选和 ready 修改/拆解草案变 stale，运行中请求变 interrupted。

真实旧样例 `backend/tests/fixtures/legacy_v1_snapshot.json` 在本轮修改模型前，使用提交 `1a3d770` 的原 v1 导出函数和匿名隔离库生成；包含任务42、正式计划7、历史片段8、反馈5和锁定资料。测试用冻结模型重建旧库，验证升级、重复检查、v1导入、v2父子恢复与失败回滚。另在旧库副本显式运行 scripts/migrate.py 两次。所有迁移/恢复验收都未指向正常 app.db。

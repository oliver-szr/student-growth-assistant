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

启动 FastAPI 也调用同一升级入口。空库执行 `0001_baseline` 建表；已有库先检查列、类型、主键、外键，仅接受已知旧结构，再补齐已知阶段字段和索引。成功才记录 Alembic 版本。重复执行不会重复导入任务或清空数据。达到 head 后仍检查模型字段与类型，不能靠一个版本号掩盖不匹配结构。

## 备份和失败处理

实际迁移前通过 SQLite 在线备份 API 生成备份，独立于正常每日备份次数限制。新安装默认备份位置为 `scripts/.runtime/backups`；若已有旧默认备份目录则继续使用该目录，既有备份不被移动或隐藏。可以使用 `SGA_BACKUP_DIR` 指定本地目录。数据库、备份和日志均不加入 Git。

遇到未知结构时拒绝迁移，不使用 `stamp head` 跳过检查。保留原库和备份，先核对版本及字段；不要删除数据库来消除错误。迁移失败不会把该库宣称为已升级。

本轮拆分设置保存于既有任务排程资料 JSON，任务 ID 和历史执行快照保持不变。旧任务没有拆分字段时仍按连续任务处理。数据导出格式保留兼容：新字段为可选资料，导入会校验时长、拆分参数及引用，非法数据整份回滚。

## 正常库和演示库

正常环境使用真实北京时间。演示环境必须指定独立演示库和模拟时钟，不替换正常库。浏览器验收脚本创建新演示库，停止脚本只关闭身份记录匹配的预览进程，旧实例数据留在本地。

恢复请通过“我的档案”的数据恢复入口进行，不在运行中直接覆盖 SQLite 文件。恢复会提高全局版本并使旧候选、旧运行失效。对话草稿要重新读取正式数据后计算。

## 后续版本维护

迁移目录位于 `backend/alembic`；`baseline_models.py` 是冻结的基线，不随业务模型变化而修改。新增结构应增加新的 revision，并先验证空库、旧库、重复升级和失败备份。`growth_migrations` 保留既有数据初始化和历史转换；应用启动不再直接调用旧建表／加列流程。

本次目录整理仅搬迁 Alembic 资源并修复路径，三个冻结文件保持原字节内容，没有增加 revision、修改 Schema、改变导出格式或在个人库上执行验证。旧本地演示路径仍兼容，新演示默认写入 scripts/.runtime。

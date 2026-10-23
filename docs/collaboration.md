# 小组协作

项目远程以 `git remote -v` 的实际结果为准。当前工作分支为 `feat/planning-growth-upgrade`；已经存在时直接使用，不重复创建或覆盖。组员先检查本地状态，再决定同步与修改。

```powershell
git status
git branch --show-current
git remote -v
git log -5 --oneline
```

- Commit 只保存在本地；Push 才上传远程；Pull Request 供同学审核和合并。不要直接在 main 开发。
- 每项改动先运行相关测试及构建，核对 `git diff`、`git diff --check`，只暂存明确检查的文件。
- 保留未提交工作，不用 `reset --hard`、`clean -fd` 或 force push 处理一般问题。
- `.env`、数据库、个人课表、日志、node_modules 和本地验收产物不进入提交。换电脑需要自备配置，不能把 API Key 写进说明或示例。
- 本轮整理只做独立本地提交，不 Push、创建 PR 或合并 main。后续统一上传由项目负责人明确安排，再由同学审核。
- 目录移动后的实际入口见 [README](../README.md)，业务边界见 [架构](architecture.md)。历史文件可从 Git 历史查阅，不必将全部旧资料留在工作树。

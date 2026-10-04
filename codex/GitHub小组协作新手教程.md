# GitHub 小组协作新手教程

适用项目：https://github.com/oliver-szr/student-growth-assistant

仓库属于你的朋友。你在自己的电脑上改代码，通过独立分支提交给朋友；朋友检查并合并后，大家同步同一份正式代码。第一次推荐使用 GitHub Desktop，主要通过点击按钮完成。

## 1. 先认识六个词

| 名称 | 通俗解释 |
|---|---|
| 仓库 Repository | 项目代码、说明和修改历史的集合 |
| 本地 Local | 你电脑里的项目文件 |
| 分支 Branch | 一条独立的修改线，让你的工作可以先单独检查 |
| 提交 Commit | 给一批修改保存一个带说明的历史版本；此时还只在电脑上 |
| 推送 Push | 将已经提交的版本上传到 GitHub |
| PR / Pull Request | 请求把你的分支合并进正式分支；大家可以讨论和检查 |

还会看到 Fetch（检查服务器上的更新）、Pull（把远程更新下载并合入当前分支）、Merge（合并）。`origin` 是本地给远程仓库起的名称，与你是不是仓库主人无关。

这次协作的流程：

```text
朋友邀请你 → 你接受邀请 → 检查本地修改 → Commit
→ 推送你的分支 → 创建 PR → 朋友检查并合并 → 大家更新 main
```

## 2. 你现在已经有哪些东西

本地项目位置：

```text
<你的本地项目目录>/student-growth-assistant
```

已核对：远程地址 `origin` 已经是朋友的仓库；当前分支是 `feat/ai-schedule-assistant`，远程默认分支为 `main`。本地还有未提交的修改。

所以第一次交接直接使用这个目录和这个分支。不需要再创建一个仓库，也不需要重新克隆到现在的项目目录。朋友是否已经邀请你、你的账号是否有写入权限，本教程没有代替你验证。

## 3. 第一步：请朋友邀请你的账号

先注册并登录自己的 GitHub 账号，把用户名发给朋友。

朋友打开仓库，在 **Settings → Collaborators → Add people** 中搜索你的用户名并发出邀请。你登录自己的账号，通过邀请邮件或 GitHub 邀请页面接受。接受后才获得直接推送权限。

你可以直接发给朋友：

> 请把我的 GitHub 账号「填写你的用户名」加入 student-growth-assistant 的 Collaborators。我会把代码提交到 feat/ai-schedule-assistant 分支，再发 PR 给你检查合并。

[官方邀请步骤](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/inviting-collaborators-to-a-personal-repository)

## 4. 第二步：安装 Desktop，加入已有本地项目

1. 从 https://desktop.github.com/ 下载 GitHub Desktop，安装后选择 **Sign in to GitHub.com**，登录你刚刚接受邀请的账号。
2. 点击 **File → Add local repository**。
3. 选择上面完整的 `student-growth-assistant` 文件夹，点击 **Add repository**。
4. 顶部的 **Current Repository** 应为本项目，**Current Branch** 应为 `feat/ai-schedule-assistant`。
5. 左侧 **Changes** 会列出本地修改；点击某个文件，右侧可查看修改前后。

如果提示“不是 Git 仓库”，先检查选中的目录。不要直接点击创建新仓库，应该选现有项目的根目录。

[官方加入已有仓库步骤](https://docs.github.com/en/desktop/adding-and-cloning-repositories/adding-a-repository-from-your-local-computer-to-github-desktop)

## 5. 第三步：检查文件，保存本地提交

确认仍在 `feat/ai-schedule-assistant` 分支，再查看 Changes 中的文件。

应提交：前后端源码、测试、依赖清单、配置示例、使用说明、公共演示脚本。

不要提交：`backend/.env`、API 密钥、个人数据库、原始个人课表、个人导出文件、日志、测试缓存、`.venv`、`node_modules`。配置示例 `.env.example` 可以提交，但其中不能含真实密钥。

当前 `.gitignore` 已排除主要配置、数据库和运行目录，但新增资料和历史已跟踪文件仍需检查。不要为了排除文件点击 **Discard changes**：那会删除本地修改；应取消文件前面的勾选，必要时补充忽略规则。

本次修改较多，先检查文件，再提交；不要默认全选所有内容。

左下角 **Summary** 填写：

```text
升级个人成长助手与三页AI工作台
```

Description 可填写：

```text
新增目标、执行记录、个性化偏好及规划/复盘/资料聊天草案。
用户确认后保存，保留原有排程约束与手动入口。
剩余功能和真实AI验收限制见 codex/三页AI对话工作台实施记录.md。
```

点击 **Commit to feat/ai-schedule-assistant**。如果一次只提交部分文件，可检查剩余 Changes 后继续提交，直到准备交接的代码和文档都包含进去。

成功标志：提交出现在 **History** 中。Commit 只保存本地历史，朋友此时还看不到新代码。

## 6. 第四步：上传你的分支

点击顶部 **Publish branch** 或 **Push origin**，实际按钮取决于这个分支是否已经存在于远程。已有朋友仓库，不需要发布一个新仓库，也不要切换成另一个远程地址。

成功后，在 GitHub 仓库的分支下拉框中选择 `feat/ai-schedule-assistant`，应能看到你刚提交的版本。朋友也能查看这个分支。

这时 `main` 不会自动变成你的版本；上传分支与合并正式代码是两步。

[官方提交与推送说明](https://docs.github.com/en/desktop/making-changes-in-a-branch/committing-and-reviewing-changes-to-your-project-in-github-desktop)

## 7. 第五步：创建 PR，请朋友整合

Desktop 中点击 **Preview Pull Request → Create Pull Request**；也可在 GitHub 仓库进入 **Pull requests → New pull request**。

核对方向：

```text
base：main                         接收修改的正式分支
compare：feat/ai-schedule-assistant  你的修改分支
```

标题可以填“个人成长助手升级：目标、执行反馈与三页 AI 工作台”。说明写清做了什么、如何启动、如何测试、还有哪些限制。若希望朋友继续整合未完成内容，可创建 Draft PR，明确它仍需完善。

本项目的交接说明至少指出：新资料与复盘聊天只覆盖已实现范围；部分功能仍使用手动入口；新聊天的真实模型验收尚未通过。不要把模拟测试通过写成真实 AI 已通过。

创建后，把 PR 链接发给朋友。朋友查看 **Files changed**、运行测试、提出评论；你在同一分支修改、Commit、Push，PR 会自动包含这些新提交。满足你们约定的合并条件后，由朋友合并。

[官方创建 PR 步骤](https://docs.github.com/en/desktop/working-with-your-remote-repository-on-github-or-github-enterprise/creating-an-issue-or-pull-request-from-github-desktop)

## 8. 合并后，怎样开始下一项合作

完成当前工作并保存提交，确认没有需要处理的未提交修改后：

1. 在 Desktop 切换 **Current Branch → main**。
2. 点击 **Fetch origin**；出现 **Pull origin** 时点击它，将朋友合并后的正式代码下载下来。
3. 从更新后的 `main` 通过 **Branch → New branch** 创建新分支，例如 `feat/review-chat` 或 `fix/calendar-conflict`。
4. 改代码、运行相关检查、Commit、Push、创建新的 PR。

如果切换分支提示有未提交修改，先留在当前分支处理并保存这些工作，弄清楚它们属于哪个功能；不要盲目选择丢弃或把它们带到 main。

你们可以简单分工：你负责 AI 对话和个性化，朋友负责整体整合与正式版本。用 Issues 写清一项任务、负责人、完成标准，减少两个人同时修改同一个大文件。

## 9. 常见问题

| 遇到的情况 | 怎么处理 |
|---|---|
| Permission denied / 403 | 核对 Desktop 登录账号，确认朋友的邀请已经接受 |
| Commit 之后朋友看不到 | 还要 Push；并让朋友选择你的分支，而不是只看 main |
| Push 被拒绝，因为远程有新提交 | 先保存本地工作并 Fetch，核对当前分支的更新；不要使用 Force push 强行覆盖 |
| 出现 merge conflict | 两个人改到了同一部分，需要对照双方修改选择最终内容，处理完再测试；不能只删除冲突标记就算完成 |
| 朋友下载代码后 AI 不能使用 | 他需要按 README 安装依赖，并在自己的 backend/.env 配置模型；密钥不通过仓库共享 |
| 朋友没有给写入权限 | 可 Fork 到自己的账号，从 Fork 提交 PR；第一次小组合作优先采用邀请协作者的方式 |

## 10. 你现在最先做什么

先让朋友邀请你的账号并接受，再用 Desktop 加入现有本地目录。然后检查 Changes，把本次修改提交并上传到 `feat/ai-schedule-assistant`，最后创建 PR 交给朋友。

本教程只说明操作步骤，没有替你提交、推送或创建 PR。

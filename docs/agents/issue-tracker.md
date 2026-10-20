# Issue 跟踪器：GitHub

本仓库的 issue 和规格都以 GitHub issue 的形式存在。所有操作都使用 `gh` CLI。

## 约定

- **创建一个 issue**：`gh issue create --title "..." --body "..."`。多行正文使用 heredoc。
- **读取一个 issue**：`gh issue view <number> --comments`，用 `jq` 过滤评论，并且同时获取标签。
- **列出 issue**：`gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`，并配上合适的 `--label` 和 `--state` 过滤条件。
- **在 issue 上评论**：`gh issue comment <number> --body "..."`
- **添加 / 移除标签**：`gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **关闭**：`gh issue close <number> --comment "..."`

从 `git remote -v` 推断仓库；在克隆目录内运行时，`gh` 会自动这么做。

## 把 PR 当作分诊界面

**PRs as a request surface: no.** _（如果本仓库把外部 PR 当作功能请求处理，就把它设为 `yes`；`/triage` 会读这个标志。）_

当设为 `yes` 时，PR 会像 issue 一样流经同一套标签和状态，使用 `gh pr` 的对应命令：

- **读取一个 PR**：`gh pr view <number> --comments`，用 `gh pr diff <number>` 看 diff。
- **列出供分诊的外部 PR**：`gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`，然后只保留 `authorAssociation` 为 `CONTRIBUTOR`、`FIRST_TIME_CONTRIBUTOR` 或 `NONE` 的（丢掉 `OWNER`/`MEMBER`/`COLLABORATOR`）。
- **评论 / 打标签 / 关闭**：`gh pr comment`、`gh pr edit --add-label`/`--remove-label`、`gh pr close`。

GitHub 的 issue 和 PR 共用一个编号空间，所以一个光秃秃的 `#42` 可能是两者中的任何一个：先用 `gh pr view 42` 解析，再回退到 `gh issue view 42`。

## 当某个技能说“publish to the issue tracker”时

创建一个 GitHub issue。

## 当某个技能说“fetch the relevant ticket”时

运行 `gh issue view <number> --comments`。

## Wayfinding operations

由 `/wayfinder` 使用。**地图**是一个单独的 issue，以**子** issue 作为工单。

- **地图**：一个打了 `wayfinder:map` 标签的单独 issue，正文包含 Notes / Decisions-so-far / Fog 这几段。`gh issue create --label wayfinder:map`。
- **子工单**：一个作为 GitHub 子 issue 链接到地图上的 issue（在 sub-issues 端点上用 `gh api`）。如果子 issue 未启用，就把子项加进地图正文的一个任务列表，并在子项正文顶部写上 `Part of #<map>`。标签：`wayfinder:<type>`（`research`/`prototype`/`grilling`/`task`）。一旦被领取，该工单就会指派给驱动它的开发者。
- **阻塞**：GitHub 的**原生 issue 依赖**，这是规范且界面上可见的表示方式。用 `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>` 添加一条边，其中 `<blocker-db-id>` 是阻塞者的数字**数据库 id**（`gh api repos/<owner>/<repo>/issues/<n> --jq .id`，_不是_ `#number` 或 `node_id`）。GitHub 会报告 `issue_dependencies_summary.blocked_by`（只含未关闭的阻塞者，即实时的闸门）。如果依赖功能不可用，就回退为在子项正文顶部写一行 `Blocked by: #<n>, #<n>`。当每一个阻塞者都关闭时，工单就不再被阻塞。
- **前沿查询**：列出地图的未关闭子项（`gh issue list --state open`，范围限定在地图的子 issue / 任务列表内），丢掉任何带有未关闭阻塞者（`issue_dependencies_summary.blocked_by > 0`，或 `Blocked by` 那一行里有未关闭的 issue）或已指派给某人的；地图顺序里最靠前的胜出。
- **领取**：`gh issue edit <n> --add-assignee @me`，这是本会话的第一次写入。
- **解决**：`gh issue comment <n> --body "<answer>"`，然后 `gh issue close <n>`，再把一个上下文指针（要点 + 链接）追加到地图的 Decisions-so-far 里。

## 历史存档：`.scratch/`

`.scratch/` 下的 markdown 文件（例如 `.scratch/workbench-v1/spec.md` 与其 `issues/` 下的 TB 工单）是切换跟踪器之前的**历史存档**，只读参考，不再更新，也不回填成 GitHub issue。新的 issue 和规格一律走 `gh`。

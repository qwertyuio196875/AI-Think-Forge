# Issue 跟踪器：本地 Markdown

本仓库的 issue 和规格以 `.scratch/` 下的 markdown 文件形式存在。

## 约定

- 每个功能一个目录：`.scratch/<feature-slug>/`
- 规格是 `.scratch/<feature-slug>/spec.md`
- 实现 issue 是每个工单一个文件，位于 `.scratch/<feature-slug>/issues/<NN>-<slug>.md`，从 `01` 开始编号，绝不使用单个合并的工单文件
- 分诊状态记录为每个 issue 文件顶部附近的 `Status:` 行（角色字符串见 `triage-labels.md`）
- 评论和对话历史追加到文件底部，放在 `## Comments` 标题下

## 当某个技能说“publish to the issue tracker”时

在 `.scratch/<feature-slug>/` 下创建一个新文件（需要时创建该目录）。

## 当某个技能说“fetch the relevant ticket”时

读取被引用路径上的文件。用户通常会直接传入路径或 issue 编号。

## Wayfinding operations

由 `/wayfinder` 使用。**地图**是一个文件，每个工单对应一个**子**文件。

- **地图**：`.scratch/<effort>/map.md`（正文为 Notes / Decisions-so-far / Fog 这几段）。
- **子工单**：`.scratch/<effort>/issues/NN-<slug>.md`，从 `01` 开始编号，正文里写着问题。`Type:` 行记录工单类型（`research`/`prototype`/`grilling`/`task`）；`Status:` 行记录 `claimed`/`resolved`。
- **阻塞**：顶部附近的一行 `Blocked by: NN, NN`。当它列出的每一个文件都是 `resolved` 时，工单就不再被阻塞。
- **前沿**：扫描 `.scratch/<effort>/issues/`，找出未关闭、未被阻塞、也未被领取的文件；编号最靠前的胜出。
- **领取**：在做任何工作之前，设置 `Status: claimed` 并保存。
- **解决**：把答案追加在 `## Answer` 标题下，设置 `Status: resolved`，然后把一个上下文指针（要点 + 链接）追加到 `map.md` 里地图的 Decisions-so-far 中。

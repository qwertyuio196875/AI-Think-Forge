# 0004. 输出格式扩为四种，PPT 改走 HTML 逐页截图（图片型、文字不可编辑）

- 状态：已接受
- 日期：2026-10-20
- 与 ADR-0003 的关系：取代其「HTML deck 与 PPTX 分轨，互不转换」与「PPTX 推迟至 v1.1」两条；其余部分继续有效

## 背景

ADR-0003 以「7 天期限 + OpenDesign 仓库中不存在 .pptx 模板」为由，把 PPTX 推到 v1.1，并立下「HTML deck 与 PPTX 分轨，互不转换」。本次需求改为：

- 「PPT 功能是直接将 html 转成的」；
- 生成 PPT 时用户可选页数。

核实到的代码事实：

- 生成侧完全没有 pptx：`generations.format` 的 CHECK 只允许 `docx` / `html`（`backend/app/db/database.py:138`），前端格式选择里 pptx 被灰置并标注「v1.1 计划」；
- 前端还留着一句明确否认该路线的文案：「v1 不生成 .pptx，也不会把 HTML 或截图冒充 PPT」（`frontend/src/components/GenerationPanel.vue:37-43`）；
- 现有 deck 是确定性渲染：`slides_from_plan`（`backend/app/generation/deck.py:100-143`）按 H1/H2 切页，页数是章节的副产品，无法控制。

「由 HTML 转成可编辑 pptx」的三条路线中，转换器（LibreOffice 的 HTML 导入基本不保留版式，商用 SDK 要付费）风险最高，且与「版式不能崩」的目标相冲突。用户选定**截图路线**。

## 决策

- 四条输出路线同源，一次内容生成多路导出：
  - **HTML deck** 为一等产物（可预览、可迭代、浏览器演示）；
  - **Word** 由正文 Markdown 按模板渲染；
  - **PPTX** 由 deck 逐页截图后装配（图片型）；
  - **PDF** 由 deck 打印导出（可选）。
- **PPT 一律是截图版**：Playwright + 内置 Chromium（headless），CSS 视口 1280×720、`deviceScaleFactor=2`，出 2560×1440 PNG，嵌入 pptx 为 13.333×7.5 英寸满幅页面。
- **逐页截图按元素边界**：每页是固定尺寸的 `<section>`，用 `element.screenshot()` 截取元素边界，不依赖滚动位置与吸顶元素；不为每页单独生成 HTML 文件。
- **页面规划显式化**：模型先输出「章节 → 页列表」的 JSON 页面规划，再据此渲染 deck，最后截图。页数为硬约束：页数少于章节数时按章节主次合并，多于章节数时给重点章节拆页。用户可在预览里增删单页后重新截图（截图是确定性的，重截成本低）。
- **字体只用 Windows 自带中文字体**（微软雅黑 / 宋体 / 等线），deck 不内联字体，保证截图与用户本机预览一致。
- **交付组合**：HTML deck、截图版 .pptx、可选 PDF 一并给出。

## 后果

- 「PPT」对外口径必须写明是图片型、文字不可编辑、不可检索。`frontend/src/components/GenerationPanel.vue:37-43` 那段相反文案必须删除，否则界面与行为直接矛盾。
- 页数由「章节 → 页列表」控制，`slides_from_plan` 的 H1/H2 自动切页退为兜底路径（页面规划缺失时使用），不再是被选中的主体路径。
- pptx 体积随页数与 2x 分辨率上升：20 页量级可达数十 MB，邮件/即时通讯传输需说明。
- 新增依赖：`playwright` + 约 150MB 的 Chromium。首次安装需联网下载或预置离线包；失败模式要给出明确提示，不得静默降级成「没有 PPT」。
- ADR-0003 的判断并非错误，只是前提变了（期限让位于能力）。「HTML 为一等产物」「内联字体换离线的取舍」两条结论继续有效。
- 截图路线把「版式保真」和「可编辑」彻底分开：需要改字时走 Word，需要改版时改 deck 后重截，不存在「在 PowerPoint 里微调」这条路径。

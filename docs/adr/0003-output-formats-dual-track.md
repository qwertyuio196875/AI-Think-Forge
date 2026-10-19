# 0003. 输出格式双轨：首版 Word + 单文件 HTML，PPTX 推迟且与 OpenDesign 分道

- 状态：已接受
- 日期：2026-10-19

## 背景

原文档承诺 Word、PPT、HTML 三种成品均基于用户模板；补充修订要求"PPT 与 HTML 优先使用 OpenDesign 模板"。经对 `nexu-io/open-design` 仓库的核实：

- 许可为 Apache-2.0（无 AGPL 传染），附属资源多为 MIT/OFL，可安全借鉴；
- 但其"PPT 模板"实为**自研静态 HTML deck 框架**（html-ppt：36 主题 CSS、31 版式、runtime.js 键盘导航/演讲者模式）+ 设计系统 + Agent 技能，**仓库中不存在 .pptx 模板**；
- PPTX 生成在其体系内也是 python-pptx/agent 技能路线，且字体走 Google Fonts CDN，离线单文件须自托管内联；
- 7 天期限内三格式全量保真不可行。

## 决策

- **首版成品 = Word（python-docx + 用户自备模板） + 单文件 HTML**。HTML 从 OpenDesign 主题族选一套适配（字体/CSS/JS 内联，遵守各自许可并保留署名），支持 file:// 双击打开。
- **PPTX 输出推迟至 v1.1**，路线为 python-pptx 填充用户自备的 .pptx 模板（呼应原文档），不承诺复杂版式无损保真，不支持不了的结构明示降级。
- **HTML deck 与 PPTX 分轨，互不转换**：汇报演示需求由单文件 HTML 承担；确需 Office 可编辑的 .pptx 时才触发 v1.1 路线。

## 后果

- 首版"PPT"一词的对外口径收敛为"单文件 HTML 演示"，与原文档字面承诺有落差，验收时须向用户（本项目所有者本人）明示。
- 内联字体带来 HTML 体积上升（约 MB 级），换取完全离线，属有意取舍。
- v1.1 的 PPTX 保真度上限由 python-pptx 能力与用户模板质量决定，需求描述不得超出已验证能力。

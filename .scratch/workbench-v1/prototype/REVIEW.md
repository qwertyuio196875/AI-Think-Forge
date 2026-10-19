# 原型评审标注（待修订）

来源：用户 2026-10-19 在应用内浏览器对 `index.html` 的标注。尚未修订——用户已暂停派工，等其放行后再动。

## A1 · 折叠后点击品牌标记可展开

- 标注元素：`body > div.shell > aside.sidebar > div.side-head > div.mark`
- 原文："要求折叠后点击此处可以展开"
- 落地口径：折叠成窄条后 `.mark` 即展开控件——button 语义、`aria-label="展开侧栏"`、`cursor:pointer`、hover 有可点暗示、`:focus-visible` 焦点环、键盘可触发。

## A2 · 折叠控件移入左侧导航栏

- 标注元素：`button#railToggle2`（`section.view > div.view-head > div.head-row > div.head-actions`）
- 原文："位置不合理，移动到左侧导航栏"
- 落地口径：从内容区头部移除，移入左栏 `.side-head` 一行（右端对齐）；全站只保留这一处折叠控件，`aria-expanded` 与 `.mark` 同步。

## 约束

不改动其它视觉与文案；沿用现有 CSS 变量与 Element Plus 观感。这两条同时约束 TB-0 真实实现的侧栏交互（规格 08 未涉及折叠细节，以本文件为准）。
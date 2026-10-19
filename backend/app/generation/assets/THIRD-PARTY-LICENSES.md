# 第三方许可与署名（单文件 HTML 演示主题族）

本文件覆盖 `backend/app/generation/` 下单文件 HTML 演示（TB-6）所用与所改编的第三方资产。
许可全文随包分发在 `licenses/` 目录；字体二进制在 `fonts/` 目录。

## 1. 版式骨架与翻页运行时（改编来源）

单文件 HTML 演示的**版式骨架与翻页运行时**（绝对定位幻灯片 + `.active` / `.prev` 状态、
页码计数、进度条、键盘翻页监听）改编自 OpenDesign 仓库的扁平主题示例：

| 本项目主题 | 改编来源 | 许可 | 版权行 |
| --- | --- | --- | --- |
| `slate`（Slate 极简） | `design-templates/html-ppt-zhangzara-blue-professional/example.html` | MIT | `Copyright (c) 2026 Zara Zhang` |
| `ember`（Ember 暖调） | `design-templates/html-ppt-zhangzara-coral/example.html` | MIT | `Copyright (c) 2026 Zara Zhang` |
| `mono`（Mono 等宽） | `design-templates/html-ppt-zhangzara-studio/example.html` | MIT | `Copyright (c) 2026 Zara Zhang` |

- 上游仓库：`nexu-io/open-design`，仓库主体 **Apache-2.0**（全文见
  `licenses/Apache-2.0-OpenDesign.txt`）；上述三个目录各自带 **MIT** 许可
  （全文见 `licenses/MIT-OpenDesign-html-ppt-zhangzara.txt`）。
- **本项目改动**：原主题的私有 CSS、Google Fonts 外链与示例文案**一律弃用**；调色板按本项目
  原型 `DECKT` 重设，CSS、字体栈与页内演讲者模式为本项目本地原创，**不做像素级复刻**。
- 署名同时保留在**每一份生成的 HTML 产物**的注释块里（含主题来源与字体署名）。

### 依赖白名单纪律

- 白名单只放 MIT 族（`html-ppt` / `html-ppt-zhangzara-*` / `lewislulu/html-ppt-skill` /
  `zarazhangrui/beautiful-html-templates`）。
- `design-templates/guizang-ppt/` **一律排除**：仓库内副本标 MIT，但上游
  `op7418/guizang-ppt-skill` 实测为 **AGPL-3.0**，许可冲突未解决 → 按最保守口径不使用。
- 本单未内联任何 JavaScript 第三方库（翻页运行时为本项目自写），故不涉及
  highlight.js / three.js / GSAP 等库的许可问题；GSAP 的 SplitText / ScrollTrigger 有额外
  商业条款，本项目不使用。

## 2. 内联字体（SIL Open Font License 1.1）

产物只内联**实际用到的西文 latin 子集** woff2（base64 内联），中文走系统字体回退。

| 字体 | 子集 / 字重 | 文件 | 许可 | 版权行 |
| --- | --- | --- | --- | --- |
| Inter | latin / 400、700 | `fonts/inter-400-latin.woff2`、`fonts/inter-700-latin.woff2` | OFL-1.1 | `Copyright 2020 The Inter Project Authors` |
| Source Serif 4 | latin / 600 | `fonts/source-serif-4-600-latin.woff2` | OFL-1.1 | `Copyright 2014 The Source Serif 4 Project Authors` |
| JetBrains Mono | latin / 400、700 | `fonts/jetbrains-mono-400-latin.woff2`、`fonts/jetbrains-mono-700-latin.woff2` | OFL-1.1 | `Copyright 2020 The JetBrains Mono Project Authors` |

许可全文：`licenses/OFL-Inter.txt`、`licenses/OFL-SourceSerif4.txt`、
`licenses/OFL-JetBrainsMono.txt`。字体按 OFL-1.1 随产物内嵌分发，**不单独售卖字体**，
不修改字体的保留名称。

## 3. 「本地原创」部分（无第三方许可义务）

- 三套主题的调色板（以 `.scratch/workbench-v1/prototype/index.html` 的 `DECKT` 为准）、
  令牌与 CSS（`backend/app/generation/themes.py`、`deck.py` 的 `_BASE_CSS`）；
- 幻灯片版式的自有实现、方案 → 幻灯片的确定性映射、讲者备注；
- **页内演讲者模式**（`S` 切换的覆盖层 + 计时器 + 讲者备注）：三套 OpenDesign 参照主题
  均未提供演讲者模式，故这部分完全为本项目自写；
- 无外部网络引用的完整性扫描器。

---

## MIT 许可全文（OpenDesign 主题目录）

```text
MIT License

Copyright (c) 2026 Zara Zhang

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
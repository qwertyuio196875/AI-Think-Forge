# TB-6 · 单文件 HTML 演示成品

Status: closed — 已实现（待编排者提交）
规格：08-v1-unified-spec.md
阻塞边：TB-3（12）；与 TB-5（14）互不阻塞

## 窄路径（四层触点）

- **schema**：生成记录复用（格式=html、所用主题模板、产物位置）。
- **API**：对已确认方案生成单文件 HTML；资源内联（样式 / 脚本 / 西文字体），中文用系统字体回退；含网络资源时明确声明；生成后做结构完整性检查。
- **UI**：生成入口、进度、双击打开入口与网络依赖声明展示。
- **测试**：产物文本扫描断言无外部引用；结构完整性检查通过；file:// 直开可用。

## 关键决策落地

- 主题取自 OpenDesign 主题族并适配为本地资产，保留 Apache-2.0 与附属资源各自许可与署名；不做像素级复刻、不做文档型长页。

## 演示证据

确认方案 → 生成 .html → 断网状态下双击打开，键盘翻页与演讲者模式可用。

## 验收

无外部引用断言与完整性检查绿；一次离线演示记录。

## Comments

- 2026-10-19 智能体（TB-6 后端实现）：单文件 HTML 演示落地；顺手修掉 TB-10 遗留 a（`advance` 0 轮次 422）。
  验证：`pytest --no-header` **194 passed**（基线 180，只增不减）；`ruff check backend` **All checks passed**。
  演示记录：`backend\scripts\demo_html_deck.py`（真实生成三套主题的 .html）。

  **实现摘要**
  - 生成记录**复用 `generations`**（不改表结构）：`format=html`、`template_used=deck-theme:<主题 id>`（术语「模板」在 HTML 一轨的载体就是主题，加前缀与 `templates/` 下的 `.docx` 相对路径区分）、`file_path` 指向产物。
  - API：`POST /api/tasks/{id}/generations` body 增 `theme`；**闸门判定与 TB-5 逐字一致**（无方案 / 未确认 → 409，未处置待确认事项 → 409，均由同一 `_require_confirmed_plan` 产出同一 `detail` 文案，已加逐字断言）。未知主题 → **400 明确报错，绝不静默退回默认主题**。新增只读 `GET /api/deck-themes`（三套主题的调色板 / 内联字体 / 来源署名 / 许可 / 网络资源，与生成入口同一份事实，供 TB-6 前端主题选择器读）。
  - 资源内联：样式 / 翻页脚本 / **西文字体 latin 子集 woff2 base64** 全部内联；**中文走系统字体回退**（如 `Inter, "Microsoft YaHei", "PingFang SC", …, system-ui, sans-serif`）；产物 `<meta name="thinkforge:deck">` 与 API 响应记 `inlined_fonts` / `cjk_fallback: true` / `network_resources` / `presenter_mode`。三套主题均**不含网络资源**（`network_resources: []`，产物 `data-network-resources="none"`）；若将来某主题必须保留网络资源，字段已就位、会在产物与记录里明示，不会静默。
  - 结构完整性检查（US 22）：**回读产物文本**——① 外部引用扫描（`http(s)://`、`<link>`、`<script src>`、指向网络的 `src=`/`href=`、`@import`、非 `data:` 的 `url()`）要求 0 条；② `HTMLParser` 解析结构（幻灯片页数与期望一致、首页 `title` / 末页 `end` 布局、keydown 监听与 ← → / PageUp / PageDown / 空格按键齐备、页码存在、`@font-face` 已内联）。任一条不过即抛错 → 服务层**删产物、不落库**、路由 500（负测已覆盖）。
  - 演示能力：键盘翻页（← / → / PageUp / PageDown / 空格，另 Home / End）、页码 + 进度条 + 触屏滑动；**页内演讲者模式**（`S` 切换：当前 / 下一页标题、计时器、讲者备注取自方案正文）。
  - `advance` 缺陷修正：`advance_round` 在「该任务尚无任何轮次」时改走**等价于发起第一轮**的路径（有种子输入才走；没有任何输入的任务仍 422），使 `derive_resume` 的 `awaiting="advance"` 成为真话；若该轮模型也未提问则按「前沿为空即收敛」产出草稿方案（`round_no=0`，由种子输入产生），不留死路。**已答完一轮后的推进行为未改**（既有 TB-3 用例全绿，含 `test_history` / `test_convergence` / `test_open_items` 的推进断言）。
  - 回归测试：`test_history::test_failed_first_round_is_recovered_by_advance_exactly_once`（首轮 502 → 0 轮次 → 点「继续」→ **恰好一轮**、不重复不叠加、`awaiting` 变 `answers`、随后收敛方案恰好一份）、`test_advance_without_rounds_and_empty_frontier_converges_into_draft_plan`、`test_advance_on_task_without_any_input_still_rejected`；新测试文件 `backend/tests/test_generation_html.py`（11 项）。

  **主题来源与署名（如实区分，未伪造 OpenDesign 主题）**
  - 已实际取到上游（`raw.githubusercontent.com` 本机不可达，改用 `api.github.com` 的 raw media type 成功）：
    版式骨架与翻页运行时**改编自** `nexu-io/open-design` 的扁平淡色主题示例
    `design-templates/html-ppt-zhangzara-blue-professional` / `-coral` / `-studio`
    （各自带 **MIT** LICENSE，`Copyright (c) 2026 Zara Zhang`；仓库主体 Apache-2.0）。
    对应关系：`slate` ← blue-professional、`ember` ← coral、`mono` ← studio。
  - **本地原创**：三套主题的调色板（逐值取自原型 `DECKT`：slate `#f6f7f9/#1c2027/#2f6bdf/#dfe4ec`、ember `#fbf6ef/#2a2018/#c4712a/#e9dcc8`、mono `#101319/#e8edf5/#3f9d70/#232b36`）、令牌与全部 CSS、字体栈、方案→幻灯片映射、讲者备注，以及**页内演讲者模式**（三套参照示例**均无**演讲者模式，这部分完全自写）。原主题的私有 CSS、Google Fonts 外链与示例文案一律弃用；**不做像素级复刻**。
  - 未内联任何第三方 JS 库（翻页运行时自写），故不涉及 highlight.js / three.js / GSAP。
  - 许可与署名落地：`backend/app/generation/assets/THIRD-PARTY-LICENSES.md`（含 MIT 全文、Apache-2.0 与 OFL 全文指针、逐项「派生 / 本地原创」区分、**白名单纪律：只放 MIT 族，`guizang-ppt` 一律排除**——上游实测 AGPL-3.0 冲突未解决）、`assets/licenses/`（Apache-2.0、MIT-ZaraZhang、OFL-Inter / OFL-JetBrainsMono / OFL-SourceSerif4 全文）；**每份生成的 HTML 注释块里保留主题来源 + 字体版权行 + 网络资源声明**。

  **内联体积数据（实测）**
  - 西文 woff2 latin 子集（原始 → base64 内联）：slate `Inter 400+700` 48,020 → 64,028 字节（1.33x）；ember `Inter 400 + Source Serif 4 600` 45,196 → 60,264；mono `JetBrains Mono 400+700` 43,076 → 57,436。与调研 B2 的「约 +33%」一致。
  - 产物总体积：slate **77,067 字节（75.3 KB）**、ember 73,395、mono 70,557；远低于 OpenDesign 自检限额（入口 2 MiB / 产物 100 MiB）。
  - 中文未内联：单字重 CJK 全量约 2.3 MB（base64 约 3.1 MB）且会丧失 `unicode-range` 分片按需加载，故走系统字体回退（`cjk_fallback: true`）。
  - 字体文件随包分发在 `backend/app/generation/assets/fonts/`（5 个 woff2，共 112,628 字节），运行时读盘内联、**不联网**。

  **验证证据（真实输出）**
  - `backend\.venv\Scripts\python.exe -m pytest --no-header` → `194 passed in 27.05s`（基线 180）。
  - `backend\.venv\Scripts\python.exe -m ruff check backend` → `All checks passed!`。
  - 演示记录 `backend\scripts\demo_html_deck.py`：三套主题产物路径 / 体积 / 内联字体清单 / **外部网络引用扫描 0 条** / `cjk_fallback=True` / 页数 5 / 布局序列 `['title','list','quote','list','end']` / 离线可用证据（脚本内联、键盘监听、按键集合、页码、演讲者覆盖层全为 True）/ 未知主题 400 / 无方案 409 / 记录 3 份 `template_used=deck-theme:{slate,ember,mono}`。
  - **测试敏感度自证（临时破坏 → 转红 → 已还原）**：① 把 `font_data_uri` 临时改成返回 Google Fonts URL（等于不内联字体）→ `test_generation_html.py` **5 failed / 6 passed**；② 把 `verify_html_deliverable` 的外部引用扫描临时置空 → `test_verifier_flags_injected_external_reference` **DID NOT RAISE → 1 failed**。两处还原后 11 passed。
  - **断网直开等价证据（含真机渲染）**：产物文本 `https://`/`http://`/`<link`/`@import` 命中数均为 0；`<script>` 无 `src`；`@font-face` 只有 `src:url(data:font/woff2;base64,…)`。另把产物经本地静态服务在本会话浏览器面板真开：标题页渲染正常、点「下一页」页码 `1 / 5 → 2 / 5`、点 `S` 演讲者覆盖层显示（计时器 `00:12`、下一页标题、讲者备注取自方案正文）；服务日志显示页面**未发起任何字体/CDN 请求**（只有浏览器自身的 favicon 404），即断网 `file://` 双击可用的等价证据。mono 主题实测标题计算样式 `color: rgb(232,237,245)`、`font-family: "JetBrains Mono", …, "Microsoft YaHei", …`、`font-weight: 700`（内联字体生效 + 中文回退生效）。
  - 修掉 TB-5 里的占位测试：`test_html_format_is_not_implemented_yet`（断言 501）改为 `test_html_track_is_served_by_the_builtin_theme_family`（断言 201 与 `.html` 产物），语义随实现更新而非「为过测试改断言」。

  **遗留 / 风险**
  1. **UI 未做**（本单写域只含 `backend/**`）：生成面板的格式 / 主题选择、进度、双击打开入口、网络依赖声明展示、设置页「默认模板」区由 TB-6 前端（@designer）承接；后端已把主题清单与产物元数据备齐（`GET /api/deck-themes`、生成响应字段）。
  2. 演讲者模式为**页内覆盖层**（`presenter_mode: "in-page-overlay"`），非独立投屏窗口；三套参照主题均无演讲者模式，故按原型口径「尽力而为」实现并如实标注，未做投影双窗同步。
  3. 主题族只做 3 套（原型口径），**不做** OpenDesign 的几十套市场化选择；也不做「用户自备 HTML 主题」入口。
  4. 方案→幻灯片映射是**结构性**的（H1 标题页 / H2 章节页 / H3 页内小标题 / 列表 / 表格 / 段落），不做分页字数控制、图片、图表或演讲备注的人工编辑；长章节可能溢出单页（`overflow:hidden`），需要人工删减方案文字或后续做「按篇幅分页」。
  5. `generations` 表未新增列，HTML 一轨的 `inlined_fonts` / `cjk_fallback` / `slides` / `external_resources` 只在**生成响应**与**产物元数据**里，`GET /api/tasks/{id}/generations` 复读时只有 `template_used`（`deck-theme:<id>`）可推断主题；若前端需要在成品卡上展示内联字体清单，需再补列或让前端在生成当次缓存（当时判断为不值得为此改表）。
  6. `templates` 表 / `GET /api/templates` 仍只覆盖 `.docx`（`discover_templates` 扫的是模板目录里的文件）；HTML 主题不进模板登记表，也**不做**全局默认主题设置（生成时未指定 `theme` 即用 `slate`）。若产品要「默认 HTML 主题」，需另加设置项。
  7. 字体资产为随包分发的二进制（5 个 woff2，112 KB）。若将来要换字体/加主题，须同步更新 `THIRD-PARTY-LICENSES.md` 与 `licenses/`（当前 OFL-1.1 三族）。

### 2026-10-19 · 评审补齐：HTML 全局默认主题（US20）

**提交**：`f56b66c`（后端）→ `8989305`；前端 `de06390` + `17f85a0` → 合并 `0e941b6`。

- 原「不做全局默认主题」的决定**已被本单覆盖**：`settings.deck_theme_default` 保存全局默认，`GET/PUT /api/settings/deck-theme` 读写，非法主题 400。
- 生成请求未显式给 `theme` 时使用全局默认；显式主题只覆盖本次。实际主题仍记入 `generations.template_used=deck-theme:<id>`。
- UI：生成面板主题区首项为「跟随全局默认主题」，并显示「当前：Ember 暖调」；`theme` 初始为空、不再自动选第一个；设置页「单文件 HTML 演示 · 全局默认主题」可真实读写。
- 真机联调：设置全局默认 `ember` → 确认方案任务生成 HTML → 产物实际使用 Ember，页面显示 `已使用 Ember 暖调`；请求体 `theme: null` 由前端单测覆盖。
- 测试：`backend/tests/test_deck_theme_settings.py` 4 项；前端 `workbenchGaps.test.mts` 覆盖 theme 空值与 API 读写。
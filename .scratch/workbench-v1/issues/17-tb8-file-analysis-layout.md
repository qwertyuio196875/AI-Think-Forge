# TB-8 · 资料分析：版式类文件（PDF / PPTX）

Status: closed — 已实现并合入 integration/workbench-v1
规格：08-v1-unified-spec.md
阻塞边：TB-7（16，复用其分块-总结-引用路径）

## 窄路径（四层触点）

- **schema**：沿用来源 / 文档 / 分块 / 总结 / 引用表，新增解析器标识与页级 locator 语义。
- **API**：解析 PDF 正文与标题；解析 PPTX 每页标题、正文、可可靠识别的表格；扫描件 / 图片 / 无法可靠识别的内容明示"未识别"，不得描述成已完整分析。
- **UI**：与 TB-7 同一分析页，来源类型与未识别提示可见。
- **测试**：PDF 与 PPTX 各一例解析断言；页面 / 幻灯片级 locator 可回溯；扫描件样本走明示路径（不做 OCR）。

## 关键决策落地

- 解析库选型于本单开工时定（不引入 OCR，Out of Scope 已排除）。

## 演示证据

传 PDF 与 PPTX 各一份 → 总结可用、引用可回溯到页 / 幻灯片、扫描件被明示未识别。

## 验收

两类解析测试绿；一次真机演示记录。

## Comments

### 2026-10-19 · 后端与 UI 完成并合入集成分支

**提交**：后端 `3b06d6b`；合并 `c675b3f`；共享分析页 UI `dca5596`。

**后端（`backend/app/analysis/parsing.py` 等）**

- `pypdf` 逐页提取文本，按字号相对全文众数字号识别标题；locator 为 `{format:"pdf", page, line}`，分块引用可回溯页 / 行；页内图片计入 `unrecognized_parts`；无文本层 → `no_text_layer` + `needs_ocr=true`，短路零模型调用。
- `python-pptx` 读每页标题占位符、正文、表格逐行；locator 为 `{slide, kind:"title"}` / `{slide, shape, paragraph}` / `{slide, table, row}`；图片 / 图表 / 组合形状 / 嵌入对象逐项明示（不递归展开组合形状）。
- `documents.parser` 记录实际解析器并纳入历史库迁移；上传白名单扩为 `.pdf` / `.pptx`；TXT / MD / DOCX 行为与契约不变。
- 加密 / 损坏 PDF → `parse_status="failed"` + 可读提示，不绕过密码，不丢已存数据。

**UI（`frontend/src/views/AnalysisView.vue`）**

- 文件类型提示与 `accept` 扩到 PDF / PPTX；版式类解析结果显示解析器 chip。
- locator 可读化覆盖页 / 行、跨页区间、幻灯片标题 / 形状 / 表格行；未识别条目按页 / 幻灯片定位。

**验证**

- 后端 `pytest`：**336 passed**（TB-7 基线 217 + TB-8 新增 5 + TB-9 新增 114）；`ruff check`：All checks passed。
- `backend/scripts/demo_analysis_layout.py` 实跑：PDF `parser=pypdf`、页级引用；PPTX `parser=python-pptx`、幻灯片 / 表格引用；扫描件 `unrecognized` + 零模型调用；损坏 PDF 409。
- 前端 `node --test`：38 项通过；`npm run build` 通过。

**遗留**

- PDF 表格按阅读顺序成行文本，不还原表格结构；矢量绘制的图表不计入图片未识别。
- 字号启发式在全文单一字号时返回 `heading_source="none"`，不硬猜。
- 真实模型下的版式类引用展示需持有效 Key 人工走查一次。
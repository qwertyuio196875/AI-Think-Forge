# 06 - 资料分析管线

Status: closed — 已并入 08-v1-unified-spec.md（勿按本单执行；本单为按层切分，已被曳光弹工单取代）

## 目标

上传 DOCX/PDF/TXT/MD/PPTX（校验扩展名+50MB 上限）与 URL 抓取（spec §2 防护清单）；解析正文/标题/结构，PPTX 抽每页标题正文表格；长文分块 map-reduce 总结 ≤500 字，忠实原文、不虚构、未识别内容明示；总结与 chunks（含 locator 引用）落库，一键送入主题创作（新任务预填来源）。PDF 用 PyMuPDF；无 OCR。

## 验收

- 五格式+URL 各一例真实总结；SSRF 负测（环回/私网/元数据）全拦；引用可回溯原始位置。

## Comments

- （待补）

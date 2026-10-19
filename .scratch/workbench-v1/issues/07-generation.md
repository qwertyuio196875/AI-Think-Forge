# 07 - Word 与单文件 HTML deck 生成

Status: ready-for-agent

## 目标

方案确认（04 闸门）后按所选格式生成：**Word** = python-docx 打开 `templates/` 内模板（默认模板=工单 01 内置最小版，用户可换），映射方案结构到标题级别/正文样式；**HTML deck** = 从 OpenDesign html-ppt 主题族取一套适配为本地模板资产（Apache-2.0 署名随文件保留），CSS/JS/西文字体内联、中文系统回退、键盘翻页+演讲者模式，file:// 双击直开；生成后基本完整性检查（结构、必要脚本在场）。记录 generations.template_used。模板缺失/损坏明确报错，不静默退回空白生成。

## 验收

- 一份真实确认方案 → 产出 .docx（可开、样式映射正确）与 .html（双击可翻页、无外部网络依赖）；负测：模板缺失报错路径。

## Comments

- （待补）

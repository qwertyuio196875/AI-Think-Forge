/**
 * 成品格式的展示元数据（工单 30）。
 *
 * 组件 `GenerationPanel.vue` 的格式选择卡、生成按钮文案与文案修正都读这一份，避免各处
 * 硬编码：「哪些格式可选」「每种格式的一句话说明」「哪种格式按主题选」（html / pptx）。
 *
 * 说清楚「可直接编辑 vs 截图版」是 ADR-0004 的对外口径要求：PPT 由 HTML deck 逐页截图装配，
 * 因此卡片说明必须在**选择之前**就写明「图片型、文字不可编辑、不可检索」，并与旧文案
 * （v1 不生成 .pptx）明确切割。
 */

import type { GenerationFormat } from '../api/client'

/** 单个格式选项的展示元数据。 */
export interface GenerationFormatOption {
  format: GenerationFormat
  /** 卡片标题（radio 旁的粗体名）。 */
  title: string
  /** 卡片一句话说明（选择前即可见）。 */
  desc: string
}

/** 成品格式的可选清单与展示文案（顺序即界面顺序：Word / HTML / PPT）。 */
export function formatOptions(): GenerationFormatOption[] {
  return [
    {
      format: 'docx',
      title: 'Word 文档',
      desc: 'python-docx 按模板写入并回读校验；产出 .docx'
    },
    {
      format: 'html',
      title: '单文件 HTML 演示',
      desc: '样式 / 脚本 / 西文字体内联，中文系统字体回退；自包含 .html，file:// 双击可开'
    },
    {
      format: 'pptx',
      title: 'PowerPoint .pptx',
      desc: '截图版 PPT：由 HTML deck 逐页截图装配，页面是图片、文字不可编辑 / 不可检索'
    }
  ]
}

/**
 * 某格式在**成品卡展示**上按什么口径解释：true = 来自 deck（主题即模板）。
 *
 * html / pptx / pdf 三者同源（ADR-0004：同一份 deck 分别渲染、截图装配、打印），
 * 记录里的 `template_used` 都是 `deck-theme:<id>`，因此都按主题解释；
 * docx 走 Word 模板目录，按模板解释。
 *
 * 注意：这不等于「生成入口都提供 pdf」——PDF 是可选产物，由独立动作产生，
 * 不出现在格式选择卡里（见 `formatOptions`）。
 */
export function isThemeBased(format: GenerationFormat): boolean {
  return format === 'html' || format === 'pptx' || format === 'pdf'
}

/** 按格式取卡片元数据（未知格式回退到以格式名本身兜底，保持返回类型完整）。 */
export function formatMeta(format: GenerationFormat): GenerationFormatOption {
  return formatOptions().find((o) => o.format === format) ?? {
    format,
    title: format,
    desc: ''
  }
}
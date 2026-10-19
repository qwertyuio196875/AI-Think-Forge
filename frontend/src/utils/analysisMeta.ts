/**
 * 资料分析页的纯展示辅助（术语以 GLOSSARY 为准：资料分析 / 总结 / 未识别 / 来源 / 分块）。
 *
 * 与后端契约逐一对齐（backend/app/analysis/*）：
 * - 上传校验口径 = `security/uploads.py`：扩展名白名单 + 50MB（等于上限放行）；
 * - 未识别 reason 码 = `analysis/service.py`：no_text_layer / empty_document / images_not_read；
 * - locator 形态 = `analysis/parsing.py` + `chunking.py`：
 *   {format, paragraph} / {format, line|block} / {format, table, row} /
 *   {format, start, end} / {…leaf, part} / {format, images}。
 *
 * 这里是纯函数（无 IO、无组件依赖），由 `node --test tests/` 直接执行验证。
 */

/** 上传硬上限：与后端 50MB 同口径。 */
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024

/**
 * 本单支持的扩展名（TB-7）。
 * 扩展位：TB-8 将加入 .pdf / .pptx，TB-9 将启用 URL 输入；白名单在此单点扩展。
 */
export const ALLOWED_SUFFIXES = ['.txt', '.md', '.docx']

/** 校验上传文件；通过返回 null，否则返回可读中文原因。 */
export function validateUploadFile(name: string, size: number): string | null {
  const lower = name.toLowerCase()
  const dot = lower.lastIndexOf('.')
  const suffix = dot >= 0 ? lower.slice(dot) : ''
  if (!ALLOWED_SUFFIXES.includes(suffix)) {
    const shown = suffix ? `（${suffix}）` : '（无扩展名）'
    return `暂不支持该文件类型${shown}。目前只接受 .txt / .md / .docx；PDF / PPTX 与网页 URL 将按路线图后续接入。`
  }
  if (size > MAX_UPLOAD_BYTES) {
    return `文件超过 50 MB 上限（当前约 ${formatFileSize(size)}），请精简内容后重试。`
  }
  return null
}

/** 字节数 → 中文可读体积（B / KB / MB，保留一位小数）。 */
export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—'
  if (bytes < 1024) return `${Math.round(bytes)} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** Element Plus 标签色调（与分析页状态语义一一对应）。 */
export type ParseTagType = 'success' | 'danger' | 'warning' | 'info'

/**
 * parse_status → 标签。failed / unrecognized 的色调与「已解析」严格区分，
 * 绝不让失败或未识别看起来像成功。未知值原样显示为中性标签。
 */
export function parseStatusTag(status: string): { label: string; type: ParseTagType } {
  if (status === 'parsed') return { label: '已解析', type: 'success' }
  if (status === 'failed') return { label: '解析失败', type: 'danger' }
  if (status === 'unrecognized') return { label: '未识别', type: 'warning' }
  return { label: status, type: 'info' }
}

/** heading_source → 中文（DOCX 标题来源如实标注：样式 / 启发式 / 无）。 */
export function headingSourceLabel(source: string | null | undefined): string {
  if (source === 'style') return '内置标题样式'
  if (source === 'heuristic') return '字号/加粗启发式'
  if (source === 'none') return '未识别到标题'
  return source || '—'
}

/** 未识别契约的最小形状（与 backend UnrecognizedContent 对齐，供纯函数消费）。 */
export interface UnrecognizedLike {
  unrecognized: boolean
  reason: string
  locator: Record<string, unknown>
  needs_ocr: boolean
}

/** 未识别内容 → 一句诚实的中文说明（明示边界，不伪装成完整分析）。 */
export function describeUnrecognized(item: UnrecognizedLike): string {
  const images = typeof item.locator?.images === 'number' ? item.locator.images : 0
  if (item.reason === 'no_text_layer') {
    const imgPart = images > 0 ? `（检测到 ${images} 处图片）` : ''
    return `整份资料没有文本层${imgPart}，疑似扫描件或图片型文档；当前版本不支持 OCR，未调用模型，也未生成总结。`
  }
  if (item.reason === 'empty_document') {
    return '资料内容为空，没有可分析的文本；未调用模型，也未生成总结。'
  }
  if (item.reason === 'images_not_read') {
    const imgPart = images > 0 ? `${images} 处` : '部分'
    return `正文已解析，但 ${imgPart}图片内容读不到；当前版本不支持 OCR，这部分未参与分析，总结不声称覆盖它们。`
  }
  return `未识别内容（原因代码：${item.reason || '未知'}）${item.needs_ocr ? '；需要 OCR，当前版本不支持' : ''}。`
}

/** 叶定位（不含 format）：段落 / 行 / 块 / 表格行。找不到返回空串。 */
function leafText(loc: Record<string, unknown> | null | undefined): string {
  if (!loc) return ''
  if (typeof loc.paragraph === 'number') return `第 ${loc.paragraph} 段`
  if (typeof loc.line === 'number') return `第 ${loc.line} 行`
  if (typeof loc.block === 'number') return `第 ${loc.block} 块`
  if (typeof loc.table === 'number' && typeof loc.row === 'number') return `表格 ${loc.table} · 第 ${loc.row} 行`
  return ''
}

/** 叶定位的结构化形式，用于折叠区间：{unit, index}。 */
function leafRangePart(
  loc: Record<string, unknown> | null | undefined
): { unit: string; index: number } | null {
  if (!loc) return null
  if (typeof loc.paragraph === 'number') return { unit: '段', index: loc.paragraph }
  if (typeof loc.line === 'number') return { unit: '行', index: loc.line }
  if (typeof loc.block === 'number') return { unit: '块', index: loc.block }
  return null
}

/**
 * locator → 可回溯位置中文（引用来源展示用）。
 * 覆盖：单块 {paragraph|line|block} / 表格 {table,row} / 分块区间 {start,end} /
 * 二次切分 {…leaf, part} / 未识别 {format, images}。空 locator 返回空串。
 */
export function formatLocator(locator: Record<string, unknown> | null | undefined): string {
  if (!locator || typeof locator !== 'object') return ''

  if (locator.start || locator.end) {
    const a = leafRangePart(locator.start as Record<string, unknown>)
    const b = leafRangePart(locator.end as Record<string, unknown>)
    let text: string
    if (a && b && a.unit === b.unit) {
      text = a.index === b.index ? `第 ${a.index} ${a.unit}` : `第 ${a.index}–${b.index} ${a.unit}`
    } else {
      const sa = leafText(locator.start as Record<string, unknown>)
      const sb = leafText(locator.end as Record<string, unknown>)
      text = sa && sb ? `${sa} → ${sb}` : sa || sb
    }
    if (typeof locator.part === 'number') text += ` · 第 ${locator.part} 片`
    return text
  }

  if (typeof locator.images === 'number') return `含 ${locator.images} 处图片`

  let text = leafText(locator)
  if (typeof locator.part === 'number') {
    text = (text ? text + ' · ' : '') + `第 ${locator.part} 片`
  }
  return text
}

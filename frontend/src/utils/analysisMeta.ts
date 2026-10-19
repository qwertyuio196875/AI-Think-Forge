/**
 * 资料分析页的纯展示辅助（术语以 GLOSSARY 为准：资料分析 / 总结 / 未识别 / 来源 / 分块）。
 *
 * 与后端契约逐一对齐（backend/app/analysis/*、security/url_guard.py）：
 * - 上传校验口径 = `security/uploads.py`：扩展名白名单（TB-8 起含 .pdf / .pptx）+ 50MB（等于上限放行）；
 * - 未识别 reason 码 = `parsing.py` / `web.py`：no_text_layer / empty_document /
 *   images_not_read / chart_not_read / grouped_shapes_not_read / embedded_object_not_read
 *   + URL 的 no_main_text / empty_page；
 * - locator 形态 = `parsing.py` + `chunking.py` + `web.py`：
 *   {format, paragraph} / {format, line|block} / {format, table, row} /
 *   PDF {format, page, line} / PPTX {format, slide, kind|shape|table|paragraph} /
 *   URL {format, url, line|block} / 分块 {format, start, end} / {…leaf, part} /
 *   未识别 {format, images} 或 {format, url, status, content_type}。
 *
 * 这里是纯函数（无 IO、无组件依赖），由 `node --test tests/` 直接执行验证。
 */

/** 上传硬上限：与后端 50MB 同口径。 */
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024

/** 本单支持的扩展名（TB-7 文本类 + TB-8 版式类；URL 走独立提交端点）。 */
export const ALLOWED_SUFFIXES = ['.txt', '.md', '.docx', '.pdf', '.pptx']

/** 校验上传文件；通过返回 null，否则返回可读中文原因。 */
export function validateUploadFile(name: string, size: number): string | null {
  const lower = name.toLowerCase()
  const dot = lower.lastIndexOf('.')
  const suffix = dot >= 0 ? lower.slice(dot) : ''
  if (!ALLOWED_SUFFIXES.includes(suffix)) {
    const shown = suffix ? `（${suffix}）` : '（无扩展名）'
    return `暂不支持该文件类型${shown}。目前接受 .txt / .md / .docx / .pdf / .pptx；网页文章可直接粘贴 URL 抓取。`
  }
  if (size > MAX_UPLOAD_BYTES) {
    return `文件超过 50 MB 上限（当前约 ${formatFileSize(size)}），请精简内容后重试。`
  }
  return null
}

/** URL 主机名（展示用）：去 `www.` 前缀；解析失败返回空串，绝不显示半截坏串。 */
export function hostFromUrl(url: unknown): string {
  if (typeof url !== 'string' || !url) return ''
  try {
    const host = new URL(url).hostname
    return host.startsWith('www.') ? host.slice(4) : host
  } catch {
    return ''
  }
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
  const locator = item.locator ?? {}
  const images = typeof locator.images === 'number' ? locator.images : 0
  const status = typeof locator.status === 'number' ? `（HTTP ${locator.status}）` : ''

  if (item.reason === 'no_text_layer') {
    const imgPart = images > 0 ? `（检测到 ${images} 处图片）` : ''
    return `整份资料没有文本层${imgPart}，疑似扫描件或图片型文档；当前版本不支持 OCR，未调用模型，也未生成总结。`
  }
  if (item.reason === 'empty_document') {
    return '资料内容为空，没有可分析的文本；未调用模型，也未生成总结。'
  }
  if (item.reason === 'no_main_text') {
    return `未能从该网页提取到可分析的正文${status}（可能是登录页 / 动态渲染页面 / 非文章页）；未调用模型，也未生成总结。`
  }
  if (item.reason === 'empty_page') {
    return `该网页返回的内容为空${status}，没有可分析的正文；未调用模型，也未生成总结。`
  }
  if (item.reason === 'images_not_read') {
    return `正文已解析，但${unreadWhere(locator)}的图片内容读不到；当前版本不支持 OCR，这部分未参与分析，总结不声称覆盖它们。`
  }
  if (item.reason === 'chart_not_read') {
    return `图表内容读不到${whereBracket(locator)}：图表中的文字与数据未参与分析，总结不声称覆盖它们。`
  }
  if (item.reason === 'grouped_shapes_not_read') {
    return `组合形状内的内容读不到${whereBracket(locator)}：组合形状不递归展开，这部分未参与分析，总结不声称覆盖它们。`
  }
  if (item.reason === 'embedded_object_not_read') {
    return `嵌入对象（如 OLE / 多媒体等浮动对象）读不到${whereBracket(locator)}：这部分未参与分析，总结不声称覆盖它们。`
  }
  return `未识别内容（原因代码：${item.reason || '未知'}）${item.needs_ocr ? '；需要 OCR，当前版本不支持' : ''}。`
}

/** 未识别条目发生位置的短语：页 / 幻灯片（含形状）/ 图片数 / 泛指。 */
function unreadWhere(locator: Record<string, unknown>): string {
  const page = num(locator.page)
  if (page !== null) return `第 ${page} 页`
  const slide = num(locator.slide)
  if (slide !== null) {
    const shape = num(locator.shape)
    return shape !== null ? `幻灯片 ${slide} · 形状 ${shape}` : `幻灯片 ${slide}`
  }
  const images = num(locator.images)
  if (images !== null && images > 0) return `${images} 处`
  return '部分'
}

/** 「（位置：…）」括注；无位置信息时为空串。 */
function whereBracket(locator: Record<string, unknown>): string {
  const text = formatLocator(locator)
  return text ? `（位置：${text}）` : ''
}

/**
 * URL 输入的前端基本校验：只判格式（协议 / 凭据 / 可解析性），返回 null 表示可提交。
 * 本机 / 内网 / 云元数据等安全判定以后端 validate_url 为唯一权威（400 原样展示其可读原因）。
 */
export function validateUrlInput(raw: string): string | null {
  const value = raw.trim()
  if (!value) return '请输入网页地址'
  let parsed: URL
  try {
    parsed = new URL(value)
  } catch {
    return '链接格式无法解析；请填写完整地址（如 https://example.com/article）'
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return '只接受 http / https 链接；其它协议（file、ftp 等）不会被抓取'
  }
  if (parsed.username || parsed.password) {
    return '链接不得内嵌用户名或密码'
  }
  return null
}

/** 数值读取：只认有限数字，其它（缺失 / 字符串 / null）返回 null。 */
function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** 叶定位的结构化结果：文本 + 折叠区间所需的 page / line / slide / unit。 */
interface LeafInfo {
  text: string
  page?: number
  line?: number
  slide?: number
  unit?: { name: string; index: number }
}

/** 叶定位（不含 format）：PPTX 幻灯片 / PDF 页行 / 段落 / 行 / 块 / 表格行。 */
function leafInfo(loc: Record<string, unknown> | null | undefined): LeafInfo {
  if (!loc) return { text: '' }

  const slide = num(loc.slide)
  if (slide !== null) {
    if (loc.kind === 'title') return { text: `幻灯片 ${slide} · 标题`, slide }
    const table = num(loc.table)
    const row = num(loc.row)
    if (table !== null && row !== null) return { text: `幻灯片 ${slide} · 表格 ${table} · 第 ${row} 行`, slide }
    const shape = num(loc.shape)
    const paragraph = num(loc.paragraph)
    if (shape !== null && paragraph !== null) {
      return { text: `幻灯片 ${slide} · 形状 ${shape} · 第 ${paragraph} 段`, slide }
    }
    if (shape !== null) return { text: `幻灯片 ${slide} · 形状 ${shape}`, slide }
    return { text: `幻灯片 ${slide}`, slide }
  }

  const page = num(loc.page)
  if (page !== null) {
    const line = num(loc.line)
    return line !== null
      ? { text: `第 ${page} 页 · 第 ${line} 行`, page, line }
      : { text: `第 ${page} 页`, page }
  }

  const paragraph = num(loc.paragraph)
  if (paragraph !== null) return { text: `第 ${paragraph} 段`, unit: { name: '段', index: paragraph } }
  const line = num(loc.line)
  if (line !== null) return { text: `第 ${line} 行`, unit: { name: '行', index: line } }
  const block = num(loc.block)
  if (block !== null) return { text: `第 ${block} 块`, unit: { name: '块', index: block } }
  const table = num(loc.table)
  const row = num(loc.row)
  if (table !== null && row !== null) return { text: `表格 ${table} · 第 ${row} 行` }
  return { text: '' }
}

/** 分块区间折叠：同页折行号、跨页折页码；幻灯片同理；段 / 行 / 块同理；其余用箭头连接。 */
function rangeText(start: LeafInfo, end: LeafInfo): string {
  if (start.page != null && end.page != null) {
    if (start.page === end.page) {
      if (start.line != null && end.line != null) {
        const lo = Math.min(start.line, end.line)
        const hi = Math.max(start.line, end.line)
        return lo === hi ? `第 ${start.page} 页 · 第 ${lo} 行` : `第 ${start.page} 页 · 第 ${lo}–${hi} 行`
      }
      return `第 ${start.page} 页`
    }
    return `第 ${Math.min(start.page, end.page)}–${Math.max(start.page, end.page)} 页`
  }
  if (start.slide != null && end.slide != null) {
    return start.slide === end.slide
      ? `幻灯片 ${start.slide}`
      : `幻灯片 ${Math.min(start.slide, end.slide)}–${Math.max(start.slide, end.slide)}`
  }
  if (start.unit && end.unit && start.unit.name === end.unit.name) {
    const lo = Math.min(start.unit.index, end.unit.index)
    const hi = Math.max(start.unit.index, end.unit.index)
    return lo === hi ? `第 ${lo} ${start.unit.name}` : `第 ${lo}–${hi} ${start.unit.name}`
  }
  if (start.text && end.text && start.text !== end.text) return `${start.text} → ${end.text}`
  return start.text || end.text
}

/**
 * locator → 可回溯位置中文（引用来源与未识别条目展示用）。
 * 覆盖：TXT/DOCX 段落 / MD 行块 / DOCX 表格行 / PDF 页行 / PPTX 幻灯片形状表格 /
 * URL 域名+行 / 分块区间 / 二次切分 part / 未识别图片与网页元数据。空 locator 返回空串。
 */
export function formatLocator(locator: Record<string, unknown> | null | undefined): string {
  if (!locator || typeof locator !== 'object') return ''

  if (locator.start || locator.end) {
    let text = rangeText(leafInfo(locator.start as Record<string, unknown>), leafInfo(locator.end as Record<string, unknown>))
    if (typeof locator.part === 'number') text += ` · 第 ${locator.part} 片`
    return text
  }

  const info = leafInfo(locator)
  let text = info.text
  if (typeof locator.part === 'number') {
    text = (text ? text + ' · ' : '') + `第 ${locator.part} 片`
  }
  if (typeof locator.images === 'number') {
    text = (text ? text + ' · ' : '') + `含 ${locator.images} 处图片`
  }
  if (typeof locator.url === 'string') {
    const host = hostFromUrl(locator.url)
    if (host) text = text ? `${host} · ${text}` : host
  }
  return text
}

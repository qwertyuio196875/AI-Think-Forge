/**
 * 轻量 Markdown 渲染（零依赖）。仅用于把后端返回的结构化方案 content_md
 * 按真实内容渲染到界面，不引入第三方库、不新增 npm 依赖。
 * 安全：先转义 HTML，再套用受控的少量行内标记，链接只允许 http/https。
 */

export interface PlanSection {
  /** 章节标题（Markdown 标题文本；无标题段为空串）。 */
  heading: string
  /** 渲染后的 HTML 片段。 */
  body: string
}

export interface PlanDocument {
  title: string | null
  sections: PlanSection[]
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>]/g, (c) => (c === '&' ? '&amp;' : c === '<' ? '&lt;' : '&gt;'))
}

/** 行内标记：**粗体** / *斜体* / `代码` / [文字](http…) 。入参须已转义。 */
function inlineRender(escaped: string): string {
  return escaped
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(
      /\[([^\]]+)\]\((https?:\/\/[^)\s"]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
    )
}

/** 把一段（不含标题行的）Markdown 渲染成块级 HTML。 */
export function renderMarkdown(md: string): string {
  const lines = md.replace(/\r\n/g, '\n').split('\n')
  const out: string[] = []
  let listType: 'ul' | 'ol' | null = null
  let para: string[] = []

  const flushPara = (): void => {
    if (para.length) {
      out.push('<p>' + para.map((l) => inlineRender(escapeHtml(l))).join('<br>') + '</p>')
      para = []
    }
  }
  const closeList = (): void => {
    if (listType) {
      out.push(listType === 'ul' ? '</ul>' : '</ol>')
      listType = null
    }
  }
  const openList = (t: 'ul' | 'ol'): void => {
    if (listType !== t) {
      closeList()
      out.push(t === 'ul' ? '<ul>' : '<ol>')
      listType = t
    }
  }

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '')
    if (!line.trim()) {
      flushPara()
      closeList()
      continue
    }
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
      flushPara()
      closeList()
      out.push('<hr>')
      continue
    }
    const bq = /^>\s?(.*)$/.exec(line)
    if (bq) {
      flushPara()
      closeList()
      out.push('<blockquote>' + inlineRender(escapeHtml(bq[1])) + '</blockquote>')
      continue
    }
    const ul = /^\s*[-*+]\s+(.*)$/.exec(line)
    if (ul) {
      flushPara()
      openList('ul')
      out.push('<li>' + inlineRender(escapeHtml(ul[1])) + '</li>')
      continue
    }
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    if (ol) {
      flushPara()
      openList('ol')
      out.push('<li>' + inlineRender(escapeHtml(ol[1])) + '</li>')
      continue
    }
    para.push(line.trim())
  }
  flushPara()
  closeList()
  return out.join('')
}

/**
 * 按 Markdown 标题把方案正文切成若干 `.fld` 区块（标题真实来自内容，不套固定模板）。
 * 首个独立的 `# `（在所有小节之前）视为文档标题，其余标题（任意层级）各自成节。
 */
export function splitPlanSections(md: string): PlanDocument {
  const lines = md.replace(/\r\n/g, '\n').split('\n')
  let title: string | null = null
  let current: { heading: string; buffer: string[] } | null = null
  const sections: { heading: string; buffer: string[] }[] = []
  const preamble: string[] = []

  for (const line of lines) {
    const h = /^(#{1,6})\s+(.*)$/.exec(line)
    if (h) {
      const level = h[1].length
      const text = h[2].trim()
      if (level === 1 && !title && !current && preamble.join('').trim() === '') {
        title = text
        continue
      }
      current = { heading: text, buffer: [] }
      sections.push(current)
      continue
    }
    if (current) current.buffer.push(line)
    else preamble.push(line)
  }

  const result: PlanSection[] = []
  const preText = preamble.join('\n').trim()
  if (preText) result.push({ heading: '', body: renderMarkdown(preText) })
  for (const s of sections) result.push({ heading: s.heading, body: renderMarkdown(s.buffer.join('\n')) })

  return { title, sections: result }
}

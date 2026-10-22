/**
 * 引用卡片的展示辅助（工单 23）。
 *
 * 三件事，全部是纯函数：
 * 1. 一条卡片该显示成什么（文件名 · 段落号 · 相关度）；
 * 2. 默认全部采用、逐条可取消时，「采用了几条 / 共几条」怎么说；
 * 3. 检索降级或未使用时必须**明示**，不能静默隐藏（规格要求）。
 *
 * 边界：本文件不检索、不算相关度、不判断一个问题是否事实型——那是后端的事
 * （判定规则写在 `fact_check_v1.md` 资产里）。前端只负责把后端给的结论摆出来。
 *
 * 由 `node --test tests/citationCard.test.mts` 直接验证。
 */

/** 与后端 `CitationCard` 对齐的最小形状。 */
export interface CitationLike {
  chunk_id: number
  name: string
  seq: number
  similarity: number
  paragraph?: number | null
  locator_label?: string
  text?: string
  adopted?: boolean
  collapsible?: boolean
}

/** 与后端 `RetrievalStatusInfo` 对齐的最小形状。 */
export interface RetrievalStatusLike {
  status: string
  status_label: string
  message?: string | null
  degraded?: boolean
  truncated?: boolean
}

/** 相关度显示成百分比整数：`0.7421` → `74%`。 */
export function similarityPercent(similarity: number): string {
  if (!Number.isFinite(similarity) || similarity < 0) return '0%'
  return `${Math.round(similarity * 100)}%`
}

/**
 * 定位文案：优先后端给的 `locator_label`（「第 3 段」这类），
 * 没有就按段落号拼，再没有就说「位置未标注」——**不编一个位置出来**。
 */
export function citationLocator(citation: CitationLike): string {
  const label = (citation.locator_label ?? '').trim()
  if (label) return label
  if (typeof citation.paragraph === 'number') return `第 ${citation.paragraph} 段`
  return '位置未标注'
}

/**
 * 一行卡片抬头：`文件名 · 第 3 段 · 相关度 74%`。
 *
 * 规格要求显示「文件名、段落号、相关度」这三样，缺一样都算没做到；
 * 因此三样都从后端字段派生，缺字段时给明确的占位而不是省略。
 */
export function citationHeadline(citation: CitationLike): string {
  const name = (citation.name ?? '').trim() || '未知资料'
  return `${name} · ${citationLocator(citation)} · 相关度 ${similarityPercent(citation.similarity)}`
}

/**
 * 卡片的初始采用状态：**默认全选**。
 *
 * 只有后端明确给了 `adopted: false` 才算未采用；字段缺失（老响应）按采用处理——
 * 默认不采用会让用户每次都要手动勾一遍，与规格的「默认全部采用」相反。
 */
export function isAdopted(citation: CitationLike): boolean {
  return citation.adopted !== false
}

/** 已采用的片段编号清单（提交答案时作为「未被取消」的那一批）。 */
export function adoptedChunkIds(citations: readonly CitationLike[]): number[] {
  return citations.filter(isAdopted).map((citation) => citation.chunk_id)
}

/** 被取消采用的片段编号清单（提交给后端，确保它们不进提示词）。 */
export function rejectedChunkIds(citations: readonly CitationLike[]): number[] {
  return citations.filter((citation) => !isAdopted(citation)).map((citation) => citation.chunk_id)
}

/**
 * 采用情况的摘要：`已采用 2 / 3 条`。
 *
 * 这个数要能一眼看出「有没有取消过」——全部采用时说「全部采用（3 条）」，
 * 取消过才说「已采用 2 / 3 条」，用户不用逐条点开去数。
 */
export function adoptionSummary(citations: readonly CitationLike[]): string {
  const total = citations.length
  if (total === 0) return '本次没有可用引用'
  const adopted = adoptedChunkIds(citations).length
  if (adopted === total) return `全部采用（${total} 条）`
  if (adopted === 0) return `已全部取消（共 ${total} 条）`
  return `已采用 ${adopted} / ${total} 条`
}

/** 「全部采用（N 条）」的唯一来源，测试与组件共用同一句文案。 */
export function adoptionAllText(total: number): string {
  return `全部采用（${total} 条）`
}

/**
 * 检索状态的提示文案：降级 / 未使用知识库时**必须**说清楚。
 *
 * 为什么不能静默：降级意味着召回变差，用户看到的引用可能不完整；
 * 若界面不说明，他会以为「这就是全部依据」。返回 null 表示无需提示（正常检索）。
 */
export function retrievalNotice(status: RetrievalStatusLike | null | undefined): string | null {
  if (!status) return null
  if (status.status === 'ok' && !status.degraded) {
    // 正常检索：只有「命中被截断」这种需要让用户知道的情况才提示。
    if (status.truncated) return '命中内容超出单次注入上限，已按预算截断（未截断的单条保持完整）'
    return null
  }
  const label = (status.status_label ?? '').trim() || '检索状态异常'
  const message = (status.message ?? '').trim()
  return message ? `${label}：${message}` : label
}

/**
 * 卡片是否可折叠：后端说可以才折叠。
 *
 * 不给前端一个「一律可折叠」的默认值——折叠会隐藏正文，若后端认为这条不该折
 * （比如极短片段，折叠反而多一次点击），前端的擅自折叠就是多余操作。
 */
export function isCollapsible(citation: CitationLike): boolean {
  return citation.collapsible === true
}

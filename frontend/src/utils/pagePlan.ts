/**
 * 页面规划的展示与编辑逻辑（工单 26）。
 *
 * 后端已经提供「章节 → 页列表」的规划（#25）：POST/GET `/tasks/{id}/page-plans`、
 * POST/.../pages（加一页）、DELETE/.../pages/{at_index}（删一页）。这里只负责把它们
 * 变成界面可用的数据，并把「这一页归属哪些章节」这类判断收在一处，组件不各自推导。
 *
 * 为什么单独成文件：`node --test` 能直接测这些纯函数（沿用仓库既有做法，不挂组件测试
 * 框架），而「预览显示每页归属哪个章节」「显示实际页数」这些验收点正好落在这一层。
 */

/** 页类型：封面 / 内容 / 结尾（与后端 `PAGE_KIND_*` 一致）。 */
export type PageKind = 'cover' | 'content' | 'end'

/** 规划里的一页（与后端 `PlannedPageItem` 同形）。 */
export interface PlannedPage {
  index: number
  kind: PageKind
  title: string
  chapter_seqs: number[]
}

/** 一次规划的完整结果（与后端 `PagePlanResponse` 同形）。 */
export interface PagePlan {
  page_plan_id: number
  task_id: number
  plan_id: number
  target_pages: number
  actual_pages: number
  pages: PlannedPage[]
}

/** 页数预设（issue #25：8 / 12 / 16 / 20 / 30）与自定义区间 3–60。 */
export const PAGE_PRESETS: readonly number[] = [8, 12, 16, 20, 30]
export const MIN_PAGES = 3
export const MAX_PAGES = 60

/**
 * 校验页数输入：区间外不静默夹紧，返回明确原因（issue #25 验收 ⑤）。
 *
 * 返回 `null` 表示合法；否则返回给用户看的中文说明。
 */
export function validatePageCount(value: number | null | undefined): string | null {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '请选择或输入页数'
  }
  if (!Number.isInteger(value)) {
    return '页数必须是整数'
  }
  if (value < MIN_PAGES || value > MAX_PAGES) {
    return `页数需在 ${MIN_PAGES}–${MAX_PAGES} 之间（当前 ${value}）`
  }
  return null
}

/** 某页归属章节的中文说明：封面/结尾没有归属，内容页列出章节序号。 */
export function pageOwnershipLabel(page: PlannedPage): string {
  if (page.kind === 'cover') return '封面'
  if (page.kind === 'end') return '结尾页'
  if (page.chapter_seqs.length === 0) return '未归属章节'
  if (page.chapter_seqs.length === 1) return `第 ${page.chapter_seqs[0]} 章`
  return `第 ${page.chapter_seqs.join('、')} 章（合并）`
}

/**
 * 实际页数与目标页数的差异说明（issue #26 验收 ③：不再强制等于目标页数）。
 *
 * 单页增删之后实际页数会偏离最初的目标，界面必须如实显示这个偏离，而不是假装相等。
 */
export function pageCountSummary(plan: PagePlan): string {
  const { target_pages: target, actual_pages: actual } = plan
  if (actual === target) {
    return `共 ${actual} 页（与目标一致）`
  }
  const delta = actual - target
  const sign = delta > 0 ? '+' : ''
  return `共 ${actual} 页（目标 ${target}，${sign}${delta}）`
}

/**
 * 标记「重点被挤到最后一页」这类问题（issue #26 验收 ④）。
 *
 * 判据刻意保守：合并页（多章挤一页）与最后一页之前就被合并的章节，都是「内容被挤压」
 * 的信号。返回需要提醒的页（空数组 = 没有可疑页）。
 */
export function crampedPages(plan: PagePlan): PlannedPage[] {
  return plan.pages.filter(
    (page) => page.kind === 'content' && page.chapter_seqs.length > 1
  )
}

/** 可删除的页：封面与结尾是结构页，不允许删（删了 deck 首尾契约就破了）。 */
export function isDeletable(page: PlannedPage): boolean {
  return page.kind === 'content'
}

/**
 * 删除某页后重新编号的预览（不调后端，仅用于界面即时反馈）。
 *
 * `atIndex` 与后端一致：1 起、删除后其余页 index 依次前移。
 */
export function pagesAfterDelete(plan: PagePlan, atIndex: number): PlannedPage[] {
  const kept = plan.pages.filter((page) => page.index !== atIndex)
  return kept.map((page, offset) => ({ ...page, index: offset + 1 }))
}

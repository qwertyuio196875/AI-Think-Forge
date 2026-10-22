/**
 * 当前轮引用卡片的勾选状态（工单 23）。
 *
 * 「勾选 / 取消」的语义不在这里另造：状态就是 `{...card, adopted}` 的浅拷贝数组，
 * 计数与取消清单全部复用 `citationCard.ts` 的现成 helper（`rejectedChunkIds` / `isAdopted`）。
 * 本文件只补那些 helper 真正没有的三件事：
 * 1. `initCopies`：从前沿问题播种可编辑副本——直接改后端响应对象会污染缓存；
 * 2. `withAdopted`：勾 / 取消单条的不可变更新；
 * 3. `roundRejectedChunkIds` + `citationsHeaderText`：跨题合并去重（同一 chunk 可能被
 *    两个问题各取消一次，提交并集仍只应出现一次），以及规格要求的折叠标题字面文案
 *    （`默认全部采用` / `本次不使用任何资料片段`），`adoptionSummary` 的句式对不上这两句。
 *
 * 测试只覆盖以上新增逻辑：`node --test tests/citationSelection.test.mts`。
 */
import { rejectedChunkIds, type CitationLike } from './citationCard.ts'

/** 题目下标 → 该题引用卡片副本（adopted 可改）。无引用的题不进映射，省得「0 条」噪声。 */
export type CitationCopies = Record<number, CitationLike[]>

/** initCopies 只需要每题的引用清单这一形状（FrontierQuestion 结构上满足）。 */
interface QuestionWithCitations {
  citations: readonly CitationLike[]
}

/**
 * 从一轮的前沿问题播种勾选状态：逐条浅拷贝（adopted 初始值沿用后端给的，正常即全选）。
 * 拷贝而非引用：提交前所有取消操作都发生在副本上，后端响应对象保持原样。
 */
export function initCopies(frontier: readonly QuestionWithCitations[]): CitationCopies {
  const copies: CitationCopies = {}
  frontier.forEach((q, qi) => {
    if (q.citations.length > 0) {
      copies[qi] = q.citations.map((citation) => ({ ...citation }))
    }
  })
  return copies
}

/** 取某题的副本清单；无引用返回空数组（模板 v-for 直接可用）。 */
export function copiesOfQuestion(copies: CitationCopies, qi: number): readonly CitationLike[] {
  return copies[qi] ?? []
}

/**
 * 勾上 / 取消某题下某个片段，返回新状态。
 *
 * 不存在的题、或该编号本来就是这个状态时返回原引用：
 * 避免模板里一次无变化的赋值触发整轮卡片重渲染。
 */
export function withAdopted(
  copies: CitationCopies,
  qi: number,
  chunkId: number,
  adopted: boolean
): CitationCopies {
  const list = copies[qi]
  if (!list) return copies
  if (list.every((c) => c.chunk_id !== chunkId || c.adopted === adopted)) return copies
  return { ...copies, [qi]: list.map((c) => (c.chunk_id === chunkId ? { ...c, adopted } : c)) }
}

/** 折叠标题里「一条都没勾」时的固定话术（规格字面量）。 */
export const NO_CITATION_USE_TEXT = '本次不使用任何资料片段'

/**
 * 折叠标题：`参考资料 · N 条 · 默认全部采用`；全部取消时明确说「本次不使用任何资料片段」。
 *
 * 取消条数直接用现成的 `rejectedChunkIds(list).length`，不再自己数一遍——
 * 「界面上勾着什么」与「提交什么」共用同一个 helper，才不会两处口径分叉。
 * 为什么默认态也要说「默认全部采用」：不点展开的人也要知道勾着的是什么。
 */
export function citationsHeaderText(copies: CitationCopies, qi: number): string {
  const list = copiesOfQuestion(copies, qi)
  const total = list.length
  const canceled = rejectedChunkIds(list).length
  if (canceled === 0) return `参考资料 · ${total} 条 · 默认全部采用`
  if (canceled >= total) return `参考资料 · ${total} 条 · ${NO_CITATION_USE_TEXT}`
  return `参考资料 · ${total} 条 · 已采用 ${total - canceled} / ${total}`
}

/**
 * 汇总本轮所有被取消的 chunk_id（跨题合并 + 去重），作为 submitAnswers 的第 4 参。
 *
 * 每题清单交给现成的 `rejectedChunkIds` 判断，这里只做并集与去重；
 * 顺序按「题目下标升序 + 题内出现顺序」，让提交载荷可比对。
 * 副本由本模块 initCopies 播种、toggle 只作用于副本内的编号，天然不会带出陈旧 id。
 */
export function roundRejectedChunkIds(copies: CitationCopies): number[] {
  const result: number[] = []
  for (const qi of Object.keys(copies)
    .map(Number)
    .sort((a, b) => a - b)) {
    for (const id of rejectedChunkIds(copies[qi] ?? [])) {
      if (!result.includes(id)) result.push(id)
    }
  }
  return result
}

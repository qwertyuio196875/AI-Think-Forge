/**
 * 确认后章节清单卡（工单 8）的纯展示辅助。
 *
 * 术语以 GLOSSARY 为准：**成品章节** = 成品正文的章（第 1 章、第 2 章……），
 * 其清单来自方案「章节」那一节的条目、由后端切分落库；它**不是**方案分节
 * （方案 Markdown 的 `##` 段落）。所以这里只做「把后端章节清单渲染得能读」，
 * 绝不做任何切分——前端再切一套就会出现规格 §2 点名的「多套切分器互相错位」。
 *
 * 与后端契约逐一对齐（backend/app/models/plan_section.py）：
 * - 状态取值域 `pending` / `completed` / `failed`，中文标签待写 / 已完成 / 失败；
 * - `target_length` 是方案给的**建议字数**，旧格式方案可能为空（此时说「字数未定」，
 *   不补 0：0 字与未定是两件事）；
 * - `status_label` 由后端给出，前端优先用它，缺省才回落到本地映射，避免两边翻译打架；
 * - `plan_id` 标出这份清单属于哪一版方案，修订后方案换 id，旧清单必须判过期。
 *
 * 这里是纯函数（无 IO、无组件依赖），由 `node --test tests/sectionList.test.mts` 直接验证。
 */

/** Element Plus 标签色调，与知识库清单页保持一致。 */
export type SectionTagType = 'success' | 'warning' | 'danger' | 'info'

/** 「返回修订方案」是本章节清单卡唯一的出口（工单 8：只此一个）。 */
export const RETURN_TO_REVISE_LABEL = '返回修订方案'

/**
 * 只读说明：明确告诉用户「这里改不了，要改就回去对话修订」。
 *
 * 工单 8 明确不提供改名 / 拖拽排序 / 增删章节——那等于把「方案直接编辑」提前
 * （规格 §3 不做清单里点名的那件事）。既然不给入口，就必须说清出口在哪。
 */
export const READONLY_NOTICE =
  '本清单只读：章节由方案「章节」一节切分而来，不支持改名、排序、增删；要改就返回修订方案，用对话改完再确认。'

/**
 * 方案切不出章节时的提示（后端返回 200 + 空清单，不是错误）。
 *
 * 空清单最常见的原因是方案里没写「章节」一节，直接说清怎么补，并指向返回修订。
 */
export const EMPTY_SECTIONS_HINT =
  '当前方案没有可识别的成品章节（方案「章节」一节可能缺失或格式不符）。请点「返回修订方案」，让方案按每章一行「标题 + 要点 + 建议字数」补齐后再确认。'

/**
 * 章节状态 → 中文标签与色调。
 *
 * `failed` 必须是 `danger`：与「已完成」同色会让人以为这章写好了（与知识库
 * 索引失败同理）。未知值原样显示为中性标签，绝不猜成「待写」——猜错会让人
 * 以为没写过的章被写过了。
 */
export function sectionStatusTag(status: string): { label: string; type: SectionTagType } {
  if (status === 'pending') return { label: '待写', type: 'info' }
  if (status === 'completed') return { label: '已完成', type: 'success' }
  if (status === 'failed') return { label: '失败', type: 'danger' }
  return { label: status, type: 'info' }
}

/** 清单行里与状态有关的最小形状（与后端 PlanSectionItem 对齐）。 */
export interface SectionStatusLike {
  status: string
  status_label?: string
}

/**
 * 章节状态文案：优先后端 `status_label`，空/空白才回落到本地映射。
 *
 * 后端已经统一翻译（`SECTION_STATUS_LABELS`），前端再翻一遍只会在后端加状态时
 * 落后一版；但契约字段可能缺失（老响应 / 替身数据），所以保留回落。
 */
export function sectionStatusLabel(item: SectionStatusLike): string {
  const label = (item.status_label ?? '').trim()
  return label || sectionStatusTag(item.status).label
}

/**
 * 建议字数的可读文案。
 *
 * 缺失 / 非正数 / 非有限值一律「字数未定」，**不显示 0 字**：0 字是「定死了不写」，
 * 与「方案没给建议字数」含义完全不同（US5 要的是「每章大约多少字」）。
 */
export function sectionLengthText(targetLength: number | null | undefined): string {
  if (typeof targetLength !== 'number' || !Number.isFinite(targetLength) || targetLength <= 0) {
    return '字数未定'
  }
  return `约 ${targetLength} 字`
}

/** 清单行里与文案有关的最小形状。 */
export interface SectionLineLike {
  seq: number
  title: string
  target_length: number | null
}

/**
 * 一行清单文案：`1. 标题（约 1200 字）`。
 *
 * 序号用后端 `seq` 而不是数组下标：清单是「成品目录」的镜像，若后端因故跳号，
 * 前端悄悄重编号会让人以为章号变了（规格 §4 要求清单与 Word 成品同序同数）。
 * 标题空白时给占位，避免清单里出现无名条目。
 */
export function sectionLine(item: SectionLineLike): string {
  const title = (item.title ?? '').trim() || '未命名章节'
  return `${item.seq}. ${title}（${sectionLengthText(item.target_length)}）`
}

/** 整份清单逐行展开，一行一章，顺序即后端返回顺序。 */
export function sectionLines(items: SectionLineLike[]): string[] {
  return items.map(sectionLine)
}

/**
 * 抬头文案：`将生成 N 章`。
 *
 * 0 章时不写「将生成 0 章」（读起来像正常结果，实际是切分失败），而是明确说
 * 没有可切分的成品章节，配合 `EMPTY_SECTIONS_HINT` 给出下一步。
 */
export function sectionListHeadline(total: number): string {
  if (typeof total !== 'number' || !Number.isFinite(total) || total <= 0) {
    return '没有可切分的成品章节'
  }
  return `将生成 ${total} 章`
}

/**
 * 清单是否已过期：后端返回的 `plan_id` 与当前方案 id 不一致即过期。
 *
 * 方案修订会换一版方案（新的 `plan_id`），旧清单描述的是上一版目录；据此判断，
 * 避免拿着过期清单去填充（下游 #9 的闸门也依赖同一判断）。
 */
export function isSectionListStale(listPlanId: number, currentPlanId: number): boolean {
  return listPlanId !== currentPlanId
}

/**
 * 字数分摊的展示辅助（工单 15）。
 *
 * 一条硬边界：**分摊规则只在后端实现一份**（`backend/app/fill/budget.py`）。
 * 本文件只回答三个显示问题——
 * 1. 这次分摊的和与目标差多少（是否「恰好等于」）；
 * 2. 逐章字数能不能改，改坏了怎么说明；
 * 3. 总额度还剩多少。
 *
 * 为什么不在这里摊一遍：前端再摊一次的后果是「预览一个数、实际写出另一个数」，
 * 正是规格 §2 点名反对的「多套实现互相错位」。所以任何真正的分摊都走后端
 * `POST /api/tasks/{id}/fill/allocation`（只算不写）。
 *
 * 纯函数、无 IO、无组件依赖，由 `node --test tests/wordBudget.test.mts` 直接验证。
 */

/** 与后端 `app.models.fill` 逐字对齐的区间与档位（US 12–14）。 */
export const MIN_TARGET_LENGTH = 300
export const MAX_TARGET_LENGTH = 20000

/**
 * 校对分摊结果与目标字数是否一致。
 *
 * 规格原文：「各章建议字数之和**恰好**等于目标字数（余数归最后一章）」。
 * 「恰好」是要在界面上被看见的：差一个字也要说出来，否则用户数出来的数与系统给的数
 * 对不上（US 18），而他并不知道该信哪个。
 */
export function allocationSummary(
  targetLength: number,
  sectionLengths: readonly number[]
): { sum: number; diff: number; exact: boolean; text: string } {
  const sum = sectionLengths.reduce((total, value) => total + (Number.isFinite(value) ? value : 0), 0)
  const diff = sum - targetLength
  const exact = sectionLengths.length > 0 && diff === 0
  let text: string
  if (sectionLengths.length === 0) {
    text = '还没有可分摊的章节'
  } else if (exact) {
    text = `${sectionLengths.length} 章合计 ${sum} 字 · 与目标一致`
  } else if (diff > 0) {
    text = `${sectionLengths.length} 章合计 ${sum} 字 · 比目标多 ${diff} 字`
  } else {
    text = `${sectionLengths.length} 章合计 ${sum} 字 · 比目标少 ${-diff} 字`
  }
  return { sum, diff, exact, text }
}

/** 逐章字数的校验结果：要么给一个数，要么给一句能读懂的原因。 */
export type SectionLengthCheck =
  | { ok: true; value: number }
  | { ok: false; message: string }

/**
 * 校验用户在某一行输入的字数。
 *
 * 只做**这一格**的合法性判断（正整数）；「改完之后总和是多少」不在这里管——
 * 那要看完整张表，由 `allocationSummary` 与后端共同裁决。这样单行报错不会因为
 * 别的行还没填而误判。
 *
 * 不静默取整、不静默夹到边界值：这两种做法都会让用户拿到自己没要的数字。
 */
export function checkSectionLength(raw: string): SectionLengthCheck {
  const text = String(raw ?? '').trim()
  if (text === '') return { ok: false, message: '这一章的字数不能为空' }
  if (!/^\d+$/.test(text)) {
    return { ok: false, message: `只能填阿拉伯数字整数：${text} 不是有效字数` }
  }
  const value = Number(text)
  if (value < 1) return { ok: false, message: '每章至少 1 字' }
  if (value > MAX_TARGET_LENGTH) {
    return { ok: false, message: `单章字数不能超过 ${MAX_TARGET_LENGTH} 字` }
  }
  return { ok: true, value }
}

/**
 * 单章字数的提示文案：说清「那一章分到多少」，并标出是不是用户改过的。
 *
 * 标出来源很重要——用户改过的章不该被下一次分摊悄悄覆盖，
 * 而未改的章本来就是系统给的，两者在界面上必须能分辨。
 */
export function sectionLengthHint(targetLength: number, edited: boolean): string {
  const source = edited ? '手动指定' : '系统按权重分摊'
  return `约 ${targetLength} 字 · ${source}`
}

/**
 * 参数弹窗打开时的初始字数。
 *
 * 优先用方案各章建议字数之和（用户上次确认过的篇幅）；方案没给建议字数时给 null，
 * 让弹窗停在「还没选」而不是伪造一个 3000——伪造等于替用户做了决定。
 */
export function initialTargetLength(suggestedLengths: readonly (number | null)[]): number | null {
  if (suggestedLengths.length === 0) return null
  if (suggestedLengths.some((value) => typeof value !== 'number' || value <= 0)) return null
  let total = 0
  for (const value of suggestedLengths) {
    // 上面已经逐个判过「是正数」，这里只为让类型收窄，不再重复业务判断。
    total += value as number
  }
  return total
}

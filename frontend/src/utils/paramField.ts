/**
 * 参数型表单弹窗的纯逻辑（工单 #4）。
 *
 * 这些函数只管「一个数值参数长什么样、怎么校验」，不碰 DOM，也不依赖 Vue，
 * 所以能在 `node --test` 下直接跑。组件（`ParamDialog.vue`）只负责把这里的
 * 结论渲染成界面。
 *
 * 取值范围与预设档位与规格逐字对齐（issue #2 的 US 12–14、US 22–23）：
 * - 目标字数：预设 1000 / 2000 / 3000 / 5000 / 8000 / 12000，自定义 300–20000 字；
 * - 页数：预设 8 / 12 / 16 / 20 / 30，自定义 3–60 页。
 *
 * 一条硬规则贯穿全文件：**超范围时只说明原因，绝不静默改成边界值**
 * （US 14 / US 23 明确要求「明确告诉我为什么不行，而不是悄悄改成边界值」）。
 * 因此校验失败的结果里**不携带**任何“已修正”的数值，调用方想凑出一个合法值
 * 也无从下手。
 */

/** 一个「档位 + 自定义区间」型参数的规格。 */
export interface ParamSpec {
  /** 界面上的标签，如「目标字数」。 */
  name: string
  /** 常用档位，按从小到大排列。 */
  presets: readonly number[]
  /** 允许的最小值（含）。 */
  min: number
  /** 允许的最大值（含）。 */
  max: number
  /** 计量单位，如「字」「页」。 */
  unit: string
}

/** 目标字数参数（US 12–14）。 */
export const WORD_COUNT_PARAM: ParamSpec = {
  name: '目标字数',
  presets: [1000, 2000, 3000, 5000, 8000, 12000],
  min: 300,
  max: 20000,
  unit: '字'
}

/** 页数参数（US 22–23）。 */
export const PAGE_COUNT_PARAM: ParamSpec = {
  name: '页数',
  presets: [8, 12, 16, 20, 30],
  min: 3,
  max: 60,
  unit: '页'
}

/** 校验失败的原因码，调用方据此决定提示样式或埋点，不必解析文案。 */
export type ParamIssueReason =
  | 'empty'
  | 'not-a-number'
  | 'not-integer'
  | 'below-min'
  | 'above-max'

export type ParamIssue = {
  ok: false
  reason: ParamIssueReason
  /** 面向用户的中文说明，直接可显示。 */
  message: string
}

export type ParamCheck = { ok: true; value: number } | ParamIssue

/** 规格里初始值的展示形态：命中档位，还是自定义输入。 */
export interface ParamValueDescription {
  mode: 'preset' | 'custom'
  /** `mode === 'preset'` 时为命中的档位，否则为 null。 */
  preset: number | null
  /** 输入框里应回显的文本；无初始值时为空串。 */
  text: string
}

/** 「300–20000」这样的区间文案，提示、占位符、报错共用一处，避免各写一遍。 */
export function rangeText(spec: ParamSpec): string {
  return `${spec.min}–${spec.max}`
}

/** 判断一个值是否正好落在预设档位上（null / undefined 一律不算）。 */
export function isPresetValue(value: number | null | undefined, spec: ParamSpec): boolean {
  if (typeof value !== 'number') return false
  return spec.presets.includes(value)
}

/**
 * 把已有的参数值推导成弹窗的初始形态。
 *
 * 命中档位就选中该档（省得用户再点一次），不是档位就落到自定义输入并原样回显；
 * 无值时不伪造档位——否则用户打开弹窗会以为系统替他选了 1000 字。
 */
export function describeParamValue(
  value: number | null | undefined,
  spec: ParamSpec
): ParamValueDescription {
  if (typeof value !== 'number') {
    return { mode: 'custom', preset: null, text: '' }
  }
  if (isPresetValue(value, spec)) {
    return { mode: 'preset', preset: value, text: String(value) }
  }
  return { mode: 'custom', preset: null, text: String(value) }
}

/* ---------- 展示文案：组件只负责渲染，不在模板里拼字符串 ---------- */

/**
 * 常驻说明（不是报错）：把「档位 / 自定义 / 上下界 / 不自动改边界值」一次讲清。
 *
 * 放在输入框上方而不是等出错才出现，是因为 US 14 与 US 23 的要求是用户事先就
 * 知道规矩；错误提示只解释这一次为什么不行。
 */
export function paramHint(spec: ParamSpec): string {
  return `常用档位 ${spec.presets.join(' / ')} ${spec.unit}，也可输入 ${rangeLabel(
    spec
  )}之间的自定义值；超出范围会说明原因，不会自动改成边界值。`
}

/** 自定义输入框的占位符，带上本参数自己的区间与单位（两处参数不串用）。 */
export function customPlaceholder(spec: ParamSpec): string {
  return `自定义，${rangeText(spec)} ${spec.unit}`
}

/** 档位按钮上的文案：只给数值，单位由分组标签统一说明，避免按钮里塞满「字」。 */
export function presetLabels(spec: ParamSpec): string[] {
  return spec.presets.map((n) => String(n))
}

/**
 * 已确认值的单行摘要（给调用方在弹窗关闭后回显用）。
 *
 * 明说「常用档位」还是「自定义」，用户回看时知道这个数是点出来的还是敲进去的。
 */
export function summarizeParamValue(
  value: number | null | undefined,
  spec: ParamSpec
): string {
  const desc = describeParamValue(value, spec)
  if (desc.text === '') return '未设置'
  return `${desc.text} ${spec.unit}（${desc.mode === 'preset' ? '常用档位' : '自定义'}）`
}

/* ---------- 提示文案 ---------- */

function rangeLabel(spec: ParamSpec): string {
  return `${rangeText(spec)} ${spec.unit}`
}

function belowMinIssue(spec: ParamSpec, shown: string): ParamIssue {
  return {
    ok: false,
    reason: 'below-min',
    message: `${spec.name}不能小于 ${spec.min} ${spec.unit}：${shown} 低于允许范围 ${rangeLabel(
      spec
    )}，不会自动改成 ${spec.min}。`
  }
}

function aboveMaxIssue(spec: ParamSpec, shown: string): ParamIssue {
  return {
    ok: false,
    reason: 'above-max',
    message: `${spec.name}不能大于 ${spec.max} ${spec.unit}：${shown} 高于允许范围 ${rangeLabel(
      spec
    )}，不会自动改成 ${spec.max}。`
  }
}

function notIntegerIssue(spec: ParamSpec, shown: string): ParamIssue {
  return {
    ok: false,
    reason: 'not-integer',
    message: `${spec.name}必须是整数：${shown} 不是整数，不会替你取整。`
  }
}

function emptyIssue(spec: ParamSpec): ParamIssue {
  return {
    ok: false,
    reason: 'empty',
    message: `请填写${spec.name}：从常用档位里选一个，或输入 ${rangeLabel(spec)} 之间的自定义值。`
  }
}

function notANumberIssue(spec: ParamSpec, shown: string): ParamIssue {
  return {
    ok: false,
    reason: 'not-a-number',
    message: `${spec.name}只能填阿拉伯数字：${shown} 不是有效数字。`
  }
}

/**
 * 校验一次整数输入，返回解析后的数值或可读原因。
 *
 * 只接受纯数字串（允许首尾空白与负号）：`3,000`、`3千`、`1e3` 这类“看起来像数”
 * 的写法一律判非法——猜一个值出来等于替用户改数，正是 US 14 禁止的行为。
 */
function checkInteger(n: number, spec: ParamSpec, shown: string): ParamCheck {
  if (n < spec.min) return belowMinIssue(spec, shown)
  if (n > spec.max) return aboveMaxIssue(spec, shown)
  return { ok: true, value: n }
}

/** 校验输入框里的原始文本。 */
export function checkParamInput(raw: string, spec: ParamSpec): ParamCheck {
  const text = String(raw ?? '').trim()
  if (text === '') return emptyIssue(spec)

  // 只认十进制整数写法；小数单独给「必须是整数」，与乱码区分开。
  if (/^-?\d+$/.test(text)) {
    return checkInteger(Number(text), spec, text)
  }
  if (/^-?\d+\.\d+$/.test(text)) {
    return notIntegerIssue(spec, text)
  }
  return notANumberIssue(spec, text)
}

/** 校验已经是数值的值（父组件保存前兜底，口径与输入校验一致）。 */
export function checkParamValue(
  value: number | null | undefined,
  spec: ParamSpec
): ParamCheck {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return { ok: false, reason: 'empty', message: `${spec.name}还没有填写。` }
  }
  if (!Number.isInteger(value)) {
    return notIntegerIssue(spec, String(value))
  }
  return checkInteger(value, spec, String(value))
}

/* ---------- 报错时机：什么时候把红字摆出来 ---------- */

/**
 * 这一条毛病该不该现在就显示。
 *
 * 区分两种性质完全不同的毛病：
 * - **再敲几位就可能自愈的**（`empty`、`below-min`）：用户输入 2000 时中途会出现
 *   「2」，若立刻标红，等于每敲一个字符骂人一次。这类留到失焦（`reveal`）再说。
 * - **无论怎么敲都救不回来的**（`above-max`、`not-integer`、`not-a-number`）：
 *   等着也没用，立刻说清楚，用户好当场改。
 *
 * @param issue `checkParamInput` / `checkParamValue` 的结果
 * @param reveal 是否已经失焦（或提交过一次），即「该摊牌了」
 */
export function shouldRevealIssue(issue: ParamCheck, reveal: boolean): ParamIssue | null {
  if (issue.ok) return null
  // 永远救不回来的，不等失焦；能靠继续输入自愈的，等失焦。
  if (!RECOVERABLE_REASONS.has(issue.reason)) return issue
  return reveal ? issue : null
}

/** 继续输入有可能自动变合法的原因码。 */
const RECOVERABLE_REASONS = new Set<ParamIssueReason>(['empty', 'below-min'])

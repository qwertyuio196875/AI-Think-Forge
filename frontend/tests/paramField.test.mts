/**
 * 参数型表单弹窗（工单 #4）的纯函数测试。
 *
 * 接缝（工单商定）：`frontend/src/utils/paramField.ts` 的公开纯函数——
 * 档位命中判定、初始值推导、上下界校验与可读提示。
 * 组件本身（ParamDialog / ParamField）只靠 `vue-tsc --noEmit` 兜类型。
 *
 * 期望值全部来自规格字面量（`C:\Users\33569\thinkforge-spec\issues\2.md`
 * 的 US 11–16 与 US 21–23），不由被测代码重新推导：
 * - 字数预设 1000 / 2000 / 3000 / 5000 / 8000 / 12000，自定义 300–20000；
 * - 页数预设 8 / 12 / 16 / 20 / 30，自定义 3–60；
 * - 超出范围必须明确说明原因，**绝不静默改成边界值**（US 14 / US 23）。
 *
 * 运行：`node --test tests/paramField.test.mts`（Node ≥23.6 原生剥离类型）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  PAGE_COUNT_PARAM,
  WORD_COUNT_PARAM,
  checkParamInput,
  checkParamValue,
  customPlaceholder,
  describeParamValue,
  isPresetValue,
  paramHint,
  presetLabels,
  rangeText,
  shouldRevealIssue,
  summarizeParamValue
} from '../src/utils/paramField.ts'

/* ---------- 规格常量：与 issue #2 的档位与范围字面量逐一对齐 ---------- */

test('字数参数：预设 1000/2000/3000/5000/8000/12000，范围 300–20000 字', () => {
  assert.deepEqual([...WORD_COUNT_PARAM.presets], [1000, 2000, 3000, 5000, 8000, 12000])
  assert.equal(WORD_COUNT_PARAM.min, 300)
  assert.equal(WORD_COUNT_PARAM.max, 20000)
  assert.equal(WORD_COUNT_PARAM.unit, '字')
  assert.equal(WORD_COUNT_PARAM.name, '目标字数')
})

test('页数参数：预设 8/12/16/20/30，范围 3–60 页', () => {
  assert.deepEqual([...PAGE_COUNT_PARAM.presets], [8, 12, 16, 20, 30])
  assert.equal(PAGE_COUNT_PARAM.min, 3)
  assert.equal(PAGE_COUNT_PARAM.max, 60)
  assert.equal(PAGE_COUNT_PARAM.unit, '页')
  assert.equal(PAGE_COUNT_PARAM.name, '页数')
})

test('范围文案统一为「下界–上界」，供提示与占位符复用', () => {
  assert.equal(rangeText(WORD_COUNT_PARAM), '300–20000')
  assert.equal(rangeText(PAGE_COUNT_PARAM), '3–60')
})

/* ---------- isPresetValue：命中档位才算预设 ---------- */

test('命中预设档位返回 true，自定义值一律 false（含 null）', () => {
  assert.equal(isPresetValue(3000, WORD_COUNT_PARAM), true)
  assert.equal(isPresetValue(12000, WORD_COUNT_PARAM), true)
  assert.equal(isPresetValue(4500, WORD_COUNT_PARAM), false)
  assert.equal(isPresetValue(300, WORD_COUNT_PARAM), false) // 边界合法但不是档位
  assert.equal(isPresetValue(null, WORD_COUNT_PARAM), false)
})

test('字数与页数的档位互不串用', () => {
  assert.equal(isPresetValue(3000, PAGE_COUNT_PARAM), false)
  assert.equal(isPresetValue(8, WORD_COUNT_PARAM), false)
  assert.equal(isPresetValue(8, PAGE_COUNT_PARAM), true)
})

/* ---------- describeParamValue：初始值推导（档位 / 自定义 / 空） ---------- */

test('初始值命中档位：选中该档，输入框显示该数值', () => {
  assert.deepEqual(describeParamValue(5000, WORD_COUNT_PARAM), {
    mode: 'preset',
    preset: 5000,
    text: '5000'
  })
})

test('初始值是自定义数值：不选中任何档位，输入框原样回显', () => {
  assert.deepEqual(describeParamValue(4500, WORD_COUNT_PARAM), {
    mode: 'custom',
    preset: null,
    text: '4500'
  })
})

test('无初始值：自定义态且输入框为空，不伪造档位', () => {
  assert.deepEqual(describeParamValue(null, WORD_COUNT_PARAM), {
    mode: 'custom',
    preset: null,
    text: ''
  })
  assert.deepEqual(describeParamValue(undefined, PAGE_COUNT_PARAM), {
    mode: 'custom',
    preset: null,
    text: ''
  })
})

/* ---------- checkParamInput：合法输入 ---------- */

test('范围内的整数通过校验，并回传解析后的数值', () => {
  assert.deepEqual(checkParamInput('3000', WORD_COUNT_PARAM), { ok: true, value: 3000 })
  assert.deepEqual(checkParamInput('8', PAGE_COUNT_PARAM), { ok: true, value: 8 })
})

test('上下界本身合法（等于边界不拒绝）', () => {
  assert.deepEqual(checkParamInput('300', WORD_COUNT_PARAM), { ok: true, value: 300 })
  assert.deepEqual(checkParamInput('20000', WORD_COUNT_PARAM), { ok: true, value: 20000 })
  assert.deepEqual(checkParamInput('3', PAGE_COUNT_PARAM), { ok: true, value: 3 })
  assert.deepEqual(checkParamInput('60', PAGE_COUNT_PARAM), { ok: true, value: 60 })
})

test('首尾空白被忽略（粘贴带空格不误判）', () => {
  assert.deepEqual(checkParamInput('  3000  ', WORD_COUNT_PARAM), { ok: true, value: 3000 })
})

/* ---------- checkParamInput：超范围必须明说，且不返回边界值 ---------- */

test('低于下限：说明当前值、下限与「不会自动改成下界」', () => {
  const res = checkParamInput('250', WORD_COUNT_PARAM)
  assert.equal(res.ok, false)
  if (res.ok) return
  assert.equal(res.reason, 'below-min')
  assert.match(res.message, /目标字数/)
  assert.match(res.message, /300–20000 字/)
  assert.match(res.message, /250/)
  assert.match(res.message, /不会自动改成 300/)
  // 关键：拒绝时绝不携带“已悄悄改成 300”的结果
  assert.equal('value' in res, false)
})

test('高于上限：说明当前值、上限与「不会自动改成上界」', () => {
  const res = checkParamInput('20001', WORD_COUNT_PARAM)
  assert.equal(res.ok, false)
  if (res.ok) return
  assert.equal(res.reason, 'above-max')
  assert.match(res.message, /20001/)
  assert.match(res.message, /不会自动改成 20000/)
  assert.equal('value' in res, false)
})

test('页数越界用页数自己的范围文案，不串用字数', () => {
  const low = checkParamInput('2', PAGE_COUNT_PARAM)
  assert.equal(low.ok, false)
  if (low.ok) return
  assert.equal(low.reason, 'below-min')
  assert.match(low.message, /页数/)
  assert.match(low.message, /3–60 页/)
  assert.match(low.message, /不会自动改成 3/)
  assert.doesNotMatch(low.message, /20000/)

  const high = checkParamInput('61', PAGE_COUNT_PARAM)
  assert.equal(high.ok, false)
  if (high.ok) return
  assert.equal(high.reason, 'above-max')
  assert.match(high.message, /不会自动改成 60/)
})

/* ---------- checkParamInput：非整数与空值 ---------- */

test('小数不被静默取整，明确说明只能填整数', () => {
  const res = checkParamInput('3000.5', WORD_COUNT_PARAM)
  assert.equal(res.ok, false)
  if (res.ok) return
  assert.equal(res.reason, 'not-integer')
  assert.match(res.message, /整数/)
  assert.match(res.message, /3000\.5/)
  assert.equal('value' in res, false)
})

test('空串与纯空白提示填写方式（档位或自定义）', () => {
  for (const raw of ['', '   ']) {
    const res = checkParamInput(raw, PAGE_COUNT_PARAM)
    assert.equal(res.ok, false)
    if (res.ok) continue
    assert.equal(res.reason, 'empty')
    assert.match(res.message, /页数/)
    assert.match(res.message, /3–60 页/)
  }
})

test('非数字输入（单位 / 千分位 / 文字）被判为非法，不猜一个数出来', () => {
  for (const raw of ['三千', '3,000', '3千', '1e3', '--3', '+', '3.']) {
    const res = checkParamInput(raw, WORD_COUNT_PARAM)
    assert.equal(res.ok, false, `期望 ${JSON.stringify(raw)} 被判非法`)
    if (res.ok) continue
    assert.equal(res.reason, 'not-a-number')
    assert.equal('value' in res, false)
  }
})

test('负号开头的数字按「低于下限」处理，而不是当成非法字符一笔带过', () => {
  const res = checkParamInput('-100', WORD_COUNT_PARAM)
  assert.equal(res.ok, false)
  if (res.ok) return
  assert.equal(res.reason, 'below-min')
})

/* ---------- checkParamValue：给父组件判定「确认」是否可用 ---------- */

test('合法数值通过；null / 非整数 / 越界各有原因', () => {
  assert.deepEqual(checkParamValue(3000, WORD_COUNT_PARAM), { ok: true, value: 3000 })
  assert.equal(checkParamValue(3000.5, WORD_COUNT_PARAM).ok, false)
  assert.equal(checkParamValue(Number.NaN, WORD_COUNT_PARAM).ok, false)
  assert.equal(checkParamValue(Number.POSITIVE_INFINITY, WORD_COUNT_PARAM).ok, false)
  assert.equal(checkParamValue(null, WORD_COUNT_PARAM).ok, false)
  assert.equal(checkParamValue(undefined, WORD_COUNT_PARAM).ok, false)
  assert.equal(checkParamValue(299, WORD_COUNT_PARAM).ok, false)
  assert.equal(checkParamValue(20001, WORD_COUNT_PARAM).ok, false)
  assert.equal(checkParamValue(61, PAGE_COUNT_PARAM).ok, false)
})

test('checkParamValue 与 checkParamInput 对同一数值给出同一结论（不出现两套口径）', () => {
  for (const n of [299, 300, 3000, 4500, 20000, 20001]) {
    const byValue = checkParamValue(n, WORD_COUNT_PARAM)
    const byInput = checkParamInput(String(n), WORD_COUNT_PARAM)
    assert.equal(byValue.ok, byInput.ok, `数值 ${n} 两处结论应一致`)
    if (byValue.ok && byInput.ok) assert.equal(byValue.value, byInput.value)
  }
})

test('非整数值校验的提示同样说明不会取整', () => {
  const res = checkParamValue(12.5, PAGE_COUNT_PARAM)
  assert.equal(res.ok, false)
  if (res.ok) return
  assert.equal(res.reason, 'not-integer')
  assert.match(res.message, /不会替你取整/)
  assert.match(res.message, /页数/)
})

/* ---------- 展示文案：组件只渲染，不再自己拼字符串 ---------- */

test('常驻提示说清「档位或自定义」以及超范围不会自动改边界值', () => {
  const word = paramHint(WORD_COUNT_PARAM)
  assert.match(word, /1000/)
  assert.match(word, /300–20000 字/)
  assert.match(word, /不会自动改成边界值/)

  const page = paramHint(PAGE_COUNT_PARAM)
  assert.match(page, /3–60 页/)
  assert.doesNotMatch(page, /20000/)
})

test('自定义输入框占位符带上本参数自己的区间与单位', () => {
  assert.equal(customPlaceholder(WORD_COUNT_PARAM), '自定义，300–20000 字')
  assert.equal(customPlaceholder(PAGE_COUNT_PARAM), '自定义，3–60 页')
})

test('档位按钮文案只给数值，单位在分组标签里统一说明', () => {
  assert.deepEqual(
    presetLabels(WORD_COUNT_PARAM),
    ['1000', '2000', '3000', '5000', '8000', '12000']
  )
  assert.deepEqual(presetLabels(PAGE_COUNT_PARAM), ['8', '12', '16', '20', '30'])
})

test('已确认值的单行摘要：命中档位说「常用档位」，自定义说「自定义」', () => {
  assert.equal(summarizeParamValue(3000, WORD_COUNT_PARAM), '3000 字（常用档位）')
  assert.equal(summarizeParamValue(4500, WORD_COUNT_PARAM), '4500 字（自定义）')
  assert.equal(summarizeParamValue(16, PAGE_COUNT_PARAM), '16 页（常用档位）')
  assert.equal(summarizeParamValue(null, PAGE_COUNT_PARAM), '未设置')
})

/* ---------- shouldRevealIssue：什么时候把红字摆出来 ---------- */

test('输入还合法时不显示任何提示', () => {
  assert.equal(shouldRevealIssue(checkParamInput('3000', WORD_COUNT_PARAM), false), null)
  assert.equal(shouldRevealIssue(checkParamInput('3000', WORD_COUNT_PARAM), true), null)
})

test('「可能还没输完」的原因（低于下限 / 空）留到失焦再说，避免每敲一位就闪红', () => {
  const typing = checkParamInput('2', WORD_COUNT_PARAM) // 用户正要输入 2000
  assert.equal(shouldRevealIssue(typing, false), null)
  const revealed = shouldRevealIssue(typing, true)
  assert.equal(revealed?.reason, 'below-min')

  const empty = checkParamInput('', WORD_COUNT_PARAM)
  assert.equal(shouldRevealIssue(empty, false), null)
  assert.equal(shouldRevealIssue(empty, true)?.reason, 'empty')
})

test('再多敲几位也救不回来的原因立刻说明（超上限 / 小数 / 非数字）', () => {
  assert.equal(shouldRevealIssue(checkParamInput('20001', WORD_COUNT_PARAM), false)?.reason, 'above-max')
  assert.equal(shouldRevealIssue(checkParamInput('3000.5', WORD_COUNT_PARAM), false)?.reason, 'not-integer')
  assert.equal(shouldRevealIssue(checkParamInput('三千', WORD_COUNT_PARAM), false)?.reason, 'not-a-number')
})

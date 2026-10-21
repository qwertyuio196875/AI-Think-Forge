/**
 * 字数分摊的展示辅助（工单 15）——纯函数测试。
 *
 * 接缝：`frontend/src/utils/wordBudget.ts` 的公开纯函数。
 * **不测分摊算法本身**：分摊只在后端实现一份（`backend/app/fill/budget.py`），
 * 前端再摊一遍就会出现「预览一个数、写出另一个数」（规格 §2 点名反对）。
 * 分摊的验收在后端 `backend/tests/test_fill_word_budget.py`。
 *
 * 期望值来自规格字面量（issue #2 的 US 12–19 与「字数控制」一节）：
 * - 预设 1000 / 2000 / 3000 / 5000 / 8000 / 12000，自定义 300–20000；
 * - 各章之和**恰好**等于目标字数；
 * - 超范围只说明原因，不静默改成边界值。
 *
 * 运行：`node --test tests/wordBudget.test.mts`。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  MAX_TARGET_LENGTH,
  MIN_TARGET_LENGTH,
  allocationSummary,
  checkSectionLength,
  initialTargetLength,
  sectionLengthHint
} from '../src/utils/wordBudget.ts'
import { WORD_COUNT_PARAM } from '../src/utils/paramField.ts'

/* ---------- 区间与档位必须与参数弹窗那一份完全一致 ---------- */

test('字数区间与档位与参数弹窗那份规格逐字一致（两处不许各写一套）', () => {
  assert.equal(MIN_TARGET_LENGTH, WORD_COUNT_PARAM.min)
  assert.equal(MAX_TARGET_LENGTH, WORD_COUNT_PARAM.max)
  assert.equal(MIN_TARGET_LENGTH, 300)
  assert.equal(MAX_TARGET_LENGTH, 20000)
})

/* ---------- allocationSummary：和是否恰好等于目标 ---------- */

test('和恰好等于目标 → 明说「与目标一致」', () => {
  const result = allocationSummary(1000, [333, 333, 334])
  assert.equal(result.sum, 1000)
  assert.equal(result.diff, 0)
  assert.equal(result.exact, true)
  assert.equal(result.text, '3 章合计 1000 字 · 与目标一致')
})

test('和少于目标 → 说出少多少（不掩饰差额）', () => {
  const result = allocationSummary(1000, [300, 300])
  assert.equal(result.sum, 600)
  assert.equal(result.diff, -400)
  assert.equal(result.exact, false)
  assert.equal(result.text, '2 章合计 600 字 · 比目标少 400 字')
})

test('和多于目标 → 说出多多少', () => {
  const result = allocationSummary(1000, [600, 600])
  assert.equal(result.sum, 1200)
  assert.equal(result.diff, 200)
  assert.equal(result.exact, false)
  assert.equal(result.text, '2 章合计 1200 字 · 比目标多 200 字')
})

test('没有章节时不说「与目标一致」（0 = 0 是伪一致）', () => {
  const result = allocationSummary(1000, [])
  assert.equal(result.sum, 0)
  assert.equal(result.exact, false)
  assert.equal(result.text, '还没有可分摊的章节')
})

test('目标为 0 且无章节也不能算作一致', () => {
  assert.equal(allocationSummary(0, []).exact, false)
})

test('非有限值不参与求和（脏数据不该把合计算成 NaN）', () => {
  const result = allocationSummary(1000, [500, Number.NaN, 500])
  assert.equal(result.sum, 1000)
  assert.equal(result.exact, true)
})

/* ---------- checkSectionLength：单格校验，不静默取整 ---------- */

test('合法正整数通过', () => {
  assert.deepEqual(checkSectionLength('800'), { ok: true, value: 800 })
  assert.deepEqual(checkSectionLength(' 1 '), { ok: true, value: 1 })
})

test('空值明确说「不能为空」，不当作 0', () => {
  const result = checkSectionLength('')
  assert.equal(result.ok, false)
  assert.match(result.ok === false ? result.message : '', /不能为空/)
})

test('小数与千分位一律拒绝，不替用户取整', () => {
  for (const raw of ['12.5', '1,200', '1e3', '-100']) {
    const result = checkSectionLength(raw)
    assert.equal(result.ok, false, `${raw} 不该通过`)
    assert.match(result.ok === false ? result.message : '', /只能填阿拉伯数字整数/)
  }
})

test('0 被拒绝：每章至少 1 字（0 字意味着这章不用写）', () => {
  const result = checkSectionLength('0')
  assert.equal(result.ok, false)
  assert.match(result.ok === false ? result.message : '', /至少 1 字/)
})

test('超过单章上限被拒绝并说明上限', () => {
  const result = checkSectionLength(String(MAX_TARGET_LENGTH + 1))
  assert.equal(result.ok, false)
  assert.match(result.ok === false ? result.message : '', new RegExp(String(MAX_TARGET_LENGTH)))
})

/* ---------- sectionLengthHint：说清来源 ---------- */

test('未改过的章标注「系统按权重分摊」', () => {
  assert.equal(sectionLengthHint(1200, false), '约 1200 字 · 系统按权重分摊')
})

test('改过的章标注「手动指定」（下次分摊不该悄悄覆盖）', () => {
  assert.equal(sectionLengthHint(700, true), '约 700 字 · 手动指定')
})

/* ---------- initialTargetLength：不伪造用户没给过的数 ---------- */

test('各章都有建议字数 → 求和作为初始值', () => {
  assert.equal(initialTargetLength([600, 400]), 1000)
})

test('有一章缺建议字数 → 不给初始值（求和会凭空缩水）', () => {
  assert.equal(initialTargetLength([600, null]), null)
})

test('没有章节 → 不给初始值', () => {
  assert.equal(initialTargetLength([]), null)
})

test('建议字数里有非正数 → 不给初始值', () => {
  assert.equal(initialTargetLength([600, 0]), null)
})

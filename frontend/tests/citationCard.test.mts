/**
 * 引用卡片的展示辅助（工单 23）——纯函数测试。
 *
 * 接缝：`frontend/src/utils/citationCard.ts` 的公开纯函数。
 * 检索、相关度计算、事实型判定都在后端，前端只负责把结论摆出来并让人取消采用。
 *
 * 期望值来自规格字面量（issue #2 的 US 与「引用卡片」一条）：
 * 「可折叠，默认全选，逐条可取消，显示文件名 · 段落号 · 相关度」。
 *
 * 运行：`node --test tests/citationCard.test.mts`。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  adoptionAllText,
  adoptionSummary,
  adoptedChunkIds,
  citationHeadline,
  citationLocator,
  isAdopted,
  isCollapsible,
  rejectedChunkIds,
  retrievalNotice,
  similarityPercent
} from '../src/utils/citationCard.ts'

function card(overrides = {}) {
  return {
    chunk_id: 1,
    name: '行业标准.md',
    seq: 1,
    similarity: 0.74,
    paragraph: 3,
    locator_label: '第 3 段',
    text: '行业通行的新员工培训周期是两周。',
    adopted: true,
    collapsible: true,
    ...overrides
  }
}

/* ---------- 相关度 ---------- */

test('相关度显示为百分比整数', () => {
  assert.equal(similarityPercent(0.7421), '74%')
  assert.equal(similarityPercent(1), '100%')
  assert.equal(similarityPercent(0), '0%')
})

test('非法相关度退回 0%，不显示 NaN%', () => {
  assert.equal(similarityPercent(Number.NaN), '0%')
  assert.equal(similarityPercent(-0.5), '0%')
})

/* ---------- 定位 ---------- */

test('定位优先用后端给的标签', () => {
  assert.equal(citationLocator(card()), '第 3 段')
})

test('没有标签时按段落号拼，仍没有就说「位置未标注」（不编位置）', () => {
  assert.equal(citationLocator(card({ locator_label: '' })), '第 3 段')
  assert.equal(citationLocator(card({ locator_label: '', paragraph: null })), '位置未标注')
})

/* ---------- 一行抬头：三样齐全 ---------- */

test('抬头同时给出文件名、段落号、相关度', () => {
  assert.equal(citationHeadline(card()), '行业标准.md · 第 3 段 · 相关度 74%')
})

test('文件名缺失时给占位，不留空', () => {
  assert.equal(citationHeadline(card({ name: '  ' })), '未知资料 · 第 3 段 · 相关度 74%')
})

/* ---------- 默认全选 ---------- */

test('字段缺失按采用处理（默认全选，不是默认不选）', () => {
  assert.equal(isAdopted({ chunk_id: 9 }), true)
})

test('后端明确 adopted: false 才算未采用', () => {
  assert.equal(isAdopted(card({ adopted: false })), false)
})

test('取消过的编号单独成清单，供提交时排除', () => {
  const cards = [card({ chunk_id: 1 }), card({ chunk_id: 2, adopted: false }), card({ chunk_id: 3 })]
  assert.deepEqual(adoptedChunkIds(cards), [1, 3])
  assert.deepEqual(rejectedChunkIds(cards), [2])
})

/* ---------- 采用摘要 ---------- */

test('全部采用时明说「全部采用」并给出条数', () => {
  const cards = [card({ chunk_id: 1 }), card({ chunk_id: 2 })]
  assert.equal(adoptionSummary(cards), adoptionAllText(2))
})

test('取消过则显示「已采用 x / y 条」', () => {
  const cards = [card({ chunk_id: 1 }), card({ chunk_id: 2, adopted: false }), card({ chunk_id: 3 })]
  assert.equal(adoptionSummary(cards), '已采用 2 / 3 条')
})

test('全部取消与没有引用是两种不同的话', () => {
  assert.equal(adoptionSummary([card({ adoption: false, adopted: false })]), '已全部取消（共 1 条）')
  assert.equal(adoptionSummary([]), '本次没有可用引用')
})

/* ---------- 检索状态必须明示 ---------- */

test('正常检索且未截断时不打扰', () => {
  assert.equal(
    retrievalNotice({ status: 'ok', status_label: '正常检索', degraded: false, truncated: false }),
    null
  )
})

test('降级检索必须说明原因', () => {
  const notice = retrievalNotice({
    status: 'degraded',
    status_label: '降级检索',
    message: '嵌入模型不可用，本次改用关键词检索',
    degraded: true,
    truncated: false
  })
  assert.ok(notice)
  assert.match(notice, /降级检索/)
  assert.match(notice, /关键词检索/)
})

test('未使用知识库也要说清楚，不能静默', () => {
  const notice = retrievalNotice({
    status: 'unavailable',
    status_label: '本次未使用知识库',
    message: '知识库里还没有已入库的资料',
    degraded: false,
    truncated: false
  })
  assert.ok(notice)
  assert.match(notice, /本次未使用知识库/)
})

test('命中被预算截断时提示（这是需要用户知道的情况）', () => {
  const notice = retrievalNotice({
    status: 'ok',
    status_label: '正常检索',
    degraded: false,
    truncated: true
  })
  assert.ok(notice)
  assert.match(notice, /上限/)
})

test('既无状态也无 message 时不抛错', () => {
  assert.equal(retrievalNotice(null), null)
  assert.equal(retrievalNotice(undefined), null)
})

/* ---------- 折叠 ---------- */

test('只有后端说可折叠才折叠', () => {
  assert.equal(isCollapsible(card()), true)
  assert.equal(isCollapsible(card({ collapsible: false })), false)
  assert.equal(isCollapsible({ chunk_id: 5 }), false)
})

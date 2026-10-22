/**
 * 引用勾选状态（工单 23）——只测本模块新增的逻辑。
 *
 * 「勾选 / 取消」语义复用 `citationCard.ts` 的现成 helper（rejectedChunkIds / isAdopted），
 * 那些已由 `citationCard.test.mts` 覆盖，这里不重复测试。
 * 本文件验证的是 helper 没有的四件事：拷贝种子（initCopies）、不可变 toggle（withAdopted）、
 * 跨题汇总去重（roundRejectedChunkIds）、折叠标题字面文案（citationsHeaderText）。
 *
 * 运行：`node --test tests/citationSelection.test.mts`。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  NO_CITATION_USE_TEXT,
  citationsHeaderText,
  copiesOfQuestion,
  initCopies,
  roundRejectedChunkIds,
  withAdopted
} from '../src/utils/citationSelection.ts'
import { isAdopted } from '../src/utils/citationCard.ts'

function card(chunkId: number, adopted = true) {
  return { chunk_id: chunkId, name: `资料${chunkId}.md`, seq: chunkId, similarity: 0.7, adopted }
}

function frontierOf(...lists: ReturnType<typeof card>[][]) {
  return lists.map((citations) => ({ citations }))
}

const q0 = [card(1), card(2), card(3)]

/* ---------- initCopies：拷贝种子 ---------- */

test('无引用的题不进映射（决策型问题没有「0 条」状态可言）', () => {
  assert.deepEqual(initCopies(frontierOf([])), {})
  assert.deepEqual(copiesOfQuestion(initCopies(frontierOf([])), 0), [])
})

test('副本沿用后端给的 adopted，默认即全部采用，汇总为空', () => {
  const copies = initCopies(frontierOf(q0))
  assert.deepEqual(roundRejectedChunkIds(copies), [])
  assert.ok(copiesOfQuestion(copies, 0).every(isAdopted))
})

test('toggle 只改副本，不污染传入的响应对象', () => {
  const src = [card(1)]
  const copies = withAdopted(initCopies(frontierOf(src)), 0, 1, false)
  assert.equal(isAdopted(copiesOfQuestion(copies, 0)[0]), false)
  assert.equal(src[0].adopted, true)
})

/* ---------- withAdopted：不可变 toggle ---------- */

test('取消一条后重新勾选即恢复，汇总回到空', () => {
  let copies = withAdopted(initCopies(frontierOf(q0)), 0, 2, false)
  assert.deepEqual(roundRejectedChunkIds(copies), [2])
  copies = withAdopted(copies, 0, 2, true)
  assert.deepEqual(roundRejectedChunkIds(copies), [])
})

test('状态没有变化时返回原引用（不触发多余的响应式更新）', () => {
  const copies = withAdopted(initCopies(frontierOf(q0)), 0, 2, false)
  assert.equal(withAdopted(copies, 0, 2, false), copies)
  assert.equal(withAdopted(copies, 0, 1, true), copies)
})

test('对不存在的题目做 toggle 返回原引用（不凭空造题）', () => {
  const copies = initCopies(frontierOf(q0))
  assert.equal(withAdopted(copies, 9, 1, false), copies)
})

/* ---------- roundRejectedChunkIds：跨题汇总去重 ---------- */

test('跨题汇总去重：同一片段被两题取消只提交一次', () => {
  let copies = initCopies(frontierOf([card(7)], [card(7), card(8)]))
  copies = withAdopted(copies, 0, 7, false)
  copies = withAdopted(copies, 1, 7, false)
  copies = withAdopted(copies, 1, 8, false)
  assert.deepEqual(roundRejectedChunkIds(copies), [7, 8])
})

test('汇总按题目下标升序，载荷可比对', () => {
  let copies = initCopies(frontierOf([card(10)], [card(20)], [card(30)]))
  copies = withAdopted(copies, 2, 30, false)
  copies = withAdopted(copies, 0, 10, false)
  copies = withAdopted(copies, 1, 20, false)
  assert.deepEqual(roundRejectedChunkIds(copies), [10, 20, 30])
})

/* ---------- citationsHeaderText：折叠标题的字面文案 ---------- */

test('默认态标题说「参考资料 · N 条 · 默认全部采用」', () => {
  const copies = initCopies(frontierOf(q0))
  assert.equal(citationsHeaderText(copies, 0), '参考资料 · 3 条 · 默认全部采用')
})

test('取消部分时标题给出「已采用 x / y」', () => {
  const copies = withAdopted(initCopies(frontierOf(q0)), 0, 2, false)
  assert.equal(citationsHeaderText(copies, 0), '参考资料 · 3 条 · 已采用 2 / 3')
})

test('全部取消时标题明确写「本次不使用任何资料片段」', () => {
  let copies = initCopies(frontierOf(q0))
  for (const c of q0) copies = withAdopted(copies, 0, c.chunk_id, false)
  assert.equal(citationsHeaderText(copies, 0), `参考资料 · 3 条 · ${NO_CITATION_USE_TEXT}`)
})

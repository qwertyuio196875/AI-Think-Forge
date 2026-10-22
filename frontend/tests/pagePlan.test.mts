/**
 * 页面规划前端逻辑（工单 26）——验收点的可测落点。
 *
 * 工单 26 的四条验收都能在这一层钉住，不必挂组件测试框架：
 * ① 预览显示每页归属哪个章节 → `pageOwnershipLabel`
 * ② 增删后页数以新规划为准 → `pagesAfterDelete`
 * ③ 界面显示实际页数、不再强制等于目标 → `pageCountSummary`
 * ④ 能发现重点被挤到最后一页 → `crampedPages`
 *
 * 外加页数区间校验（工单 25 验收 ⑤：区间外明确拒绝）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  MAX_PAGES,
  MIN_PAGES,
  PAGE_PRESETS,
  crampedPages,
  isDeletable,
  pageCountSummary,
  pageOwnershipLabel,
  pagesAfterDelete,
  validatePageCount,
  type PagePlan
} from '../src/utils/pagePlan.ts'

function plan(pages: PagePlan['pages'], target = 4): PagePlan {
  return {
    page_plan_id: 1,
    task_id: 7,
    plan_id: 3,
    target_pages: target,
    actual_pages: pages.length,
    pages
  }
}

/* ---------- 验收 ①：预览显示每页归属哪个章节 ---------- */

test('归属标签：封面/结尾没有章节，单章与合并章分别说清楚', () => {
  assert.equal(
    pageOwnershipLabel({ index: 1, kind: 'cover', title: '演示', chapter_seqs: [] }),
    '封面'
  )
  assert.equal(
    pageOwnershipLabel({ index: 5, kind: 'end', title: '谢谢', chapter_seqs: [] }),
    '结尾页'
  )
  assert.equal(
    pageOwnershipLabel({ index: 2, kind: 'content', title: '全景', chapter_seqs: [1] }),
    '第 1 章'
  )
  // 合并页必须能看出「这是多章挤在一页」，否则用户发现不了重点被挤压。
  assert.equal(
    pageOwnershipLabel({ index: 3, kind: 'content', title: '合并', chapter_seqs: [2, 4] }),
    '第 2、4 章（合并）'
  )
})

/* ---------- 验收 ③：显示实际页数，不再强制等于目标 ---------- */

test('页数摘要：一致时说一致，增删后如实显示偏差（不假装相等）', () => {
  const same = plan(
    [
      { index: 1, kind: 'cover', title: 'a', chapter_seqs: [] },
      { index: 2, kind: 'content', title: 'b', chapter_seqs: [1] },
      { index: 3, kind: 'end', title: 'c', chapter_seqs: [] }
    ],
    3
  )
  assert.equal(pageCountSummary(same), '共 3 页（与目标一致）')

  // 加了一页：目标 3、实际 4，必须显示 +1。
  const more = plan(
    [
      { index: 1, kind: 'cover', title: 'a', chapter_seqs: [] },
      { index: 2, kind: 'content', title: 'b', chapter_seqs: [1] },
      { index: 3, kind: 'content', title: 'b2', chapter_seqs: [1] },
      { index: 4, kind: 'end', title: 'c', chapter_seqs: [] }
    ],
    3
  )
  assert.equal(pageCountSummary(more), '共 4 页（目标 3，+1）')

  // 删了一页：目标 3、实际 2，必须显示 -1。
  const fewer = plan(
    [
      { index: 1, kind: 'cover', title: 'a', chapter_seqs: [] },
      { index: 2, kind: 'end', title: 'c', chapter_seqs: [] }
    ],
    3
  )
  assert.equal(pageCountSummary(fewer), '共 2 页（目标 3，-1）')
})

/* ---------- 验收 ④：能发现重点被挤到后面 ---------- */

test('挤压检测：合并了多章的内容页要被点出来，正常页不误报', () => {
  const p = plan([
    { index: 1, kind: 'cover', title: '封', chapter_seqs: [] },
    { index: 2, kind: 'content', title: '单章', chapter_seqs: [1] },
    { index: 3, kind: 'content', title: '挤了三章', chapter_seqs: [2, 3, 4] },
    { index: 4, kind: 'end', title: '谢', chapter_seqs: [] }
  ])
  const flagged = crampedPages(p)
  assert.equal(flagged.length, 1)
  assert.deepEqual(flagged[0].chapter_seqs, [2, 3, 4])
})

/* ---------- 验收 ②：增删后页数以新规划为准 ---------- */

test('删页后的预览：其余页 index 依次前移，且封面/结尾不可删', () => {
  const before = plan([
    { index: 1, kind: 'cover', title: '封', chapter_seqs: [] },
    { index: 2, kind: 'content', title: 'A', chapter_seqs: [1] },
    { index: 3, kind: 'content', title: 'B', chapter_seqs: [2] },
    { index: 4, kind: 'end', title: '谢', chapter_seqs: [] }
  ])

  const after = pagesAfterDelete(before, 2)

  assert.deepEqual(
    after.map((p) => p.index),
    [1, 2, 3]
  )
  assert.deepEqual(
    after.map((p) => p.title),
    ['封', 'B', '谢']
  )
  // 结构页不可删：删了 deck 的首尾契约就破了。
  assert.equal(isDeletable(before.pages[0]), false)
  assert.equal(isDeletable(before.pages[3]), false)
  assert.equal(isDeletable(before.pages[1]), true)
})

/* ---------- 工单 25 验收 ⑤：页数区间 ---------- */

test('页数校验：区间外明确说明原因，不静默夹紧', () => {
  assert.equal(validatePageCount(16), null)
  assert.equal(validatePageCount(8), null)
  assert.equal(validatePageCount(undefined), '请选择或输入页数')
  assert.match(validatePageCount(2) ?? '', /页数需在 3–60 之间.*当前 2/)
  assert.match(validatePageCount(99) ?? '', /3–60/)
  assert.match(validatePageCount(8.5) ?? '', /整数/)
  assert.deepEqual(PAGE_PRESETS, [8, 12, 16, 20, 30])
  assert.equal(MIN_PAGES, 3)
  assert.equal(MAX_PAGES, 60)
})

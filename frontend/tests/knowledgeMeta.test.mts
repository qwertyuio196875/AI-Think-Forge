/**
 * 知识库清单页纯函数测试（工单 19）。
 * 接缝（工单商定）：frontend/src/utils/knowledgeMeta.ts 的公开纯函数；
 * 运行方式 `node --test tests/`（Node ≥23.6 原生剥离类型，零新增依赖）。
 * 期望值来自规格与后端契约（backend/app/models/knowledge.py 的
 * INDEX_STATUS_LABELS），不由被测代码重新推导。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  INDEX_STATUS_ORDER,
  indexStatusTag,
  indexStatusDetail,
  formatChunkCount,
  knowledgeDisplayName
} from '../src/utils/knowledgeMeta.ts'

/* ---------- indexStatusTag：状态取值域与中文标签严格对齐后端 ---------- */

test('索引状态取值域三个值各有中文标签与色调', () => {
  assert.deepEqual(indexStatusTag('stored'), { label: '已入库', type: 'success' })
  assert.deepEqual(indexStatusTag('indexing'), { label: '索引中', type: 'warning' })
  // 失败必须是 danger：绝不与「已入库」同色，让人一眼看出没进索引
  assert.deepEqual(indexStatusTag('failed'), { label: '索引失败', type: 'danger' })
})

test('未知索引状态原样显示为中性标签，不冒充「已入库」', () => {
  assert.deepEqual(indexStatusTag('mystery'), { label: 'mystery', type: 'info' })
  assert.equal(indexStatusTag('').label, '')
})

test('INDEX_STATUS_ORDER 覆盖全部取值且顺序固定（stored/indexing/failed）', () => {
  assert.deepEqual(INDEX_STATUS_ORDER, ['stored', 'indexing', 'failed'])
  for (const status of INDEX_STATUS_ORDER) {
    assert.equal(indexStatusTag(status).label !== '', true)
  }
})

/* ---------- indexStatusDetail：失败原因必须可见 ---------- */

test('索引失败且带原因时把原因原样给出', () => {
  assert.equal(
    indexStatusDetail({ index_status: 'failed', index_message: '不是有效的 DOCX' }),
    '不是有效的 DOCX'
  )
})

test('索引失败但没有原因时给出兜底说明，不静默留空', () => {
  assert.equal(
    indexStatusDetail({ index_status: 'failed', index_message: null }),
    '索引失败，原因未记录'
  )
})

test('已入库与索引中不显示失败原因（有残留文案也不展示）', () => {
  assert.equal(indexStatusDetail({ index_status: 'stored', index_message: '旧错误' }), '')
  assert.equal(indexStatusDetail({ index_status: 'indexing', index_message: null }), '')
})

/* ---------- formatChunkCount：清单页的分块数展示 ---------- */

test('分块数按「N 块」展示', () => {
  assert.equal(formatChunkCount(1), '1 块')
  assert.equal(formatChunkCount(12), '12 块')
})

test('零分块与缺失都如实说明，不显示负数或 undefined', () => {
  assert.equal(formatChunkCount(0), '0 块')
  assert.equal(formatChunkCount(null), '—')
  assert.equal(formatChunkCount(undefined), '—')
})

/* ---------- knowledgeDisplayName：文件名优先，缺失不编造标题 ---------- */

test('文件名优先显示', () => {
  assert.equal(
    knowledgeDisplayName({ name: '产品说明.docx', ref: 'uploads/abc.docx' }),
    '产品说明.docx'
  )
})

test('没有文件名时退回 ref，两者都没有时为「未命名资料」', () => {
  assert.equal(knowledgeDisplayName({ name: '', ref: 'uploads/abc.docx' }), 'uploads/abc.docx')
  assert.equal(knowledgeDisplayName({ name: '  ', ref: '' }), '未命名资料')
})

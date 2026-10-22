/**
 * 单章填充 + 引用（工单 24）——API 契约与展示逻辑测试。
 *
 * 接缝（无组件测试框架，沿用仓库既有做法）：
 * 1) `frontend/src/api/client.ts` 的 `previewSectionReferences` / `fillSection`：
 *    用替身 fetch 断言它们只打对应的端点、带正确的 HTTP 方法与请求体、原样透出字段；
 * 2) 组件行为依赖 `frontend/src/utils/citationCard.ts` 的既有纯函数
 *    （默认全选 / 被取消的不提交 / 卡片抬头与定位 / 检索降级明示），此处回归校验
 *    「默认全选 = 所有 chunk 都在 keep 列表」这一工单 24 的核心不变量。
 *
 * 期望值来自工单 24、ADR-0005（引用可撤销 + 资料只列实际用到的来源）与后端契约
 * （`backend/app/models/fill.py::SectionFillRequest/SectionReferencesResponse`、
 *  `backend/app/api/routes/fill.py`），不由被测代码重新推导。
 *
 * 运行：`node --test tests/sectionFill.test.mts`（Node ≥23.6 原生剥离类型）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  ApiHttpError,
  fillSection,
  previewSectionReferences,
  type CitationCard,
  type PlanSectionItem,
  type GenerationResponse,
  type SectionReferencesResponse,
  type SectionWriteResponse
} from '../src/api/client.ts'
import {
  adoptedChunkIds,
  citationHeadline,
  citationLocator,
  isAdopted,
  retrievalNotice
} from '../src/utils/citationCard.ts'

/** 一条引用卡片（与后端契约同构）。 */
function card(overrides: Partial<CitationCard> = {}): CitationCard {
  return {
    chunk_id: 1,
    document_id: 10,
    source_id: 20,
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

/** 一份章节项（与后端契约同构）。 */
function planItem(overrides: Partial<PlanSectionItem> = {}): PlanSectionItem {
  return {
    seq: 1,
    title: '产品全景',
    key_points: '三条真实场景讲清主线',
    target_length: 1200,
    hanzi_count: 0,
    status: 'pending',
    status_label: '待写',
    completed_at: null,
    ...overrides
  }
}

/** 一份成品记录（与后端契约同构）。 */
function generation(overrides: Partial<GenerationResponse> = {}): GenerationResponse {
  return {
    id: 50,
    task_id: 42,
    plan_id: 12,
    format: 'docx',
    file_path: 'E:/deliverables/正文.docx',
    template_used: '_builtin/minimal-default.docx',
    created_at: '2026-10-20T12:00:00+08:00',
    template_style_applied: true,
    missing_styles: [],
    headings: 3,
    integrity_ok: true,
    theme_used: null,
    inlined_fonts: [],
    cjk_fallback: false,
    slides: 0,
    ...overrides
  }
}

test('previewSectionReferences 只打 POST /tasks/{id}/sections/{seq}/references，并原样透出字段', async () => {
  const payload: SectionReferencesResponse = {
    task_id: 42,
    seq: 1,
    cards: [card({ chunk_id: 1 }), card({ chunk_id: 2, adopted: true })],
    retrieval_status: { status: 'ok', status_label: '正常', message: null, degraded: false, truncated: false }
  }
  const urls: string[] = []
  const inits: Array<RequestInit | undefined> = []
  const original = globalThis.fetch
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    urls.push(String(input))
    inits.push(init)
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    })
  }) as typeof fetch
  try {
    const res = await previewSectionReferences(42, 1)
    assert.deepEqual(urls, ['http://127.0.0.1:8720/api/tasks/42/sections/1/references'])
    // 只读预览：POST 但不带请求体
    assert.equal(inits[0]?.method, 'POST')
    assert.equal(inits[0]?.body, undefined)
    assert.deepEqual(res, payload)
    // 默认全选：所有卡片都被视为采用
    assert.deepEqual(adoptedChunkIds(res.cards), [1, 2])
  } finally {
    globalThis.fetch = original
  }
})

test('fillSection 把保留的引用卡片作为 reference_cards 提交（被取消的不在请求体里）', async () => {
  const done: SectionWriteResponse = {
    task_id: 42,
    fill_id: 9,
    section: planItem({ status: 'completed', status_label: '已完成', hanzi_count: 812 }),
    deliverable: generation()
  }
  let calledBody: unknown
  const original = globalThis.fetch
  globalThis.fetch = (async (_input: string | URL | Request, init?: RequestInit) => {
    calledBody = init?.body
    return new Response(JSON.stringify(done), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    })
  }) as typeof fetch
  try {
    // 主 3、取消第一条（chunk 41）：只保留第二条进请求体
    const kept = [card({ chunk_id: 42, name: '场景库.md' })]
    const res = await fillSection(42, 1, { reference_cards: kept })
    const body = JSON.parse(String(calledBody)) as { reference_cards?: CitationCard[] }
    assert.deepEqual(body.reference_cards, kept)
    assert.deepEqual(body.reference_cards?.map((c) => c.chunk_id), [42])
    assert.deepEqual(res, done)
  } finally {
    globalThis.fetch = original
  }
})

test('fillSection 不带引用卡片时不发送 reference_cards 字段', async () => {
  const done: SectionWriteResponse = {
    task_id: 42,
    fill_id: 9,
    section: planItem({ status: 'completed', status_label: '已完成', hanzi_count: 600 }),
    deliverable: generation()
  }
  let calledBody: unknown
  const original = globalThis.fetch
  globalThis.fetch = (async (_input: string | URL | Request, init?: RequestInit) => {
    calledBody = init?.body
    return new Response(JSON.stringify(done), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    })
  }) as typeof fetch
  try {
    const res = await fillSection(42, 1, {})
    const body = JSON.parse(String(calledBody)) as { reference_cards?: CitationCard[] }
    assert.equal('reference_cards' in body, false)
    assert.deepEqual(res, done)
  } finally {
    globalThis.fetch = original
  }
})

test('章不存在时 previewSectionReferences 抛 404 ApiHttpError，由组件显式提示', async () => {
  const original = globalThis.fetch
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ detail: '任务 42 没有第 9 章' }), {
      status: 404,
      headers: { 'Content-Type': 'application/json' }
    })) as typeof fetch
  try {
    await assert.rejects(
      () => previewSectionReferences(42, 9),
      (err: unknown) => {
        assert.ok(err instanceof ApiHttpError)
        assert.equal((err as ApiHttpError).status, 404)
        assert.equal((err as ApiHttpError).detail, '任务 42 没有第 9 章')
        return true
      }
    )
  } finally {
    globalThis.fetch = original
  }
})

test('引用展示文案：文件名 · 定位 · 相关度，默认全选（工单 24 / 23 共享）', () => {
  const c = card()
  assert.equal(citationHeadline(c), '行业标准.md · 第 3 段 · 相关度 74%')
  assert.equal(citationLocator(c), '第 3 段')
  assert.equal(isAdopted(c), true)
  assert.equal(adoptedChunkIds([c, card({ chunk_id: 2 })]).length, 2)
})

test('检索降级 / 未使用知识库时明示，正常检索不打扰', () => {
  assert.equal(
    retrievalNotice({ status: 'degraded', status_label: '降级', message: '嵌入不可用，已用关键词', degraded: true, truncated: false }),
    '降级：嵌入不可用，已用关键词'
  )
  assert.equal(
    retrievalNotice({ status: 'ok', status_label: '正常', message: null, degraded: false, truncated: false }),
    null
  )
})
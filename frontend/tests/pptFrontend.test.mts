/**
 * 截图版 PPT 前端（工单 30）——测试先行。
 *
 * 接缝（沿用仓库既有做法：`node --test` 直接测公开调用方，不挂组件测试框架）：
 * 1) `frontend/src/utils/generationFormats.ts` 的纯函数：成品格式的展示元数据。
 *    这是把「选择 PPT 之前就看到可编辑 vs 截图说明」这条规格落到可测位置的接缝，
 *    组件只消费它，不各自硬编码。
 * 2) `frontend/src/api/client.ts` 的 `generateDeliverable` / `fetchDeliverable`：
 *    用替身 fetch 断言 pptx 请求体带 `format: 'pptx'` + `theme`，且下载链路命中
 *    `/api/deliverables/{generation_id}`（后端投递白名单能吞 .pptx）。
 *
 * 期望值来自工单 30、ADO-0004 后果节（「PPT 对外口径必须写明是图片型、文字不可编辑、
 * 不可检索」）与后端契约，不由被测代码重新推导。
 *
 * 运行：`node --test tests/pptFrontend.test.mts`（Node ≥23.6 原生剥离类型）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { formatMeta, formatOptions, isThemeBased } from '../src/utils/generationFormats.ts'
import { generateDeliverable, fetchDeliverable } from '../src/api/client.ts'

/* ---------- 格式卡片元数据：PPT 已启用 + 选择前就讲清可编辑 vs 截图 ---------- */

test('三个格式都出现在选项清单里（docx / html / pptx），pptx 不再是「计划」', () => {
  const formats = formatOptions().map((f) => f.format)
  // 「v1.1 计划 / 灰置」的旧状态已经不存在：pptx 必须是一个真正可达的可选项。
  assert.deepEqual(formats, ['docx', 'html', 'pptx'])
  // 三个选项都在清单里：同一份内容可同时导 Word / HTML / PPT（互不排斥）。
  for (const f of ['docx', 'html', 'pptx'] as const) {
    assert.ok(formatOptions().some((o) => o.format === f), `${f} 应为可选格式`)
  }
})

test('pptx 卡片说明在选择前就写明「截图版：可展示、文字不可编辑、不可检索」', () => {
  const meta = formatMeta('pptx')
  // ADR-0004 后果节：对外口径必须写明是图片型 / 文字不可编辑 / 不可检索。
  assert.match(meta.desc, /截图/)
  assert.match(meta.desc, /图片/)
  assert.match(meta.desc, /不可编辑/)
  assert.match(meta.desc, /不可检索/)
})

test('与实际相反的旧文案已删除（不再出现「v1 不生成 .pptx / 冒充 PPT」）', () => {
  const allText = formatOptions().map((f) => `${f.title} ${f.desc}`).join(' ')
  assert.ok(!allText.includes('v1 不生成'), '旧文案「v1 不生成 .pptx」必须删除')
  assert.ok(!allText.includes('冒充'), '旧文案「把 HTML 或截图冒充 PPT」必须删除')
  assert.ok(!allText.includes('v1.1 计划'), '「v1.1 计划」灰置标签必须删除')
})

/* ---------- theme 归属：html 与 pptx 都按主题，docx 按模板 ---------- */

test('html 与 pptx 共用主题选择器，docx 走模板（不是主题）', () => {
  assert.equal(isThemeBased('html'), true)
  assert.equal(isThemeBased('pptx'), true)
  assert.equal(isThemeBased('docx'), false)
})

/* ---------- 生成请求体：format=pptx + 可选 theme ---------- */

test('generateDeliverable 请求 body 带 format=pptx，并透传 theme', async () => {
  let calledInits: RequestInit | undefined
  let calledUrl = ''
  const original = globalThis.fetch
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    calledUrl = String(input)
    calledInits = init
    return new Response(
      JSON.stringify({
        id: 77,
        task_id: 42,
        plan_id: 12,
        format: 'pptx',
        file_path: 'E:/deliverables/demo.pptx',
        template_used: 'deck-theme:slate',
        created_at: '2026-10-21T10:00:00+08:00',
        integrity_ok: true
      }),
      { status: 201, headers: { 'Content-Type': 'application/json' } }
    )
  }) as typeof fetch
  try {
    await generateDeliverable(42, { format: 'pptx', theme: 'slate' })
    assert.equal(calledUrl, 'http://127.0.0.1:8720/api/tasks/42/generations')
    const body = JSON.parse(String(calledInits?.body)) as {
      format: string
      theme: string | null
    }
    assert.equal(body.format, 'pptx')
    assert.equal(body.theme, 'slate')
  } finally {
    globalThis.fetch = original
  }
})

test('generateDeliverable 不指定 theme 时请求体 theme 为 null（走全局默认）', async () => {
  let calledInits: RequestInit | undefined
  const original = globalThis.fetch
  globalThis.fetch = (async (_input: string | URL | Request, init?: RequestInit) => {
    calledInits = init
    return new Response(
      JSON.stringify({
        id: 78,
        task_id: 42,
        plan_id: 12,
        format: 'pptx',
        file_path: 'E:/deliverables/demo.pptx',
        template_used: 'deck-theme:slate',
        created_at: '2026-10-21T10:00:00+08:00',
        integrity_ok: true
      }),
      { status: 201, headers: { 'Content-Type': 'application/json' } }
    )
  }) as typeof fetch
  try {
    await generateDeliverable(42, { format: 'pptx' })
    const body = JSON.parse(String(calledInits?.body)) as { theme: string | null }
    assert.equal(body.theme, null)
  } finally {
    globalThis.fetch = original
  }
})

/* ---------- 下载链路：fetchDeliverable 命中 /deliverables/{id} ---------- */

test('fetchDeliverable 命中 /api/deliverables/{generation_id}，pptx 走同一投递通道', async () => {
  const urls: string[] = []
  const original = globalThis.fetch
  globalThis.fetch = (async (input: string | URL | Request) => {
    urls.push(String(input))
    return new Response(new Uint8Array([0x50, 0x4b]), { status: 200 })
  }) as typeof fetch
  try {
    const resp = await fetchDeliverable(77)
    assert.equal(urls[0], 'http://127.0.0.1:8720/api/deliverables/77')
    assert.equal(resp.status, 200)
  } finally {
    globalThis.fetch = original
  }
})
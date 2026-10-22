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
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { formatMeta, formatOptions, isThemeBased } from '../src/utils/generationFormats.ts'
import { generateDeliverable, fetchDeliverable } from '../src/api/client.ts'

/* ---------- 扫描前端源码的辅助（用于「旧文案必须消失」这类全局断言） ---------- */

const SRC_ROOT = fileURLToPath(new URL('../src', import.meta.url))

/** 递归收集 src 下的 .vue / .ts 源文件（跳过 .d.ts）。 */
function sourceFiles(dir: string = SRC_ROOT): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) {
      out.push(...sourceFiles(full))
    } else if (/\.(vue|ts)$/.test(entry.name) && !entry.name.endsWith('.d.ts')) {
      out.push(full)
    }
  }
  return out
}

/**
 * 取一个源文件里**用户可见**的文案行：跳过纯注释行（`//`、`*`、`<!--`）。
 *
 * 注释里引用旧文案做对照是正常写法（「与『v1 不生成 .pptx』明确切割」），
 * 不应当被当成「旧文案仍在」。行内注释也一并去掉尾巴再判断。
 */
function userVisibleLines(file: string): string[] {
  const lines: string[] = []
  for (const raw of readFileSync(file, 'utf8').split(/\r?\n/)) {
    const trimmed = raw.trim()
    if (
      trimmed.startsWith('//') ||
      trimmed.startsWith('*') ||
      trimmed.startsWith('/*') ||
      trimmed.startsWith('<!--')
    ) {
      continue
    }
    // 去掉行内注释尾巴（保守：只处理 ` // ` 与 ` <!-- ` 之后的部分）。
    lines.push(trimmed.split(' // ')[0].split(' <!-- ')[0])
  }
  return lines
}

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

test('与实际相反的旧文案已删除（扫全部前端源码，不只看格式清单）', () => {
  // 只断言 formatOptions() 里的字符串会「假绿」：旧文案真正的藏身处是组件模板
  // （GenerationPanel / SettingsView）。所以这里把 src 下所有 .vue/.ts 读进来一起扫。
  //
  // 只扫**用户可见文案**（模板文本 / 字符串字面量），跳过注释：注释里引用旧文案
  // 做对照说明是正常写法（「与『v1 不生成 .pptx』明确切割」），不该被当成残留。
  const stale = ['v1 不生成', '冒充 PPT', 'v1.1 计划', '两条路互不转换']
  const offenders: string[] = []
  for (const file of sourceFiles()) {
    for (const line of userVisibleLines(file)) {
      for (const phrase of stale) {
        if (line.includes(phrase)) {
          offenders.push(`${relative(SRC_ROOT, file)}: 「${phrase}」→ ${line.trim()}`)
        }
      }
    }
  }
  assert.deepEqual(offenders, [], `与实际相反的旧文案必须删除，实际仍在：\n${offenders.join('\n')}`)
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
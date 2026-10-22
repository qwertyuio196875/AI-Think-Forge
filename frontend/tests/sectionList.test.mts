/**
 * 确认后章节清单卡（工单 8）的纯函数与契约测试。
 *
 * 接缝（无组件测试框架，沿用仓库既有做法）：
 * 1) `frontend/src/utils/sectionList.ts` 的公开纯函数：清单行文案、状态标签、
 *    空清单提示、按 plan_id 判定清单是否过期；
 * 2) `frontend/src/api/client.ts` 的 `listPlanSections`：用替身 fetch 断言它只打
 *    `GET /tasks/{id}/sections`，且返回值原样透出后端字段（不重算、不猜字段）；
 * 3) 只读边界的源码级守卫：没有改名 / 排序 / 增删章节的结构编辑 API 与界面入口
 *    （工单 24 的引用预览与单章填充是写内容，不改变目录结构，故不在禁列）。
 *
 * 期望值来自工单 8、规格 US5–US6 与后端契约
 * （`backend/app/models/plan_section.py`、`backend/app/api/routes/sections.py`），
 * 不由被测代码重新推导。
 *
 * 运行：`node --test tests/sectionList.test.mts`（Node ≥23.6 原生剥离类型）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  EMPTY_SECTIONS_HINT,
  READONLY_NOTICE,
  RETURN_TO_REVISE_LABEL,
  isSectionListStale,
  sectionLengthText,
  sectionLine,
  sectionLines,
  sectionListHeadline,
  sectionStatusLabel,
  sectionStatusTag
} from '../src/utils/sectionList.ts'
import client, {
  ApiHttpError,
  listPlanSections,
  type PlanSectionItem,
  type PlanSectionListResponse
} from '../src/api/client.ts'

/** 后端 `PlanSectionItem` 的一份真实形状样例（字段名逐一照抄契约）。 */
function item(overrides: Partial<PlanSectionItem> = {}): PlanSectionItem {
  return {
    seq: 1,
    title: '背景与目标',
    key_points: '为什么做、做到什么程度',
    target_length: 1200,
    hanzi_count: 0,
    status: 'pending',
    status_label: '待写',
    completed_at: null,
    ...overrides
  }
}

/** 组件与客户端的源码文本：用于「不提供编辑入口」的源码级守卫。 */
function source(relative: string): string {
  return readFileSync(new URL(relative, import.meta.url), 'utf8')
}

/* ---------- 状态标签：三态与后端中文标签严格一致 ---------- */

test('章节状态三态各有中文标签与色调，取值域与后端 PlanSectionStatus 一致', () => {
  assert.deepEqual(sectionStatusTag('pending'), { label: '待写', type: 'info' })
  assert.deepEqual(sectionStatusTag('completed'), { label: '已完成', type: 'success' })
  // 失败必须与「已完成」明显不同色，否则写挂的章节会被看成写好了
  assert.deepEqual(sectionStatusTag('failed'), { label: '失败', type: 'danger' })
})

test('未知状态原样显示为中性标签，不冒充「待写」', () => {
  assert.deepEqual(sectionStatusTag('mystery'), { label: 'mystery', type: 'info' })
  assert.equal(sectionStatusTag('').label, '')
})

test('状态文案优先用后端给的 status_label，缺省才回落到本地映射', () => {
  assert.equal(sectionStatusLabel(item({ status: 'completed', status_label: '已完成' })), '已完成')
  assert.equal(sectionStatusLabel(item({ status: 'failed', status_label: '' })), '失败')
  assert.equal(sectionStatusLabel(item({ status: 'pending', status_label: '  待写  ' })), '待写')
})

/* ---------- 清单行文案：工单要求的「1. 标题（约 X 字）」 ---------- */

test('清单行是「序号. 标题（约 X 字）」，序号取后端的 seq 而不是数组下标', () => {
  assert.equal(sectionLine(item()), '1. 背景与目标（约 1200 字）')
  // 序号若跳过（例如删过章节），仍按后端 seq 显示，不悄悄改序号
  assert.equal(sectionLine(item({ seq: 3, title: '实施步骤', target_length: 800 })), '3. 实施步骤（约 800 字）')
})

test('建议字数缺失时显示「字数未定」，绝不编造或补 0', () => {
  assert.equal(sectionLengthText(null), '字数未定')
  assert.equal(sectionLengthText(undefined), '字数未定')
  assert.equal(sectionLengthText(0), '字数未定')
  assert.equal(sectionLengthText(-5), '字数未定')
  assert.equal(sectionLengthText(Number.NaN), '字数未定')
  assert.equal(sectionLengthText(1500), '约 1500 字')
  assert.equal(sectionLine(item({ target_length: null })), '1. 背景与目标（字数未定）')
})

test('标题为空白时给出占位而非空行，避免清单出现无名条目', () => {
  assert.equal(sectionLine(item({ title: '   ' })), '1. 未命名章节（约 1200 字）')
})

test('多章按后端顺序逐行输出，一行一章', () => {
  const lines = sectionLines([
    item({ seq: 1, title: '背景与目标', target_length: 1200 }),
    item({ seq: 2, title: '现状与问题', target_length: 900 }),
    item({ seq: 3, title: '方案要点', target_length: null })
  ])
  assert.deepEqual(lines, [
    '1. 背景与目标（约 1200 字）',
    '2. 现状与问题（约 900 字）',
    '3. 方案要点（字数未定）'
  ])
})

test('空清单不产生任何行，也不抛错', () => {
  assert.deepEqual(sectionLines([]), [])
})

/* ---------- 抬头文案 ---------- */

test('抬头是「将生成 N 章」；空清单明确说没有可切分的章节', () => {
  assert.equal(sectionListHeadline(1), '将生成 1 章')
  assert.equal(sectionListHeadline(8), '将生成 8 章')
  assert.equal(sectionListHeadline(0), '没有可切分的成品章节')
  assert.equal(sectionListHeadline(Number.NaN), '没有可切分的成品章节')
  assert.equal(sectionListHeadline(-2), '没有可切分的成品章节')
})

/* ---------- 过期判定：清单属于某一版方案 ---------- */

test('plan_id 与当前方案不一致即视为过期，一致才是当前清单', () => {
  assert.equal(isSectionListStale(7, 7), false)
  assert.equal(isSectionListStale(7, 8), true)
  assert.equal(isSectionListStale(8, 7), true)
})

/* ---------- 固定文案与只读边界 ---------- */

test('「返回修订方案」是唯一出口的文案，且说明清单只读', () => {
  assert.equal(RETURN_TO_REVISE_LABEL, '返回修订方案')
  // 只读说明必须点明「要改就回对话修订」，否则用户会找编辑入口
  assert.match(READONLY_NOTICE, /只读/)
  assert.match(READONLY_NOTICE, /修订/)
})

test('空清单提示把「怎么写才能切出章节」说清楚，并指向返回修订', () => {
  assert.match(EMPTY_SECTIONS_HINT, /章节/)
  assert.match(EMPTY_SECTIONS_HINT, /返回修订方案/)
})

test('章节 API 只含「只读清单 + 逐章填充」——不存在改名 / 排序 / 增删 / 重排的函数', () => {
  const text = source('../src/api/client.ts')
  // 允许的章节端点：只读清单 listPlanSections、工单 24 的引用预览 previewSectionReferences、
  // 单章正文填充 fillSection。这些**写的是章节内容 / 引用**，不改变章节目录结构。
  const names = [...text.matchAll(/export function (\w*[Ss]ection\w*)\s*\(/g)].map((m) => m[1])
  assert.deepEqual(names, ['listPlanSections', 'previewSectionReferences', 'fillSection'])
  // 只读边界：章节目录**结构**不可改——没有改名 / 排序 / 增删 / 重排章节的端点
  // （填充单章正文是写内容，不是改目录；ADR-0006 只禁止结构编辑）。
  assert.equal(/rename[\w]*[Ss]ection|reorder[\w]*[Ss]ection|resequence[\w]*[Ss]ection/i.test(text), false)
  assert.equal(/method:\s*'(?:PUT|PATCH|DELETE)'[^}]*sections/s.test(text), false)
})

/* ---------- 客户端：端点、字段透出与错误 ---------- */

test('listPlanSections 只打 GET /tasks/{id}/sections，并原样透出后端字段', async () => {
  const payload: PlanSectionListResponse = {
    plan_id: 12,
    items: [item(), item({ seq: 2, title: '实施步骤', target_length: null, status: 'completed', status_label: '已完成', hanzi_count: 812, completed_at: '2026-10-20T12:00:00+08:00' })],
    total: 2
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
    const res = await listPlanSections(42)
    assert.deepEqual(urls, ['http://127.0.0.1:8720/api/tasks/42/sections'])
    // 只读查询：不带 method（默认 GET）、不带请求体
    assert.ok(!inits[0]?.method || inits[0]?.method === 'GET')
    assert.equal(inits[0]?.body, undefined)
    assert.deepEqual(res, payload)
    assert.equal(res.items[1].status_label, '已完成')
    assert.equal(res.items[1].target_length, null)
  } finally {
    globalThis.fetch = original
  }
})

test('方案还没确认（404）时抛出带 detail 的 ApiHttpError，由卡片显式提示而不是当成空清单', async () => {
  const original = globalThis.fetch
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ detail: '任务 42 尚无结构化方案' }), {
      status: 404,
      headers: { 'Content-Type': 'application/json' }
    })) as typeof fetch
  try {
    await assert.rejects(
      () => listPlanSections(42),
      (err: unknown) => {
        assert.ok(err instanceof ApiHttpError)
        assert.equal((err as ApiHttpError).status, 404)
        assert.equal((err as ApiHttpError).detail, '任务 42 尚无结构化方案')
        return true
      }
    )
  } finally {
    globalThis.fetch = original
  }
})

test('新函数已登记在 client.ts 的 default 导出里（否则调用方拿不到）', () => {
  assert.equal(typeof client.listPlanSections, 'function')
  assert.equal(client.listPlanSections, listPlanSections)
})

/* ---------- 组件源码守卫：只读、无编辑入口 ---------- */

test('章节清单组件没有任何编辑入口：无输入框、无 contenteditable、无拖拽排序', () => {
  const text = source('../src/components/SectionListCard.vue')
  for (const forbidden of ['contenteditable', 'draggable', 'el-input', '<input', 'v-model', 'sortable']) {
    assert.equal(text.includes(forbidden), false, `章节清单组件不应包含 ${forbidden}`)
  }
  // 必须真有「返回修订方案」出口，且只读说明可见
  assert.ok(text.includes('RETURN_TO_REVISE_LABEL'), '缺少「返回修订方案」出口')
  assert.ok(text.includes('READONLY_NOTICE'), '缺少只读说明')
  assert.ok(text.includes('listPlanSections'), '清单必须读后端章节接口，不许前端自行推导')
})

test('章节清单组件不从方案正文推导章节（不碰方案分节切分）', () => {
  const text = source('../src/components/SectionListCard.vue')
  assert.equal(text.includes('splitPlanSections'), false)
  assert.equal(text.includes('planSectioned'), false)
})

test('卡片只在方案已确认时挂载（工单 8：方案未确认时该卡片不出现）', () => {
  const text = source('../src/views/CreationView.vue')
  // 挂载点必须带「已确认」条件；不能无条件渲染，否则草稿态就会出现成品目录
  const mount = /<SectionListCard[\s\S]*?\/>/.exec(text)
  assert.ok(mount, 'CreationView 里没有挂载 SectionListCard')
  assert.match(mount![0], /v-if="plan\.status === 'confirmed'"/)
  assert.match(mount![0], /:plan-id="plan\.id"/)
  // 「返回修订方案」必须接回既有修订流程，而不是新开一套
  assert.match(mount![0], /@back-to-revise="backToRevise"/)
  assert.ok(text.includes('function backToRevise'))
})

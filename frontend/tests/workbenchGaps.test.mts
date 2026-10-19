/**
 * 工作台 v1 前端规格缺口补测（纯函数，零依赖）。
 * 覆盖：HTTP 状态码判定（ApiHttpError / isApiStatus）、最近资料行的三态与命名、
 *       任务级模型选择器的选项文案。
 * 运行：`npm run test:unit`（node --test tests/）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { ApiHttpError, BackendUnavailableError, isApiStatus } from '../src/api/client.ts'
import { sourceDisplayName, sourceRowTag } from '../src/utils/analysisMeta.ts'
import { providerOptionLabel } from '../src/utils/providerMeta.ts'

/* ---------- ApiHttpError：消息格式保持不变 ---------- */

test('ApiHttpError 保留「请求失败：<code> <statusText> · <detail>」消息格式', () => {
  const err = new ApiHttpError(409, 'Conflict', '该来源尚无总结，请先执行分析')
  assert.equal(err.message, '请求失败：409 Conflict · 该来源尚无总结，请先执行分析')
  assert.equal(err.status, 409)
  assert.equal(err.detail, '该来源尚无总结，请先执行分析')
  assert.ok(err instanceof Error)
})

test('无 detail 时不留尾随分隔符；statusText 为空时也不留多余空格', () => {
  assert.equal(new ApiHttpError(500, 'Internal Server Error', '').message, '请求失败：500 Internal Server Error')
  assert.equal(new ApiHttpError(404, '', '来源 7 不存在').message, '请求失败：404 · 来源 7 不存在')
})

/* ---------- isApiStatus：不再靠字符串反解析状态码 ---------- */

test('isApiStatus 只认 ApiHttpError 的状态码', () => {
  const err = new ApiHttpError(404, 'Not Found', '来源 7 不存在')
  assert.equal(isApiStatus(err, 404), true)
  assert.equal(isApiStatus(err, 409), false)
})

test('后端未启动 / 普通错误 / 非错误值都判不出状态码（不会被文案里的数字骗到）', () => {
  assert.equal(isApiStatus(new BackendUnavailableError(), 404), false)
  assert.equal(isApiStatus(new Error('请求失败：404 已被我用旧写法拼进消息'), 404), false)
  assert.equal(isApiStatus('请求失败：404', 404), false)
  assert.equal(isApiStatus(undefined, 500), false)
  assert.equal(isApiStatus(null, 500), false)
})

/* ---------- 最近资料行：命名与三态绝不混淆 ---------- */

test('sourceDisplayName：文件名优先，URL 取主机名，坏数据退回 ref', () => {
  assert.equal(
    sourceDisplayName({ kind: 'file', ref: 'uploads/9.md', meta: { original_name: '会议纪要.md' } }),
    '会议纪要.md'
  )
  assert.equal(
    sourceDisplayName({ kind: 'url', ref: 'https://example.com/a/b', meta: { url: 'https://www.example.com/a' } }),
    'example.com'
  )
  assert.equal(sourceDisplayName({ kind: 'url', ref: 'not-a-url', meta: {} }), 'not-a-url')
  assert.equal(sourceDisplayName({ kind: 'file', ref: '', meta: {} }), '未知资料')
})

test('sourceRowTag：parsed / failed / unrecognized 三种状态标签与色调各自不同', () => {
  assert.deepEqual(sourceRowTag({ parse_status: 'parsed' }), { label: '已解析', type: 'success' })
  assert.deepEqual(sourceRowTag({ parse_status: 'failed' }), { label: '解析失败', type: 'danger' })
  assert.deepEqual(sourceRowTag({ parse_status: 'unrecognized' }), { label: '未识别', type: 'warning' })
})

test('sourceRowTag：没有解析记录时显示「未解析」，绝不冒充已解析', () => {
  assert.deepEqual(sourceRowTag(null), { label: '未解析', type: 'info' })
})

/* ---------- 任务级模型选择器的选项文案 ---------- */

test('providerOptionLabel：名称 · 模型名，全局默认配置标注「（默认）」', () => {
  assert.equal(
    providerOptionLabel({ name: 'DeepSeek 主流程', model_name: 'deepseek-flash', is_default: true }),
    'DeepSeek 主流程 · deepseek-flash（默认）'
  )
  assert.equal(
    providerOptionLabel({ name: '本地 ollama', model_name: 'qwen3:8b', is_default: false }),
    '本地 ollama · qwen3:8b'
  )
})

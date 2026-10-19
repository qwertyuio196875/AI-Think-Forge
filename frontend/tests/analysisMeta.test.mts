/**
 * TB-7 资料分析页纯函数测试。
 * 接缝（工单商定）：frontend/src/utils/analysisMeta.ts 的公开纯函数；
 * 运行方式 `node --test tests/`（Node ≥23.6 原生剥离类型，零新增依赖）。
 * 期望值全部来自规格 / 后端契约的字面量，不由被测代码重新推导。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  validateUploadFile,
  formatFileSize,
  parseStatusTag,
  headingSourceLabel,
  describeUnrecognized,
  formatLocator
} from '../src/utils/analysisMeta.ts'

/* ---------- validateUploadFile：扩展名白名单 + 50MB（与后端 UPLOAD 校验同口径） ---------- */

test('合法扩展名与大小通过校验', () => {
  assert.equal(validateUploadFile('报告.docx', 50 * 1024 * 1024 - 1), null)
  assert.equal(validateUploadFile('notes.txt', 1234), null)
  assert.equal(validateUploadFile('SPEC.MD', 1), null) // 大写扩展名同样放行
})

test('扩展名白名单外的文件被拒绝', () => {
  const pdf = validateUploadFile('思考的杠杆.pdf', 1000)
  assert.ok(pdf)
  assert.match(pdf, /\.txt \/ \.md \/ \.docx/)

  assert.ok(validateUploadFile('audio.mp3', 1000))
  assert.ok(validateUploadFile('noextension', 10)) // 无扩展名不在白名单内
})

test('恰好 50MB 与超限按字节比较（与后端 read_upload 同口径）', () => {
  assert.equal(validateUploadFile('a.txt', 50 * 1024 * 1024), null) // 等于上限不拒绝
  assert.match(validateUploadFile('a.txt', 50 * 1024 * 1024 + 1), /超过 50 MB/)
})

test('空字节文件可上传（内容由后端解析后如实判未识别）', () => {
  assert.equal(validateUploadFile('empty.md', 0), null)
})

/* ---------- formatFileSize ---------- */

test('formatFileSize 输出中文可读体积', () => {
  assert.equal(formatFileSize(0), '0 B')
  assert.equal(formatFileSize(999), '999 B')
  assert.equal(formatFileSize(1024), '1.0 KB')
  assert.equal(formatFileSize(2 * 1024 * 1024), '2.0 MB')
  assert.equal(formatFileSize(150 * 1024 * 1024), '150.0 MB')
})

/* ---------- parseStatusTag：parsed/failed/unrecognized 绝不混淆 ---------- */

test('parseStatusTag 三种状态给出不同色调与标签', () => {
  assert.deepEqual(parseStatusTag('parsed'), { label: '已解析', type: 'success' })
  assert.deepEqual(parseStatusTag('failed'), { label: '解析失败', type: 'danger' })
  assert.deepEqual(parseStatusTag('unrecognized'), { label: '未识别', type: 'warning' })
})

test('未知状态原样回退为中性标签，不冒充成功', () => {
  assert.deepEqual(parseStatusTag('weird'), { label: 'weird', type: 'info' })
})

/* ---------- headingSourceLabel ---------- */

test('heading_source 三值映射中文，未知回退原值', () => {
  assert.equal(headingSourceLabel('style'), '内置标题样式')
  assert.equal(headingSourceLabel('heuristic'), '字号/加粗启发式')
  assert.equal(headingSourceLabel('none'), '未识别到标题')
  assert.equal(headingSourceLabel('future'), 'future')
})

/* ---------- describeUnrecognized：后端三个 reason 码 ---------- */

test('no_text_layer 明示扫描件与 OCR 边界', () => {
  const text = describeUnrecognized({
    unrecognized: true,
    reason: 'no_text_layer',
    locator: { format: 'docx', images: 3 },
    needs_ocr: true
  })
  assert.match(text, /没有文本层/)
  assert.match(text, /3 处图片/)
  assert.match(text, /不支持 OCR/)
})

test('empty_document 明示内容为空', () => {
  assert.match(describeUnrecognized({ unrecognized: true, reason: 'empty_document', locator: { format: 'txt' }, needs_ocr: false }), /内容为空/)
})

test('images_not_read 明示图片内容读不到', () => {
  const text = describeUnrecognized({
    unrecognized: true,
    reason: 'images_not_read',
    locator: { format: 'docx', images: 2 },
    needs_ocr: true
  })
  assert.match(text, /图片/)
  assert.match(text, /未参与分析/)
})

test('未知 reason 回退原文，不静默吞掉', () => {
  assert.match(describeUnrecognized({ unrecognized: true, reason: 'mystery_code', locator: {}, needs_ocr: false }), /mystery_code/)
})

/* ---------- formatLocator：逐格式位置可读化 ---------- */

test('txt / docx 段落定位', () => {
  assert.equal(formatLocator({ format: 'txt', paragraph: 12 }), '第 12 段')
  assert.equal(formatLocator({ format: 'docx', paragraph: 3 }), '第 3 段')
})

test('docx 表格单元格定位', () => {
  assert.equal(formatLocator({ format: 'docx', table: 2, row: 5 }), '表格 2 · 第 5 行')
})

test('md 行与块定位', () => {
  assert.equal(formatLocator({ format: 'md', line: 8 }), '第 8 行')
  assert.equal(formatLocator({ format: 'md', block: 4 }), '第 4 块')
})

test('分块区间定位折叠起止', () => {
  assert.equal(
    formatLocator({ format: 'docx', start: { paragraph: 2 }, end: { paragraph: 9 } }),
    '第 2–9 段'
  )
  assert.equal(
    formatLocator({ format: 'docx', start: { paragraph: 4 }, end: { paragraph: 4 } }),
    '第 4 段'
  )
})

test('二次切分带 part 序号', () => {
  assert.equal(formatLocator({ format: 'txt', paragraph: 7, part: 2 }), '第 7 段 · 第 2 片')
})

test('未识别契约的图片计数', () => {
  assert.equal(formatLocator({ format: 'docx', images: 5 }), '含 5 处图片')
})

test('空 locator 返回空串（调用方据此省略位置）', () => {
  assert.equal(formatLocator({}), '')
  assert.equal(formatLocator(null), '')
})

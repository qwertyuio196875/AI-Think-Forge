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
  formatLocator,
  hostFromUrl,
  validateUrlInput
} from '../src/utils/analysisMeta.ts'

/* ---------- validateUploadFile：扩展名白名单 + 50MB（与后端 UPLOAD 校验同口径） ---------- */

test('合法扩展名与大小通过校验（TB-8 起含 PDF / PPTX）', () => {
  assert.equal(validateUploadFile('报告.docx', 50 * 1024 * 1024 - 1), null)
  assert.equal(validateUploadFile('notes.txt', 1234), null)
  assert.equal(validateUploadFile('SPEC.MD', 1), null) // 大写扩展名同样放行
  assert.equal(validateUploadFile('思考的杠杆.pdf', 2 * 1024 * 1024), null)
  assert.equal(validateUploadFile('分享提纲.PPTX', 8 * 1024 * 1024), null)
})

test('白名单外的文件被拒绝（音视频 / 表格 / 旧版 Office 均不支持）', () => {
  const xlsx = validateUploadFile('数据.xlsx', 1000)
  assert.ok(xlsx)
  assert.match(xlsx, /\.txt \/ \.md \/ \.docx \/ \.pdf \/ \.pptx/)

  assert.ok(validateUploadFile('audio.mp3', 1000))
  assert.ok(validateUploadFile('slides.ppt', 1000))
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

/* ---------- describeUnrecognized：TB-8 版式类与 TB-9 URL 原因码 ---------- */

test('no_main_text：网页抽不出正文，明示未调用模型', () => {
  const text = describeUnrecognized({
    unrecognized: true,
    reason: 'no_main_text',
    locator: { format: 'url', url: 'https://example.com/x', status: 200, content_type: 'text/html' },
    needs_ocr: false
  })
  assert.match(text, /未能从该网页提取到可分析的正文/)
  assert.match(text, /HTTP 200/)
  assert.match(text, /未调用模型/)
})

test('empty_page：页面为空与抽不出正文口径不同', () => {
  const text = describeUnrecognized({
    unrecognized: true,
    reason: 'empty_page',
    locator: { format: 'url', url: 'https://example.com/', status: 200 },
    needs_ocr: false
  })
  assert.match(text, /内容为空/)
  assert.match(text, /未调用模型/)
})

test('chart_not_read：图表按幻灯片位置明示未参与分析', () => {
  const text = describeUnrecognized({
    unrecognized: true,
    reason: 'chart_not_read',
    locator: { format: 'pptx', slide: 4, shape: 2 },
    needs_ocr: false
  })
  assert.match(text, /图表/)
  assert.match(text, /幻灯片 4 · 形状 2/)
  assert.match(text, /未参与分析/)
})

test('grouped_shapes_not_read：组合形状未逐项展开', () => {
  const text = describeUnrecognized({
    unrecognized: true,
    reason: 'grouped_shapes_not_read',
    locator: { format: 'pptx', slide: 6, shape: 3 },
    needs_ocr: false
  })
  assert.match(text, /组合形状/)
  assert.match(text, /未参与分析/)
})

test('embedded_object_not_read：嵌入对象读不到', () => {
  const text = describeUnrecognized({
    unrecognized: true,
    reason: 'embedded_object_not_read',
    locator: { format: 'pptx', slide: 1, shape: 9 },
    needs_ocr: false
  })
  assert.match(text, /嵌入对象/)
  assert.match(text, /未参与分析/)
})

test('images_not_read 带页级位置时按页说明（PDF 逐页明示）', () => {
  const text = describeUnrecognized({
    unrecognized: true,
    reason: 'images_not_read',
    locator: { format: 'pdf', page: 2, images: 1 },
    needs_ocr: true
  })
  assert.match(text, /第 2 页/)
  assert.match(text, /图片/)
  assert.match(text, /未参与分析/)
})

test('no_text_layer 无图片计数时仍说明疑似扫描件', () => {
  const text = describeUnrecognized({
    unrecognized: true,
    reason: 'no_text_layer',
    locator: { format: 'pdf', images: 0 },
    needs_ocr: true
  })
  assert.match(text, /没有文本层/)
  assert.match(text, /不支持 OCR/)
})

/* ---------- validateUrlInput：前端基本格式校验（安全拒绝由后端完成） ---------- */

test('合法 http / https 链接通过前端校验', () => {
  assert.equal(validateUrlInput('https://www.paulgraham.com/leverage.html'), null)
  assert.equal(validateUrlInput('  http://example.com  '), null) // 首尾空白可接受
})

test('非 http / https 协议被拒绝（与后端 REASON_TEXT 同口径）', () => {
  assert.match(validateUrlInput('ftp://example.com/file') ?? '', /只接受 http \/ https/)
  assert.match(validateUrlInput('javascript:alert(1)') ?? '', /只接受 http \/ https/)
  assert.match(validateUrlInput('file:///C:/Windows/win.ini') ?? '', /只接受 http \/ https/)
})

test('内嵌凭据、无法解析、空输入各有可读原因', () => {
  assert.match(validateUrlInput('https://user:pass@example.com') ?? '', /不得内嵌用户名或密码/)
  assert.match(validateUrlInput('https://') ?? '', /无法解析/) // URL 标准：解析失败
  assert.match(validateUrlInput('example.com') ?? '', /无法解析/) // 缺协议不猜测补全
  assert.match(validateUrlInput('   ') ?? '', /请输入网页地址/)
  // 注：主机名为空等更深的校验以后端 validate_url 为准（400 原样展示其可读原因）
})

test('本机 / 内网地址不在前端拦截：由后端安全校验给出权威拒绝', () => {
  // 前端只做格式校验；127.0.0.1 能通过格式，但后端会 400 拒绝并说明原因
  assert.equal(validateUrlInput('http://127.0.0.1/'), null)
  assert.equal(validateUrlInput('http://169.254.169.254/latest/meta-data/'), null)
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

/* ---------- formatLocator：TB-8 版式类（PDF / PPTX）与 TB-9 URL ---------- */

test('PDF 页 / 行定位（pypdf：{page, line} 均 1 起）', () => {
  assert.equal(formatLocator({ format: 'pdf', page: 3, line: 7 }), '第 3 页 · 第 7 行')
  assert.equal(formatLocator({ format: 'pdf', page: 3 }), '第 3 页')
})

test('PDF 分块区间：同页折叠行号，跨页折叠页码', () => {
  assert.equal(
    formatLocator({ format: 'pdf', start: { page: 2, line: 3 }, end: { page: 2, line: 9 } }),
    '第 2 页 · 第 3–9 行'
  )
  assert.equal(
    formatLocator({ format: 'pdf', start: { page: 2, line: 5 }, end: { page: 2, line: 5 } }),
    '第 2 页 · 第 5 行'
  )
  assert.equal(
    formatLocator({ format: 'pdf', start: { page: 1, line: 4 }, end: { page: 3, line: 2 } }),
    '第 1–3 页'
  )
})

test('PDF 未识别图片按页明示（{page, images}）', () => {
  assert.equal(formatLocator({ format: 'pdf', page: 4, images: 2 }), '第 4 页 · 含 2 处图片')
})

test('PPTX 标题 / 形状段落 / 表格行 / 未识别形状定位', () => {
  assert.equal(formatLocator({ format: 'pptx', slide: 5, kind: 'title' }), '幻灯片 5 · 标题')
  assert.equal(
    formatLocator({ format: 'pptx', slide: 2, shape: 3, paragraph: 4 }),
    '幻灯片 2 · 形状 3 · 第 4 段'
  )
  assert.equal(
    formatLocator({ format: 'pptx', slide: 2, table: 1, row: 3 }),
    '幻灯片 2 · 表格 1 · 第 3 行'
  )
  assert.equal(formatLocator({ format: 'pptx', slide: 7, shape: 4 }), '幻灯片 7 · 形状 4')
})

test('PPTX 分块区间折叠幻灯片号', () => {
  assert.equal(
    formatLocator({ format: 'pptx', start: { slide: 2, kind: 'title' }, end: { slide: 6, shape: 1, paragraph: 2 } }),
    '幻灯片 2–6'
  )
  assert.equal(
    formatLocator({ format: 'pptx', start: { slide: 3, kind: 'title' }, end: { slide: 3, shape: 2, paragraph: 1 } }),
    '幻灯片 3'
  )
})

test('URL 定位显示域名 + 行号，不显示超长 URL', () => {
  assert.equal(
    formatLocator({ format: 'url', url: 'https://www.paulgraham.com/leverage.html', line: 12 }),
    'paulgraham.com · 第 12 行'
  )
  assert.equal(
    formatLocator({
      format: 'url',
      start: { url: 'https://example.com/a', line: 2 },
      end: { url: 'https://example.com/a', line: 9 }
    }),
    '第 2–9 行'
  )
})

test('URL 未识别契约的 locator 只显示域名（无行号时）', () => {
  assert.equal(
    formatLocator({ format: 'url', url: 'https://example.com/x', status: 200, content_type: 'text/html' }),
    'example.com'
  )
  // 无法解析的 URL 不显示主机名，只保留可读部分
  assert.equal(formatLocator({ format: 'url', url: 'not a url', line: 3 }), '第 3 行')
})

/* ---------- hostFromUrl ---------- */

test('hostFromUrl 去 www 前缀，坏地址返回空串', () => {
  assert.equal(hostFromUrl('https://www.ex.com/x?a=1'), 'ex.com')
  assert.equal(hostFromUrl('http://127.0.0.1:8720/'), '127.0.0.1')
  assert.equal(hostFromUrl('not a url'), '')
})

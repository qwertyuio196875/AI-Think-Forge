<template>
  <section class="view" aria-label="资料分析">
    <header class="view-head">
      <div class="head-row">
        <div class="head-title">
          <h1>资料分析</h1>
          <p>单份资料的「解析 → 总结」快捷流程，默认不进入拷问；总结可直接送入主题创作</p>
        </div>
        <div class="head-actions">
          <el-tag v-if="headChip" size="small" :type="headChip.type" effect="plain" class="status-chip">
            <i class="tf-dot" :class="headChip.dot"></i>{{ headChip.label }}
          </el-tag>
          <el-tag size="small" type="info" effect="plain">总结默认 ≤500 汉字</el-tag>
          <el-button size="small" :icon="Clock" @click="goHistory">分析记录</el-button>
        </div>
      </div>
    </header>

    <div class="view-body">
      <div class="split">
        <!-- ============ 左：发起分析 ============ -->
        <div class="panel">
          <div class="panel-head">
            <h3>发起分析</h3>
            <span class="right xs muted">TXT / MD / DOCX / PDF / PPTX</span>
          </div>
          <div class="panel-body">
            <button
              type="button"
              class="drop"
              :class="{ 'is-drag': dragging, 'is-busy': uploading || fetching || analyzing }"
              :disabled="uploading || fetching || analyzing"
              aria-describedby="drop-help"
              @click="openPicker"
              @dragover.prevent="onDragOver"
              @dragleave.prevent="dragging = false"
              @drop.prevent="onDrop"
            >
              <el-icon class="ico"><Upload /></el-icon>
              <b>{{ uploading ? '正在上传…' : '拖拽文件到此处，或点击选择文件' }}</b>
              <span id="drop-help">单次一份资料 · 单文件不超过 50 MB · 类型与大小先校验再解析</span>
            </button>
            <input
              ref="fileRef"
              type="file"
              class="file-input"
              tabindex="-1"
              aria-hidden="true"
              :accept="acceptAttr"
              @change="onPick"
            />

            <div v-if="uploading" class="up-progress" aria-live="polite">
              <div class="bar"><i :style="{ width: uploadPercent + '%' }"></i></div>
              <span class="xs muted">{{ uploadName }} · {{ uploadPercent }}%{{ uploadPercent >= 100 ? '（上传完成，正在解析）' : '' }}</span>
            </div>

            <div v-if="rejectNote" class="note err" role="alert" style="margin-top: var(--sp-4)">
              <el-icon class="ico"><WarningFilled /></el-icon>
              <div class="note-body"><span>{{ rejectNote }}</span></div>
            </div>

            <!-- 当前资料：解析结果如实回显（parsed / failed / unrecognized 绝不混淆） -->
            <div v-if="current" class="src-list">
              <div class="src">
                <el-icon
                  class="ico src-ico"
                  :class="{ 'is-warn': parseUnrecognized, 'is-err': parseFailed }"
                  aria-hidden="true"
                ><Link v-if="isUrlSource" /><Document v-else /></el-icon>
                <div class="grow">
                  <b :title="fileName">{{ fileName }}</b>
                  <span>{{ sourceMetaText }}</span>
                  <span v-if="finalUrlNote" class="xs src-sub" :title="finalUrlNote">
                    跳转后地址：{{ finalUrlNote }}
                  </span>
                  <div v-if="parsedChips.length" class="chip-row">
                    <span v-for="chip in parsedChips" :key="chip" class="chip xs">{{ chip }}</span>
                  </div>
                </div>
                <el-tag size="small" :type="statusTag.type" effect="plain">{{ statusTag.label }}</el-tag>
              </div>
              <p v-if="parseFailed && current.message" class="xs muted fail-line" role="status">
                {{ isUrlSource ? '抓取失败原因' : '解析失败原因' }}：{{ current.message }}（来源已保留，不丢数据；{{ isUrlSource ? '可换一个公开可访问的链接重试' : '可重新上传其它文件' }}）
              </p>
            </div>

            <!-- TB-9：公开网页 URL 抓取（安全判定以后端为准，拒绝原因原样展示） -->
            <div class="url-field">
              <div class="url-row">
                <el-input
                  v-model="urlInput"
                  :disabled="uploading || fetching || analyzing"
                  placeholder="粘贴公开网页 URL，抓取正文后分析"
                  aria-label="公开网页 URL 地址"
                  @keydown.enter.prevent="submitUrl"
                >
                  <template #prepend>URL</template>
                </el-input>
                <el-button
                  type="primary"
                  plain
                  :loading="fetching"
                  :disabled="uploading || analyzing || !urlInput.trim()"
                  @click="submitUrl"
                >
                  抓取
                </el-button>
              </div>
              <p class="xs muted url-hint">
                {{ fetching ? '正在抓取并解析网页，请稍候…' : '仅 http / https；本机、内网与云元数据地址会被安全策略拒绝且不落库；超时 15 秒、上限 5 MB、最多 3 次重定向。' }}
              </p>
            </div>

            <div class="note info" style="margin-top: var(--sp-4)">
              <el-icon class="ico"><InfoFilled /></el-icon>
              <div class="note-body">
                <b>不会自动进入拷问</b>
                <span>资料分析默认只做总结。想把它变成创作输入，用结果区的「送入主题创作」。</span>
              </div>
            </div>

            <el-button
              type="primary"
              size="large"
              class="analyze-btn"
              :disabled="!canAnalyze"
              :loading="analyzing"
              @click="runAnalyze"
            >
              {{ analyzing ? '分析中…' : result?.summary ? '重新分析' : '开始分析' }}
            </el-button>
            <p class="xs muted hint-line" aria-live="polite">
              {{ analyzeHint }}
            </p>
            <p v-if="result?.summary && !analyzing" class="xs muted">
              重新分析会再次调用模型并另存一份总结；已有总结仍可通过「复制 / 送入主题创作」使用。
            </p>
          </div>
        </div>

        <!-- ============ 右：分析结果 ============ -->
        <div class="panel">
          <!-- 进行中 -->
          <template v-if="rightState === 'analyzing'">
            <div class="panel-head">
              <h3>正在分析</h3>
              <span class="right xs muted"><el-icon class="is-loading spin-ico"><Loading /></el-icon></span>
            </div>
            <div class="panel-body">
              <div class="src" style="border: 0; padding: 0">
                <div class="grow">
                  <b>{{ fileName }} · 共 {{ doc?.chunks ?? 0 }} 个分块</b>
                  <div class="bar indeterminate" aria-label="分析进行中"><i></i></div>
                </div>
              </div>
              <p class="xs muted hint-line" aria-live="polite">
                  逐块分析 {{ doc?.chunks ?? 0 }} 次后再综合 1 次，长文需要一些时间；总结走 turbo 档（该档缺失时回退默认配置并如实标注）。完成后的总结会保存，可在分析记录中留痕。
              </p>
            </div>
          </template>

          <!-- 模型 / 请求失败（已存数据保留，可安全重试） -->
          <template v-else-if="rightState === 'analyze-error'">
            <div class="panel-head">
              <h3>分析未完成</h3>
              <span class="right"><el-tag size="small" type="danger" effect="plain">可重试</el-tag></span>
            </div>
            <div class="panel-body">
              <div class="note err" role="alert">
                <el-icon class="ico"><WarningFilled /></el-icon>
                <div class="note-body">
                  <b>{{ analyzeError }}</b>
                  <span>已入库的来源、文档与分块保留不受影响；确认模型配置可用后直接重试即可。</span>
                  <div>
                    <el-button size="small" :disabled="!canAnalyze" @click="runAnalyze">重试分析</el-button>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <!-- 总结 -->
          <template v-else-if="rightState === 'summary' && result?.summary">
            <div class="panel-head">
              <h3>总结</h3>
              <el-tag size="small" :type="result.summary.truncated ? 'warning' : 'success'" effect="plain">
                {{ result.summary.truncated ? '超上限，按句读截断' : '500 汉字以内' }}
              </el-tag>
              <span class="right xs muted">来源：{{ fileName }} · {{ formatDateTime(result.source.created_at) }}</span>
            </div>
            <div class="panel-body">
              <div class="stat-row">
                <div class="stat"><b>{{ result.summary.hanzi_count }} 字</b>总结长度（上限 500）</div>
                <div class="stat"><b>{{ result.summary.chunk_count }}</b>分块已覆盖</div>
                <div class="stat"><b>{{ result.summary.citations.length }} 处</b>引用来源</div>
                <div v-if="result.unrecognized_parts.length" class="stat"><b>{{ result.unrecognized_parts.length }} 处</b>未识别内容</div>
              </div>

              <div class="sum-text" aria-label="总结正文">{{ result.summary.text }}</div>

              <div class="prov-row" aria-label="实际所用档位">
                <span class="cap">档位 <b>{{ result.summary.provider_kind || '—' }}</b></span>
                <span class="cap">实际配置 <b>{{ result.summary.provider_used || '—' }}</b></span>
                <span class="cap">模型 <b>{{ result.summary.model_used || '—' }}</b></span>
                <el-tag v-if="result.summary.provider_fallback" size="small" type="warning" effect="plain">
                  请求档位缺失，已回退默认配置
                </el-tag>
              </div>
              <p v-if="result.summary.provider_note" class="xs muted prov-note">{{ result.summary.provider_note }}</p>

              <section class="cites" aria-label="引用来源">
                <h4>引用来源 · {{ result.summary.citations.length }} 处</h4>
                <ol class="cite-scroll" tabindex="0">
                  <li v-for="c in result.summary.citations" :key="c.chunk_seq" class="cite">
                    <span class="cite-no">块 {{ c.chunk_seq }}</span>
                    <span class="cite-loc">{{ formatLocator(c.locator) || '位置未标注' }}</span>
                    <p class="cite-ex">{{ c.excerpt }}</p>
                  </li>
                </ol>
              </section>

              <div v-if="result.unrecognized_parts.length" class="note warn" style="margin-top: var(--sp-4)">
                <el-icon class="ico"><Warning /></el-icon>
                <div class="note-body">
                  <b>未识别内容（已明示，不伪装成完整分析）</b>
                  <span v-for="(part, pi) in result.unrecognized_parts" :key="pi">
                    {{ describeUnrecognized(part) }}（位置：{{ formatLocator(part.locator) || '未标注' }}）
                  </span>
                </div>
              </div>
            </div>
            <div class="result-actions">
              <el-button size="small" :icon="CopyDocument" @click="copySummary">复制总结</el-button>
              <el-button size="small" type="primary" :icon="Promotion" :loading="sending" @click="doSend">
                送入主题创作
              </el-button>
            </div>
          </template>

          <!-- 未识别：一级契约展示，绝不显示为成功 -->
          <template v-else-if="rightState === 'unrecognized' && primaryUnrec">
            <div class="panel-head">
              <h3>分析结果</h3>
              <el-tag size="small" type="warning" effect="plain">未识别 · 未生成总结</el-tag>
              <span class="right xs muted">{{ fileName }}</span>
            </div>
            <div class="panel-body">
              <div class="note warn" role="status">
                <el-icon class="ico"><Warning /></el-icon>
                <div class="note-body">
                  <b>{{ describeUnrecognized(primaryUnrec) }}</b>
                  <span v-if="formatLocator(primaryUnrec.locator)">位置：{{ formatLocator(primaryUnrec.locator) }}</span>
                  <span v-if="current?.message">{{ current.message }}</span>
                  <span>{{ isUrlSource ? '可换一个公开可访问、含正文的页面链接重试。' : '该结论已在任务历史中留痕；如为文本型资料，可检查文件内容或编码后重新上传。' }}</span>
                </div>
              </div>
              <template v-if="pendingParts.length">
                <div v-for="(part, pi) in pendingParts" :key="pi" class="note warn" style="margin-top: var(--sp-3)">
                  <el-icon class="ico"><Warning /></el-icon>
                  <div class="note-body">
                    <span>{{ describeUnrecognized(part) }}（位置：{{ formatLocator(part.locator) || '未标注' }}）</span>
                  </div>
                </div>
              </template>
            </div>
          </template>

          <!-- 解析 / 抓取失败：明确失败态 -->
          <template v-else-if="rightState === 'parse-failed'">
            <div class="panel-head">
              <h3>分析结果</h3>
              <el-tag size="small" type="danger" effect="plain">{{ isUrlSource ? '抓取失败 · 未生成总结' : '解析失败 · 未生成总结' }}</el-tag>
              <span class="right xs muted">{{ fileName }}</span>
            </div>
            <div class="panel-body">
              <div class="note err" role="alert">
                <el-icon class="ico"><WarningFilled /></el-icon>
                <div class="note-body">
                  <b>{{ isUrlSource ? `网页抓取未成功：${sourceHost || fileName}` : `无法解析「${fileName}」` }}</b>
                  <span>{{ doc?.parse_message || current?.message || '后端未给出具体原因' }}</span>
                  <span>{{ isUrlSource ? '来源已保留，不丢已存数据；本系统不绕过登录与访问控制。确认链接公开可访问后可重试，或换其它链接。' : '来源与文件已保留，不丢已存数据；无法对解析失败的资料做分析。可检查文件是否完整、是否另存为标准格式后重新上传。' }}</span>
                </div>
              </div>
            </div>
          </template>

          <!-- 已上传待分析 -->
          <template v-else-if="rightState === 'ready-to-analyze'">
            <div class="panel-head">
              <h3>总结结果</h3>
              <span class="right xs muted">主题 / 核心观点 / 关键内容 / 重要数据 / 结论</span>
            </div>
            <div class="panel-body">
              <div class="empty">
                <el-icon class="ico-lg"><Link v-if="isUrlSource" /><Document v-else /></el-icon>
                <b>「{{ fileName }}」已解析（{{ doc?.chunks ?? 0 }} 个分块）</b>
                <p>点左侧「开始分析」，逐块分析后综合为 500 汉字以内的总结；总结可一键送入主题创作继续拷问。</p>
              </div>
              <div v-if="pendingParts.length" class="note warn" style="margin-top: var(--sp-4)">
                <el-icon class="ico"><Warning /></el-icon>
                <div class="note-body">
                  <b>解析中发现未识别内容（分析将不覆盖这些部分）</b>
                  <span v-for="(part, pi) in pendingParts" :key="pi">
                    {{ describeUnrecognized(part) }}（位置：{{ formatLocator(part.locator) || '未标注' }}）
                  </span>
                </div>
              </div>
            </div>
          </template>

          <!-- 空态 -->
          <template v-else>
            <div class="panel-head">
              <h3>总结结果</h3>
              <span class="right xs muted">主题 / 核心观点 / 关键内容 / 重要数据 / 结论</span>
            </div>
            <div class="panel-body">
              <div class="empty">
                <el-icon class="ico-lg"><Document /></el-icon>
                <b>暂无分析结果</b>
                <p>上传 TXT / MD / DOCX / PDF / PPTX 文件，或粘贴公开网页 URL，解析后即可总结；总结可一键送入主题创作继续拷问。</p>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Clock,
  CopyDocument,
  Document,
  InfoFilled,
  Link,
  Loading,
  Promotion,
  Upload,
  Warning,
  WarningFilled
} from '@element-plus/icons-vue'
import {
  analyzeSource,
  BackendUnavailableError,
  createAnalysisUrlSource,
  sendToCreation,
  uploadAnalysisSource,
  type AnalysisResultResponse,
  type AnalysisSourceResponse,
  type UnrecognizedContent
} from '../api/client'
import {
  ALLOWED_SUFFIXES,
  describeUnrecognized,
  formatFileSize,
  formatLocator,
  headingSourceLabel,
  hostFromUrl,
  parseStatusTag,
  validateUploadFile,
  validateUrlInput
} from '../utils/analysisMeta'
import { formatDateTime } from '../utils/taskMeta'

type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

const router = useRouter()

const fileRef = ref<HTMLInputElement | null>(null)
const dragging = ref(false)

const uploading = ref(false)
const uploadPercent = ref(0)
const uploadName = ref('')
const rejectNote = ref('')

const urlInput = ref('')
const fetching = ref(false)

const current = ref<AnalysisSourceResponse | null>(null)

const analyzing = ref(false)
const analyzeError = ref('')
const result = ref<AnalysisResultResponse | null>(null)

const sending = ref(false)

/* ---------- 派生状态 ---------- */

const doc = computed(() => current.value?.document ?? null)

const isUrlSource = computed(() => current.value?.source.kind === 'url')

const sourceHost = computed(() => {
  const c = current.value
  if (!c || c.source.kind !== 'url') return ''
  const meta = c.source.meta ?? {}
  return hostFromUrl(typeof meta.url === 'string' ? meta.url : c.source.ref)
})

const fileName = computed(() => {
  const meta = current.value?.source.meta ?? {}
  const original = typeof meta.original_name === 'string' ? meta.original_name : ''
  return original || current.value?.source.ref || uploadName.value || '未知资料'
})

/** 重定向后的最终地址（与原始地址不同时才展示，供引用回溯核对）。 */
const finalUrlNote = computed(() => {
  const meta = current.value?.source.meta
  if (!current.value || current.value.source.kind !== 'url' || !meta) return ''
  const original = typeof meta.url === 'string' ? meta.url : ''
  const final = typeof meta.final_url === 'string' ? meta.final_url : ''
  return final && final !== original ? final : ''
})

const parseFailed = computed(() => doc.value?.parse_status === 'failed')
const parseUnrecognized = computed(() => doc.value?.parse_status === 'unrecognized')

const primaryUnrec = computed<UnrecognizedContent | null>(
  () => result.value?.unrecognized ?? current.value?.unrecognized ?? null
)

const pendingParts = computed<UnrecognizedContent[]>(
  () => result.value?.unrecognized_parts ?? current.value?.unrecognized_parts ?? []
)

const summary = computed(() => result.value?.summary ?? null)

const statusTag = computed(() => parseStatusTag(doc.value?.parse_status ?? ''))

const canAnalyze = computed(
  () => !!doc.value && doc.value.parse_status === 'parsed' && !uploading.value && !fetching.value && !analyzing.value
)

type RightState =
  | 'analyzing'
  | 'analyze-error'
  | 'summary'
  | 'unrecognized'
  | 'parse-failed'
  | 'ready-to-analyze'
  | 'empty'

const rightState = computed<RightState>(() => {
  if (analyzing.value) return 'analyzing'
  if (analyzeError.value) return 'analyze-error'
  if (summary.value) return 'summary'
  if (primaryUnrec.value) return 'unrecognized'
  if (parseFailed.value) return 'parse-failed'
  if (current.value) return 'ready-to-analyze'
  return 'empty'
})

const headChip = computed<{ label: string; type: TagType; dot: string } | null>(() => {
  if (uploading.value) return { label: '上传中', type: 'primary', dot: 'tf-dot--run' }
  if (fetching.value) return { label: '抓取中', type: 'primary', dot: 'tf-dot--run' }
  if (analyzing.value) return { label: '分析中', type: 'primary', dot: 'tf-dot--run' }
  if (analyzeError.value) return { label: '分析未完成', type: 'danger', dot: 'tf-dot--err' }
  if (summary.value) return { label: '已生成总结', type: 'success', dot: 'tf-dot--ok' }
  if (primaryUnrec.value || parseUnrecognized.value)
    return { label: '未识别', type: 'warning', dot: 'tf-dot--warn' }
  if (parseFailed.value) return { label: '解析失败', type: 'danger', dot: 'tf-dot--err' }
  if (canAnalyze.value) return { label: '已解析 · 可开始分析', type: 'info', dot: '' }
  return null
})

const acceptAttr = computed(() => ALLOWED_SUFFIXES.join(','))

const sourceMetaText = computed(() => {
  const c = current.value
  if (!c) return ''
  const time = formatDateTime(c.source.created_at)
  if (c.source.kind === 'url') {
    const host = hostFromUrl(typeof c.source.meta.url === 'string' ? c.source.meta.url : c.source.ref)
    const redirects = typeof c.source.meta.redirects === 'number' ? c.source.meta.redirects : 0
    const parts = [
      host ? `网页 · ${host}` : '网页来源',
      redirects > 0 ? `经 ${redirects} 次跳转` : '',
      `抓取于 ${time}`
    ]
    return parts.filter(Boolean).join(' · ')
  }
  const size = typeof c.source.meta.size === 'number' ? formatFileSize(c.source.meta.size) : ''
  return [size && `大小 ${size}`, `上传于 ${time}`].filter(Boolean).join(' · ')
})

/** 版式类解析器值得回显（用户会关心 PDF/PPTX 是谁读的）；文本类不堆技术细节。 */
const LAYOUT_PARSERS = new Set(['pypdf', 'python-pptx'])

const parsedChips = computed(() => {
  const d = doc.value
  if (!d || d.parse_status !== 'parsed') return []
  const chips: string[] = []
  if (d.parser && LAYOUT_PARSERS.has(d.parser)) chips.push(`解析器 ${d.parser}`)
  if (!isUrlSource.value && d.encoding) chips.push(`编码 ${d.encoding}`)
  chips.push(`标题来源：${headingSourceLabel(d.heading_source)}`)
  if (d.headings > 0) chips.push(`${d.headings} 个标题`)
  if (d.images > 0) chips.push(`${d.images} 处图片（不参与文本分析）`)
  return chips
})

const analyzeHint = computed(() => {
  if (uploading.value) return '正在上传并解析文件…'
  if (fetching.value) return '正在抓取并解析网页…'
  if (analyzing.value) return '正在逐块分析并综合，请稍候…'
  if (!current.value) return '上传文件（TXT / MD / DOCX / PDF / PPTX）或粘贴公开网页 URL 后即可开始分析。'
  if (parseFailed.value)
    return isUrlSource.value
      ? '抓取失败的资料无法分析；来源已保留，可换一个公开可访问的链接重试。'
      : '解析失败的资料无法分析；来源与文件已保留，可重新上传其它文件。'
  if (parseUnrecognized.value) return '未识别到可分析的文本，未调用模型；换一份含可分析正文的资料再试。'
  if (result.value?.summary) return '本份总结已保存；可复制，或一键送入主题创作。'
  return '分析 = 分块 → 逐块分析 → 综合（分析管线，不是 RAG）；完成后总结自动保存。'
})

/* ---------- 上传 ---------- */

function openPicker(): void {
  if (uploading.value || fetching.value || analyzing.value) return
  fileRef.value?.click()
}

function onPick(event: Event): void {
  const input = event.target as HTMLInputElement
  if (input.files?.length) void handleFiles(input.files)
  input.value = ''
}

function onDragOver(): void {
  if (!uploading.value && !fetching.value && !analyzing.value) dragging.value = true
}

function onDrop(event: DragEvent): void {
  dragging.value = false
  if (event.dataTransfer?.files?.length) void handleFiles(event.dataTransfer.files)
}

async function handleFiles(files: FileList | File[]): Promise<void> {
  const list = Array.from(files)
  if (!list.length || uploading.value || fetching.value || analyzing.value) return
  rejectNote.value = ''

  const file = list[0]
  if (list.length > 1) {
    ElMessage.info(`单次分析一份资料，本次处理「${file.name}」`)
  }

  const invalid = validateUploadFile(file.name, file.size)
  if (invalid) {
    rejectNote.value = invalid
    return
  }

  uploading.value = true
  uploadPercent.value = 0
  uploadName.value = file.name
  try {
    const res = await uploadAnalysisSource(file, (percent) => {
      uploadPercent.value = percent
    })
    current.value = res
    result.value = null
    analyzeError.value = ''
    rejectNote.value = ''
    if (res.document.parse_status === 'parsed') {
      ElMessage.success(`已解析「${file.name}」：${res.document.chunks} 个分块，可开始分析`)
    } else if (res.document.parse_status === 'failed') {
      ElMessage.warning('文件已保留，但解析失败；原因见右侧提示')
    } else {
      ElMessage.warning('未识别到可分析的文本；详情见右侧提示')
    }
  } catch (err) {
    rejectNote.value = describeUploadError(err)
  } finally {
    uploading.value = false
    uploadPercent.value = 0
  }
}

/* ---------- URL 抓取（TB-9） ---------- */

async function submitUrl(): Promise<void> {
  if (uploading.value || fetching.value || analyzing.value) return
  rejectNote.value = ''

  const value = urlInput.value.trim()
  const invalid = validateUrlInput(value)
  if (invalid) {
    rejectNote.value = invalid
    return
  }

  fetching.value = true
  try {
    const res = await createAnalysisUrlSource(value)
    current.value = res
    result.value = null
    analyzeError.value = ''
    rejectNote.value = ''
    urlInput.value = ''
    if (res.document.parse_status === 'parsed') {
      ElMessage.success(`已抓取网页：${res.document.chunks} 个分块，可开始分析`)
    } else if (res.document.parse_status === 'failed') {
      ElMessage.warning('来源已保留，但抓取未成功；原因见右侧提示')
    } else {
      ElMessage.warning('该网页未提取到可分析的正文；详情见右侧提示')
    }
  } catch (err) {
    rejectNote.value = describeFetchError(err)
  } finally {
    fetching.value = false
  }
}

/* ---------- 分析 ---------- */

async function runAnalyze(): Promise<void> {
  const c = current.value
  if (!c || !canAnalyze.value) return
  analyzing.value = true
  analyzeError.value = ''
  try {
    const res = await analyzeSource(c.source.id)
    result.value = res
    if (res.summary) {
      ElMessage.success(`分析完成：总结 ${res.summary.hanzi_count} 汉字`)
    } else if (res.unrecognized) {
      ElMessage.warning('该资料未识别到可分析的文本，未调用模型')
    } else {
      analyzeError.value = res.message || '分析没有返回可用结果，可重试'
    }
  } catch (err) {
    analyzeError.value = describeAnalyzeError(err)
  } finally {
    analyzing.value = false
  }
}

/* ---------- 总结操作 ---------- */

async function copySummary(): Promise<void> {
  const text = summary.value?.text
  if (!text) return
  let ok = false
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      ok = true
    }
  } catch {
    ok = false
  }
  if (!ok) ok = legacyCopy(text)
  if (ok) {
    ElMessage.success(`总结已复制（${summary.value?.hanzi_count ?? 0} 汉字）`)
  } else {
    ElMessage.error('复制失败，请手动选中总结文本复制')
  }
}

function legacyCopy(text: string): boolean {
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  }
  area.remove()
  return ok
}

async function doSend(): Promise<void> {
  const c = current.value
  const s = summary.value
  if (!c || !s || sending.value) return
  sending.value = true
  try {
    const res = await sendToCreation(c.source.id)
    ElMessage.success(
      `已送入主题创作：「${res.task.title || '未命名任务'}」已创建，总结预填为已知信息（未调用模型，首轮问题待你发起时产生）`
    )
    router.push(`/creation?task=${res.task.id}`)
  } catch (err) {
    ElMessage.error(describeSendError(err))
  } finally {
    sending.value = false
  }
}

function goHistory(): void {
  router.push('/history')
}

/* ---------- 错误文案 ---------- */

/** 从「请求失败：<code> · <detail>」里取出后端可读 detail。 */
function extractDetail(msg: string): string {
  if (!msg.startsWith('请求失败')) return msg
  const idx = msg.indexOf(' · ')
  return idx > 0 ? msg.slice(idx + 3) : msg
}

function describeUploadError(err: unknown): string {
  if (err instanceof BackendUnavailableError) return '后端未启动，上传失败。请双击「启动.bat」拉起服务后重试。'
  const detail = extractDetail((err as Error).message || '')
  return detail || '上传失败，请重试；若多次失败请检查后端是否在运行'
}

/** URL 提交错误：400 安全拒绝原样展示后端可读原因（此时未抓取、未落库）。 */
function describeFetchError(err: unknown): string {
  if (err instanceof BackendUnavailableError) return '后端未启动，无法抓取。请双击「启动.bat」拉起服务后重试。'
  const msg = (err as Error).message || ''
  const detail = extractDetail(msg)
  if (msg.includes('400')) return `${detail || '该链接未通过安全校验'}（未发起抓取，未保存任何数据）`
  if (msg.includes('422')) return '链接不能为空，且长度不能超过 2048 字符'
  return detail || '抓取请求失败，请重试'
}

function describeAnalyzeError(err: unknown): string {
  if (err instanceof BackendUnavailableError) return '后端未启动，无法发起分析'
  const msg = (err as Error).message || ''
  const detail = extractDetail(msg)
  if (msg.includes('502')) return detail || '模型调用失败，总结未生成'
  if (msg.includes('409')) return detail || '该资料当前不可分析'
  if (msg.includes('404')) return '该资料不存在或已被清理，请重新上传'
  return detail || '分析请求失败，请重试'
}

function describeSendError(err: unknown): string {
  if (err instanceof BackendUnavailableError) return '后端未启动，送入失败'
  const msg = (err as Error).message || ''
  const detail = extractDetail(msg)
  if (msg.includes('409')) return detail || '该来源尚无总结，无法送入主题创作；请先完成分析'
  if (msg.includes('404')) return '该资料不存在或已被清理，请重新上传'
  return detail ? `送入失败：${detail}` : '送入主题创作失败，请重试'
}
</script>

<style scoped>
/* 双栏布局（窄屏单列） */
.split {
  display: grid;
  grid-template-columns: minmax(340px, 440px) minmax(0, 1fr);
  gap: var(--sp-6);
  align-content: start;
  width: 100%;
  max-width: 1180px;
  margin: 0 auto;
}
.panel + .panel {
  min-height: 0;
}

/* 页眉状态 */
.head-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.status-chip .tf-dot {
  margin-right: 5px;
}

/* 拖放区（button 语义，键盘可触发文件选择） */
.drop {
  border: 1px dashed var(--line-3);
  border-radius: var(--r-md);
  padding: var(--sp-6) var(--sp-4);
  text-align: center;
  background: var(--bg-sunken);
  color: var(--text-2);
  width: 100%;
  cursor: pointer;
  font: inherit;
}
.drop:hover:not(:disabled),
.drop.is-drag {
  border-color: var(--brand-200);
  background: var(--brand-50);
  color: var(--brand-700);
}
.drop:disabled {
  cursor: default;
  opacity: 0.65;
}
.drop > .ico {
  font-size: 22px;
  margin-bottom: var(--sp-2);
}
.drop b {
  display: block;
  font-size: var(--fs-sm);
}
.drop span {
  display: block;
  font-size: var(--fs-xs);
  color: var(--text-3);
  margin-top: 2px;
}
.file-input {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}

/* 上传进度 */
.up-progress {
  margin-top: var(--sp-3);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.bar {
  height: 4px;
  border-radius: var(--r-pill);
  background: var(--line-1);
  overflow: hidden;
}
.bar > i {
  display: block;
  height: 100%;
  border-radius: var(--r-pill);
  background: var(--brand-500);
  width: 0;
  transition: width 0.3s ease;
}
.bar.indeterminate {
  position: relative;
  margin-top: var(--sp-2);
}
.bar.indeterminate > i {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 40%;
  transition: none;
  animation: ana-slide 1.2s ease-in-out infinite;
}
@keyframes ana-slide {
  0% {
    left: -40%;
  }
  100% {
    left: 100%;
  }
}
@media (prefers-reduced-motion: reduce) {
  .bar.indeterminate > i {
    animation: none;
    left: 30%;
  }
}

/* 资料行 */
.src-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  margin-top: var(--sp-4);
}
.src {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  border: 1px solid var(--line-1);
  border-radius: var(--r-sm);
  padding: var(--sp-2) var(--sp-3);
}
.src .grow {
  flex: 1;
  min-width: 0;
}
.src b {
  display: block;
  font-size: var(--fs-sm);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.src span {
  display: block;
  font-size: var(--fs-xs);
  color: var(--text-3);
}
.src-ico {
  color: var(--text-4);
  flex: none;
}
.src-ico.is-warn {
  color: var(--warn-fg);
}
.src-ico.is-err {
  color: var(--err-fg);
}
.chip-row {
  display: flex;
  gap: var(--sp-2);
  flex-wrap: wrap;
  margin-top: var(--sp-2);
}
.chip {
  display: inline-flex;
  align-items: center;
  border-radius: var(--r-xs);
  background: var(--bg-sunken);
  color: var(--text-2);
  padding: 1px 6px;
  line-height: 1.5;
  width: fit-content;
}
.fail-line {
  margin: 0;
  line-height: 1.6;
}

/* URL 抓取输入（TB-9）：与拖放区共用「单份资料」的提交流程 */
.url-field {
  margin-top: var(--sp-4);
}
.url-row {
  display: flex;
  gap: var(--sp-2);
  align-items: stretch;
}
.url-row .el-input {
  flex: 1;
  min-width: 0;
}
.url-hint {
  margin: var(--sp-2) 0 0;
  line-height: 1.6;
}
.src-sub {
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 分析按钮 */
.analyze-btn {
  width: 100%;
  justify-content: center;
  margin-top: var(--sp-4);
}
.hint-line {
  margin: var(--sp-2) 0 0;
  line-height: 1.6;
}

/* 结果区 */
.spin-ico {
  color: var(--brand-500);
  vertical-align: -2px;
}
.stat-row {
  display: flex;
  gap: var(--sp-5);
  flex-wrap: wrap;
  padding-bottom: var(--sp-4);
  margin-bottom: var(--sp-4);
  border-bottom: 1px solid var(--line-1);
}
.stat {
  font-size: var(--fs-xs);
  color: var(--text-3);
}
.stat b {
  display: block;
  font-size: var(--fs-lg);
  font-weight: 600;
  color: var(--text-1);
}
.sum-text {
  font-size: var(--fs-md);
  line-height: 1.85;
  color: var(--text-1);
  white-space: pre-wrap;
  word-break: break-word;
}
.prov-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  margin-top: var(--sp-4);
}
.prov-note {
  margin: var(--sp-2) 0 0;
  color: var(--warn-fg);
}

/* 引用来源 */
.cites {
  margin-top: var(--sp-5);
  border-top: 1px solid var(--line-1);
  padding-top: var(--sp-4);
}
.cites h4 {
  margin: 0 0 var(--sp-3);
  font-size: var(--fs-xs);
  color: var(--text-3);
  font-weight: 600;
  letter-spacing: 0.5px;
}
.cite-scroll {
  list-style: none;
  margin: 0;
  padding: 0 var(--sp-3) 0 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  max-height: 220px;
  overflow-y: auto;
}
.cite-scroll:focus-visible {
  outline: 2px solid var(--brand-500);
  outline-offset: 2px;
  border-radius: var(--r-xs);
}
.cite {
  border-left: 2px solid var(--brand-100);
  padding-left: var(--sp-3);
  min-width: 0;
}
.cite-no {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--brand-600);
  background: var(--brand-50);
  border-radius: var(--r-xs);
  padding: 1px 5px;
  margin-right: var(--sp-2);
  white-space: nowrap;
}
.cite-loc {
  font-size: var(--fs-xs);
  color: var(--text-3);
}
.cite-ex {
  margin: 2px 0 0;
  font-size: var(--fs-sm);
  color: var(--text-2);
  line-height: 1.6;
  overflow-wrap: anywhere;
}

/* 结果操作条 */
.result-actions {
  display: flex;
  gap: var(--sp-2);
  flex-wrap: wrap;
  padding: var(--sp-4);
  border-top: 1px solid var(--line-1);
}
.result-actions .el-button + .el-button {
  margin-left: 0;
}
.result-actions .el-button:nth-child(2) {
  margin-left: auto;
}

@media (max-width: 1100px) {
  .split {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--sp-5);
  }
}
@media (max-width: 640px) {
  /* 窄屏优先保证标题不折行：右侧次要提示隐藏（信息在正文与提示行仍有） */
  .panel-head .right {
    display: none;
  }
}
</style>

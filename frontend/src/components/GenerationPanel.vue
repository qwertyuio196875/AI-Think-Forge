<template>
  <div class="gpanel card" :class="{ 'is-locked': locked }">
    <div class="card-head">
      <h3>生成面板</h3>
      <span class="sub">选格式 · 选模板 / 主题 · 拿产物</span>
      <span class="right">
        <el-tag size="small" :type="locked ? 'warning' : 'success'" effect="plain">
          <el-icon class="tag-ico"><Lock v-if="locked" /><Select v-else /></el-icon>
          {{ locked ? '未解锁 · 方案还没确认' : '已解锁 · 可生成 Word / HTML / PPT' }}
        </el-tag>
      </span>
    </div>

    <!-- 锁定态：只说明闸门，不给可用假象 -->
    <div v-if="locked" class="gp-lock">
      <el-icon class="ico"><Lock /></el-icon>
      <div>
        <b>确认方案后才能生成</b>
        <p>{{ lockReason || '方案确认是进入生成阶段的唯一闸门；未经确认的推测不会写进任何文件。' }}</p>
      </div>
    </div>

    <!-- 解锁态：可操作 -->
    <div v-else class="card-body gp-live">
      <!-- 格式 -->
      <div class="gfield">
        <label>成品格式</label>
        <div class="fmt-grid" role="radiogroup" aria-label="成品格式">
          <label class="fmt" :class="{ sel: format === opt.format }" v-for="opt in formatOptions" :key="opt.format">
            <input v-model="format" type="radio" name="gpfmt" :value="opt.format" />
            <span><b>{{ opt.title }}</b><span class="d">{{ opt.desc }}</span></span>
          </label>
        </div>
      </div>

      <!-- 模板 / 主题：Word 走模板；html 与 pptx（截图版 PPT）都按主题（deck 同源） -->
      <div v-if="format === 'docx'" class="gfield">
        <label>Word 模板 · 本任务临时选择</label>
        <el-select v-model="templateSel" class="tpl-select" placeholder="跟随全局默认模板">
          <el-option label="跟随全局默认模板" :value="TEMPLATE_DEFAULT" />
          <el-option
            v-for="t in docxTemplates"
            :key="t.name"
            :label="t.name + tplSuffix(t)"
            :value="t.name"
            :disabled="!t.usable"
          />
        </el-select>
        <p class="hint">
          临时选择只影响<strong>这一次生成</strong>，记在该成品的「实际所用模板」里，<strong>不改变设置页的全局默认</strong>。
          解析顺序：临时覆盖 &gt; 全局默认 &gt; 内置最小默认。当前全局默认：<b>{{ globalDefaultName || '无（将用内置最小默认模板）' }}</b>。
        </p>
      </div>

      <!-- 主题：html 与 pptx（截图版 PPT）同源，都按主题选（清单来自 GET /api/deck-themes，色板不硬编码；空值 = 跟随全局默认） -->
      <div v-else class="gfield">
        <label>演示主题 · 本任务临时选择</label>
        <div class="theme-grid" role="radiogroup" aria-label="演示主题">
          <label class="theme-opt is-follow" :class="{ sel: theme === '' }">
            <input v-model="theme" type="radio" name="gptheme" value="" />
            <span>
              <b>跟随全局默认主题</b>
              <span class="td">{{ followThemeText }}</span>
              <span class="theme-chips is-follow-chips">
                <template v-if="defaultThemeInfo">
                  <i :style="{ background: defaultThemeInfo.palette.bg }"></i>
                  <i :style="{ background: defaultThemeInfo.palette.fg }"></i>
                  <i :style="{ background: defaultThemeInfo.palette.accent }"></i>
                  <i :style="{ background: defaultThemeInfo.palette.line }"></i>
                </template>
                <template v-else>
                  <i class="void"></i><i class="void"></i><i class="void"></i><i class="void"></i>
                </template>
              </span>
              <span class="th-src">不指定主题 · 由后端按全局默认生成</span>
            </span>
          </label>
          <template v-if="themesLoading">
            <div class="xs muted theme-loading">正在读取主题族…</div>
          </template>
          <label
            v-for="th in themes"
            :key="th.id"
            class="theme-opt"
            :class="{ sel: theme === th.id }"
          >
            <input v-model="theme" type="radio" name="gptheme" :value="th.id" />
            <span>
              <b>{{ th.name }}</b>
              <span class="td th-fonts">{{ th.fonts.join(' · ') || '—' }}</span>
              <span class="theme-chips">
                <i :style="{ background: th.palette.bg }"></i>
                <i :style="{ background: th.palette.fg }"></i>
                <i :style="{ background: th.palette.accent }"></i>
                <i :style="{ background: th.palette.line }"></i>
              </span>
              <span class="th-src">{{ th.derived_from }}</span>
              <span v-if="th.network_resources.length" class="th-net">含网络资源：{{ th.network_resources.join('、') }}</span>
              <span v-else class="th-net ok">无网络资源 · 离线可开</span>
            </span>
          </label>
        </div>
        <div v-if="!themesLoading && themes.length === 0" class="note warn" style="margin-top: var(--sp-3)">
          <el-icon class="ico"><WarningFilled /></el-icon>
          <div class="note-body"><span>读不到主题族清单；仍可生成，未选择具体主题时由后端按全局默认主题产出。</span></div>
        </div>
        <p class="hint">
          主题取自 OpenDesign 主题族适配后的本地资产（MIT 族，见署名）；中文走系统字体回退、不内联 CJK。
          <strong>未选择具体主题时</strong>用设置页的「全局默认主题」；选了具体主题<strong>只覆盖本次生成</strong>，不改变全局默认。
          未知主题后端返回 400，不静默退回默认。
        </p>
      </div>

      <!-- 生成动作 -->
      <div class="gp-actions">
        <el-button type="primary" size="large" :loading="generating" :icon="Box" @click="runGenerate()">
          {{ generating ? '正在生成…' : generateButtonText }}
        </el-button>
        <span class="xs muted mono">产物落 data/deliverables/{{ taskId }}/</span>
      </div>
      <div v-if="generating" class="gp-bar indeterminate" aria-label="生成中"><i></i></div>

      <!-- 错误态 -->
      <div v-if="genError" class="note err" role="alert">
        <el-icon class="ico"><WarningFilled /></el-icon>
        <div class="note-body">
          <b>{{ genErrorTitle }}</b>
          <span>{{ genError }}</span>
          <div v-if="canRetryBuiltin" class="retry-row">
            <el-button size="small" :disabled="generating" @click="retryBuiltin">改用内置默认模板重试</el-button>
          </div>
        </div>
      </div>

      <!-- 成品卡 -->
      <div class="art-wrap">
        <h4>成品记录<template v-if="generations.length"> · {{ generations.length }} 份</template></h4>

        <div v-if="generations.length === 0" class="pend-empty">还没有生成记录；在上方选格式后点「生成」产出一份</div>

        <div v-for="g in generations" :key="g.id" class="art">
          <div class="art-body">
            <!-- HTML 演示缩略（色板用该主题真实调色板；无 palette 时中性占位，不硬编码） -->
            <button
              v-if="g.format === 'html'"
              type="button"
              class="deck-thumb"
              :style="thumbStyle(g)"
              @click="openArtifact(g)"
            >
              <span class="dt-bar" :style="thumbBarStyle(g)"></span>
              <span class="dt-t">{{ deckThumbTitle(g) }}</span>
              <span class="dt-s">{{ themeNameOf(g) }} · 单文件 HTML</span>
              <span class="dt-f mono">file:// · {{ meta(g)?.slides ?? '—' }} 页</span>
              <span class="deck-thumb-cap">
                <el-icon class="ico"><Film /></el-icon>打开演示
              </span>
            </button>
            <el-icon v-else class="ico-lg doc-ico"><Document /></el-icon>

            <div class="art-main">
              <div class="art-head">
                <span class="art-name">{{ baseName(g.file_path) }}</span>
                <span class="sp"></span>
                <el-tag size="small" :type="g.format === 'docx' ? 'primary' : 'success'" effect="plain">
                  {{ formatLabel(g) }}
                </el-tag>
                <el-tag
                  size="small"
                  :type="meta(g) ? (meta(g)!.integrity_ok ? 'success' : 'danger') : 'info'"
                  effect="plain"
                >
                  {{ meta(g) ? (meta(g)!.integrity_ok ? '完整性通过' : '完整性未过') : '完整性未附带' }}
                </el-tag>
              </div>

              <dl class="art-kv">
                <dt>{{ isThemeBased(g.format) ? '所用主题' : '实际所用模板' }}</dt>
                <dd>
                  {{ isThemeBased(g.format) ? themeNameOf(g) : g.template_used }}
                  <span class="muted">（{{ isThemeBased(g.format) ? '主题即模板' : tplSource(g.template_used) }}）</span>
                </dd>
                <dt>生成时间</dt>
                <dd>{{ formatDateTime(g.created_at) }}</dd>
                <dt>产物位置</dt>
                <dd class="mono path">{{ g.file_path }}</dd>

                <template v-if="g.format === 'docx' && meta(g)">
                  <dt>样式映射</dt>
                  <dd>
                    <span v-if="meta(g)!.template_style_applied" class="ok-t">已套用模板样式</span>
                    <span v-else class="warn-t">
                      模板缺样式，已回退（加粗/字号/前缀），缺失：{{ meta(g)!.missing_styles.join('、') || '—' }}
                    </span>
                  </dd>
                  <dt>标题数</dt>
                  <dd>{{ meta(g)!.headings }}</dd>
                </template>

                <template v-else-if="g.format === 'html' && meta(g)">
                  <dt>内联字体</dt>
                  <dd>{{ meta(g)!.inlined_fonts.length ? meta(g)!.inlined_fonts.join('、') : '无西文内联' }}</dd>
                  <dt>中文回退</dt>
                  <dd>{{ meta(g)!.cjk_fallback ? '系统字体回退（未内联 CJK）' : '—' }}</dd>
                  <dt>页数</dt>
                  <dd>{{ meta(g)!.slides }} 页</dd>
                  <dt>外部资源</dt>
                  <dd>
                    <span v-if="meta(g)!.external_resources.length === 0" class="ok-t">0 条 · 自包含</span>
                    <span v-else class="err-t">{{ meta(g)!.external_resources.join('、') }}</span>
                  </dd>
                  <dt v-if="meta(g)!.network_resources_declared.length">网络资源声明</dt>
                  <dd v-if="meta(g)!.network_resources_declared.length" class="warn-t">
                    {{ meta(g)!.network_resources_declared.join('、') }}
                  </dd>
                  <dt>演讲者模式</dt>
                  <dd>{{ presenterLabel(meta(g)!.presenter_mode) }}</dd>
                </template>

                <p v-else class="hint">
                  {{
                    g.format === 'html'
                      ? '主题内联 / 页数等明细仅随本次生成响应返回，历史列表项只能从 deck-theme 记录推断主题。'
                      : g.format === 'pptx'
                        ? '截图版 PPT：页面由 HTML deck 逐页截图装配，文字不可编辑；页数等明细仅随本次生成响应返回。'
                        : '样式映射 / 标题数等明细仅随本次生成响应返回，历史列表项不附带。'
                  }}
                </p>
              </dl>

              <div class="art-acts">
                <el-button v-if="g.format === 'html'" size="small" type="primary" :icon="Film" @click="openArtifact(g)">
                  打开演示
                </el-button>
                <el-button size="small" :loading="viewerLoading" @click="openArtifact(g)">
                  {{ g.format === 'html' ? '下载 .html' : g.format === 'pptx' ? '下载 .pptx' : '打开文件' }}
                </el-button>
                <span class="xs muted">也可在文件管理器按上方路径直接双击打开</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 演示态：应用内全屏预览自包含 .html -->
    <DeckViewer
      :open="deckViewer.open"
      :html="deckViewer.html"
      :filename="deckViewer.filename"
      :theme-name="deckViewer.themeName"
      :slides="deckViewer.slides"
      :file-path="deckViewer.filePath"
      @close="deckViewer.open = false"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Box,
  Document,
  Film,
  Lock,
  Select,
  WarningFilled
} from '@element-plus/icons-vue'
import {
  BackendUnavailableError,
  DeliverableUnavailableError,
  downloadDeliverable,
  fetchDeliverableHtml,
  generateDeliverable,
  getDeckThemeDefault,
  getDeckThemes,
  getTemplates,
  isApiStatus,
  listGenerations,
  type DeckTheme,
  type Generation,
  type GenerationFormat,
  type GenerationResponse,
  type Template
} from '../api/client'
import { formatDateTime } from '../utils/taskMeta'
import {
  formatOptions as builtInFormatOptions,
  isThemeBased
} from '../utils/generationFormats'
import DeckViewer from './DeckViewer.vue'

const props = defineProps<{
  taskId: number
  locked: boolean
  lockReason?: string
}>()

const BUILTIN_TEMPLATE = '_builtin/minimal-default.docx'
const DECK_THEME_PREFIX = 'deck-theme:'
/**
 * 「跟随全局默认模板」的下拉值：不能用空串（Element Plus 把空串当未选择，
 * 会把选项文案显示成占位符），这里用哨兵并在提交时映射回 null。
 */
const TEMPLATE_DEFAULT = '__global_default__'

const format = ref<GenerationFormat>('docx')
const templateSel = ref<string>(TEMPLATE_DEFAULT)
/** 演示主题：空串 = 跟随设置页的全局默认主题（生成时不带 theme，由后端按默认产出）。 */
const theme = ref('')
const templates = ref<Template[]>([])
const themes = ref<DeckTheme[]>([])
const themesLoading = ref(true)
/** 后端记录的全局默认主题 id（GET /api/settings/deck-theme）。 */
const deckDefault = ref('')
const deckDefaultState = ref<'loading' | 'ready' | 'error'>('loading')
const generations = ref<Generation[]>([])
const metaById = ref<Record<number, GenerationResponse>>({})
const generating = ref(false)
const viewerLoading = ref(false)
const genError = ref('')
const genErrorTitle = ref('')
const canRetryBuiltin = ref(false)

const deckViewer = reactive({
  open: false,
  html: '',
  filename: '',
  themeName: '',
  slides: 0,
  filePath: ''
})

const docxTemplates = computed(() => templates.value.filter((t) => t.format === 'docx'))
const globalDefaultName = computed(
  () => docxTemplates.value.find((t) => t.is_default)?.name || ''
)

/** 格式选择卡元数据（pptFrontend util 统一给文案，选择前即说明可编辑 vs 截图差异）。 */
const formatOptions = computed(() => builtInFormatOptions())
/** 生成按钮文案，按当前格式定（html / pptx 都叫「演示」，docx 叫 Word）。 */
const generateButtonText = computed(() => {
  if (format.value === 'html') return '生成单文件 HTML 演示'
  if (format.value === 'pptx') return '生成截图版 PPT'
  return '生成 Word 成品'
})
/** 生成成功的弹层文案，按当前格式定。 */
const generateSuccessText = computed(() => {
  if (format.value === 'html') return '已生成单文件 HTML 演示'
  if (format.value === 'pptx') return '已生成截图版 PPT'
  return '已生成 Word 成品'
})

function meta(g: Generation): GenerationResponse | null {
  return metaById.value[g.id] ?? null
}
function baseName(p: string): string {
  return p.split(/[\\/]/).pop() || p
}
/** 成品格式的中文标签（成品卡 tag / 缩略副标题共用）。 */
function formatLabel(g: Generation): string {
  if (g.format === 'docx') return 'Word'
  if (g.format === 'pptx') return '截图版 PPT'
  if (g.format === 'pdf') return 'PDF'
  return '单文件 HTML'
}

/** HTML 记录的 template_used 形如 `deck-theme:slate`，据此推断主题。 */
function themeIdOf(g: Generation): string {
  const fromMeta = meta(g)?.theme_used
  if (fromMeta) return fromMeta
  return g.template_used.startsWith(DECK_THEME_PREFIX)
    ? g.template_used.slice(DECK_THEME_PREFIX.length)
    : g.template_used
}
function themeInfo(g: Generation): DeckTheme | undefined {
  const id = themeIdOf(g)
  return themes.value.find((t) => t.id === id || t.name === id)
}
function themeNameOf(g: Generation): string {
  const t = themeInfo(g)
  if (t) return t.name
  const id = themeIdOf(g)
  if (id.startsWith(DECK_THEME_PREFIX)) return id.slice(DECK_THEME_PREFIX.length)
  return id
}
function thumbStyle(g: Generation): Record<string, string> {
  const p = themeInfo(g)?.palette
  if (!p) return {}
  return { background: p.bg, color: p.fg }
}
function thumbBarStyle(g: Generation): Record<string, string> {
  const p = themeInfo(g)?.palette
  if (!p) return { background: 'var(--brand-500)' }
  return { background: p.accent }
}
function deckThumbTitle(g: Generation): string {
  return g.format === 'html' ? '结构化方案演示' : baseName(g.file_path)
}
function presenterLabel(mode: string | null): string {
  if (mode === 'in-page-overlay') return '页内覆盖层（按 S 切换）'
  if (!mode) return '—'
  return mode
}
function tplSource(name: string): string {
  if (name.startsWith('_builtin/')) return '内置最小默认模板'
  const t = docxTemplates.value.find((x) => x.name === name)
  if (t?.is_default) return '用户模板 · 全局默认'
  if (t) return '用户模板 · 本任务临时选择'
  return '用户模板'
}
function tplSuffix(t: Template): string {
  if (t.missing) return '（文件已缺失）'
  if (t.builtin) return '（内置最小默认）'
  if (t.is_default) return '（全局默认）'
  return ''
}

async function loadTemplates(): Promise<void> {
  try {
    templates.value = (await getTemplates()).items
  } catch {
    templates.value = []
  }
}

async function loadThemes(): Promise<void> {
  themesLoading.value = true
  try {
    // 只填清单，不预选具体主题：默认保持「跟随全局默认主题」（theme 为空）
    themes.value = (await getDeckThemes()).items
  } catch {
    themes.value = []
  } finally {
    themesLoading.value = false
  }
}

/** 读取全局默认主题，用于「跟随全局默认」卡片上的说明；失败不阻塞生成。 */
async function loadDeckDefault(): Promise<void> {
  deckDefaultState.value = 'loading'
  try {
    deckDefault.value = (await getDeckThemeDefault()).theme
    deckDefaultState.value = 'ready'
  } catch {
    deckDefault.value = ''
    deckDefaultState.value = 'error'
  }
}

/** 全局默认对应的主题详情：清单里找不到就返回 null（说明文字仍按 id 原样显示，不静默替换）。 */
const defaultThemeInfo = computed<DeckTheme | null>(() =>
  deckDefault.value
    ? themes.value.find((t) => t.id === deckDefault.value || t.name === deckDefault.value) ?? null
    : null
)

/** 「跟随全局默认主题」卡片的副文案。 */
const followThemeText = computed(() => {
  if (deckDefaultState.value === 'loading') return '正在读取全局默认主题…'
  if (deckDefaultState.value === 'error') return '全局默认主题读取失败，将使用内建默认'
  if (!deckDefault.value) return '全局默认主题未读取到，将使用内建默认'
  return `当前：${defaultThemeInfo.value?.name ?? deckDefault.value}`
})

async function loadGenerations(): Promise<void> {
  try {
    generations.value = (await listGenerations(props.taskId)).items
  } catch {
    generations.value = []
  }
}

async function runGenerate(override?: string | null): Promise<void> {
  if (generating.value) return
  generating.value = true
  genError.value = ''
  genErrorTitle.value = ''
  canRetryBuiltin.value = false
  const template =
    override !== undefined ? override : templateSel.value === TEMPLATE_DEFAULT ? null : templateSel.value
  try {
    const resp = await generateDeliverable(props.taskId, {
      format: format.value,
      template: format.value === 'docx' ? template : null,
      // html 与 pptx（截图版 PPT）同源：都按主题选择；docx 不带主题。
      theme: format.value === 'docx' ? null : theme.value || null
    })
    generations.value = [resp, ...generations.value]
    metaById.value = { ...metaById.value, [resp.id]: resp }
    ElMessage.success(generateSuccessText.value)
  } catch (err) {
    handleGenError(err)
  } finally {
    generating.value = false
  }
}

function handleGenError(err: unknown): void {
  if (err instanceof BackendUnavailableError) {
    genErrorTitle.value = '后端未启动'
    genError.value = '无法生成成品，请确认本地服务已启动后重试。'
    return
  }
  const msg = (err as Error).message || ''
  if (isApiStatus(err, 409)) {
    genErrorTitle.value = '生成闸门未放行'
    genError.value = '方案未确认或仍有未处置的待确认事项：' + tailDetail(msg)
  } else if (isApiStatus(err, 400)) {
    // Word 模板不可用 或 HTML/PPT 未知主题：都明确报错、不静默退回。
    const isTheme = format.value !== 'docx'
    genErrorTitle.value = isTheme
      ? '主题不可用，已按规则拒绝生成（不静默退回默认主题）'
      : '模板不可用，已按规则拒绝生成（不会静默产出空白文档）'
    genError.value = tailDetail(msg)
    canRetryBuiltin.value = !isTheme
  } else if (isApiStatus(err, 500)) {
    genErrorTitle.value = '完整性检查未通过，产物已丢弃'
    genError.value = tailDetail(msg)
  } else if (isApiStatus(err, 501)) {
    genErrorTitle.value = '该格式暂不可用'
    genError.value = '该成品格式后端尚未落地。'
  } else {
    genErrorTitle.value = '生成失败'
    genError.value = msg
  }
}

function tailDetail(msg: string): string {
  const idx = msg.indexOf('·')
  return idx >= 0 ? msg.slice(idx + 1).trim() : msg
}

function retryBuiltin(): void {
  templateSel.value = BUILTIN_TEMPLATE
  void runGenerate(BUILTIN_TEMPLATE)
}

/** 打开成品：HTML → 应用内演示态（经 deliverables 取回内容）；Word → 下载。取不到时如实降级。 */
async function openArtifact(g: Generation): Promise<void> {
  if (viewerLoading.value) return
  const filename = baseName(g.file_path)
  if (g.format === 'html') {
    viewerLoading.value = true
    try {
      const html = await fetchDeliverableHtml(g.id)
      deckViewer.html = html
      deckViewer.filename = filename
      deckViewer.themeName = themeNameOf(g)
      deckViewer.slides = meta(g)?.slides ?? 0
      deckViewer.filePath = g.file_path
      deckViewer.open = true
    } catch (err) {
      degradeOpen(err, filename)
    } finally {
      viewerLoading.value = false
    }
  } else {
    viewerLoading.value = true
    try {
      await downloadDeliverable(g.id, filename)
    } catch (err) {
      degradeOpen(err, filename)
    } finally {
      viewerLoading.value = false
    }
  }
}

function degradeOpen(err: unknown, filename: string): void {
  if (err instanceof BackendUnavailableError) {
    ElMessage.error('后端未启动，无法打开成品')
  } else if (err instanceof DeliverableUnavailableError) {
    ElMessage.warning(`成品投递暂不可用（${filename}），可在文件管理器按路径双击打开`)
  } else {
    ElMessage.error('打开失败：' + (err as Error).message)
  }
}

function refresh(): void {
  if (props.taskId > 0) {
    loadTemplates()
    loadGenerations()
  }
}

// 切换任务时清掉上一个任务的临时选择，避免把 A 任务的主题 / 模板带到 B 任务，
// 使「跟随全局默认」在新任务上仍然是真正的默认值。
watch(() => props.taskId, () => {
  templateSel.value = TEMPLATE_DEFAULT
  theme.value = ''
  refresh()
})
// 切到 html / pptx（都按主题）时刷新一次全局默认，反映设置页里刚改过的值（不阻塞、不报错打扰）
watch(format, (next) => {
  if (next !== 'docx') void loadDeckDefault()
})
onMounted(() => {
  loadThemes()
  loadDeckDefault()
  refresh()
})
</script>

<style scoped>
.tag-ico {
  vertical-align: -2px;
}
.gp-lock {
  display: flex;
  gap: var(--sp-3);
  align-items: flex-start;
  padding: var(--sp-4) var(--sp-5);
  background: var(--bg-sunken);
  border-top: 1px solid var(--line-1);
}
.gp-lock > .ico {
  width: 18px;
  height: 18px;
  color: var(--text-4);
  margin-top: 2px;
  flex: none;
  font-size: 18px;
}
.gp-lock b {
  display: block;
  font-size: var(--fs-sm);
  color: var(--text-1);
}
.gp-lock p {
  font-size: var(--fs-sm);
  color: var(--text-3);
  margin: 4px 0 0;
  max-width: 66ch;
  line-height: 1.6;
}

.gfield {
  margin-bottom: var(--sp-5);
}
.gfield > label {
  display: block;
  font-size: var(--fs-xs);
  color: var(--text-3);
  font-weight: 600;
  letter-spacing: 0.3px;
  margin-bottom: var(--sp-2);
}
.fmt-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: var(--sp-3);
}
.fmt {
  display: flex;
  gap: var(--sp-3);
  align-items: flex-start;
  border: 1px solid var(--line-2);
  border-radius: var(--r-md);
  padding: var(--sp-3);
  background: var(--bg-surface);
  cursor: pointer;
}
.fmt input {
  margin-top: 3px;
  accent-color: var(--brand-500);
  flex: none;
}
.fmt > span {
  min-width: 0;
}
.fmt b {
  display: block;
  font-size: var(--fs-sm);
  color: var(--text-1);
}
.fmt .d {
  display: block;
  font-size: var(--fs-xs);
  color: var(--text-3);
  margin-top: 2px;
  line-height: 1.55;
}
.fmt.sel {
  border-color: var(--brand-500);
  background: var(--brand-50);
  box-shadow: 0 0 0 2px var(--brand-50);
}
.fmt.is-plan {
  background: var(--bg-sunken);
  border-style: dashed;
  cursor: not-allowed;
}
.fmt.is-plan b {
  color: var(--text-3);
}
.fmt.is-plan .d {
  color: var(--text-4);
}
.mini {
  margin-left: 6px;
  vertical-align: 1px;
}

/* 主题选择（色卡来自接口 palette，不硬编码） */
.theme-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--sp-3);
}
.theme-opt {
  display: flex;
  gap: var(--sp-3);
  align-items: flex-start;
  border: 1px solid var(--line-1);
  border-radius: var(--r-md);
  padding: var(--sp-3);
  cursor: pointer;
  background: var(--bg-surface);
}
.theme-opt:hover {
  border-color: var(--brand-200);
}
.theme-opt input {
  margin-top: 3px;
  accent-color: var(--brand-500);
  flex: none;
}
.theme-opt > span {
  min-width: 0;
}
.theme-opt b {
  display: block;
  font-size: var(--fs-sm);
  color: var(--text-1);
}
.td {
  display: block;
  font-size: var(--fs-xs);
  color: var(--text-3);
}
.theme-opt.sel {
  border-color: var(--brand-500);
  background: var(--brand-50);
  box-shadow: 0 0 0 2px var(--brand-50);
}

/* 「跟随全局默认」与其它主题卡同权重，只是不指定具体主题 */
.theme-opt.is-follow .td {
  color: var(--text-2);
}
.theme-chips i.void {
  background: repeating-linear-gradient(
    135deg,
    var(--line-2) 0 3px,
    var(--bg-sunken) 3px 6px
  );
}
.theme-loading {
  align-self: center;
  padding: var(--sp-3) 0;
}
.theme-chips {
  display: flex;
  gap: 3px;
  margin-top: 6px;
}
.theme-chips i {
  width: 14px;
  height: 14px;
  border-radius: 3px;
  display: block;
  border: 1px solid rgba(0, 0, 0, 0.12);
}
.th-src {
  display: block;
  font-size: 10px;
  color: var(--text-4);
  margin-top: 4px;
}
.th-net {
  display: block;
  font-size: var(--fs-xs);
  margin-top: 2px;
}
.th-net.ok {
  color: var(--ok-fg);
}
.th-net:not(.ok) {
  color: var(--warn-fg);
}
.th-fonts {
  color: var(--text-4);
  font-family: var(--font-mono);
}

.tpl-select {
  width: 100%;
}
.hint {
  font-size: var(--fs-xs);
  color: var(--text-3);
  line-height: 1.55;
  margin: var(--sp-2) 0 0;
}

.gp-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
  padding-top: var(--sp-2);
}
.mono {
  font-family: var(--font-mono);
}
.gp-bar {
  height: 4px;
  border-radius: var(--r-pill);
  background: var(--line-1);
  overflow: hidden;
  margin-top: var(--sp-3);
}
.gp-bar.indeterminate > i {
  display: block;
  height: 100%;
  width: 40%;
  border-radius: var(--r-pill);
  background: var(--brand-500);
  animation: gp-slide 1.1s ease-in-out infinite;
}
@keyframes gp-slide {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(300%);
  }
}
@media (prefers-reduced-motion: reduce) {
  .gp-bar.indeterminate > i {
    animation: none;
    width: 100%;
    opacity: 0.5;
  }
}

.retry-row {
  margin-top: var(--sp-1);
}

.art-wrap {
  margin-top: var(--sp-6);
  border-top: 1px solid var(--line-1);
  padding-top: var(--sp-4);
}
.art-wrap h4 {
  margin: 0 0 var(--sp-3);
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text-1);
}
.pend-empty {
  border: 1px dashed var(--line-3);
  border-radius: var(--r-sm);
  background: var(--bg-sunken);
  padding: var(--sp-4);
  font-size: var(--fs-sm);
  color: var(--text-3);
  text-align: center;
}
.art {
  border: 1px solid var(--line-1);
  border-radius: var(--r-md);
  padding: var(--sp-3) var(--sp-4);
  background: var(--bg-surface);
  margin-bottom: var(--sp-3);
}
.art-body {
  display: flex;
  gap: var(--sp-4);
  align-items: flex-start;
  flex-wrap: wrap;
}
.art-main {
  flex: 1;
  min-width: 260px;
}
.doc-ico {
  color: var(--brand-600);
  font-size: 34px;
  flex: none;
}
.art-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.art-name {
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text-1);
  word-break: break-all;
}
.art-head .sp {
  margin-left: auto;
}
.art-kv {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: 4px var(--sp-3);
  margin: var(--sp-3) 0 0;
  font-size: var(--fs-xs);
}
.art-kv dt {
  color: var(--text-3);
}
.art-kv dd {
  margin: 0;
  color: var(--text-2);
  line-height: 1.6;
  word-break: break-all;
}
.art-kv .path {
  color: var(--text-2);
}
.art-kv .ok-t {
  color: var(--ok-fg);
}
.art-kv .warn-t {
  color: var(--warn-fg);
}
.art-kv .err-t {
  color: var(--err-fg);
}
.art-kv .hint {
  grid-column: 1 / -1;
  margin-top: var(--sp-1);
}
.art-acts {
  display: flex;
  gap: var(--sp-2);
  align-items: center;
  flex-wrap: wrap;
  margin-top: var(--sp-3);
}

/* HTML 演示缩略（原型 .deck-thumb） */
.deck-thumb {
  flex: none;
  width: 198px;
  padding: 0;
  border: 1px solid var(--line-2);
  border-radius: var(--r-sm);
  overflow: hidden;
  background: none;
  display: block;
  cursor: pointer;
  text-align: left;
}
.deck-thumb:hover {
  border-color: var(--brand-200);
  box-shadow: 0 0 0 3px var(--brand-50);
}
.deck-thumb .dt-bar,
.deck-thumb .dt-t,
.deck-thumb .dt-s,
.deck-thumb .dt-f {
  display: block;
}
.deck-thumb .dt {
  display: flex;
  flex-direction: column;
}
.deck-thumb > .dt-bar {
  width: 22px;
  height: 3px;
  border-radius: 2px;
  margin: 10px 12px 8px;
  background: var(--brand-500);
}
.deck-thumb .dt-t {
  font-size: 13px;
  line-height: 1.25;
  font-weight: 600;
  padding: 0 12px;
}
.deck-thumb .dt-s {
  font-size: 10px;
  opacity: 0.7;
  margin-top: 4px;
  padding: 0 12px;
}
.deck-thumb .dt-f {
  font-size: 9px;
  opacity: 0.5;
  margin: 8px 12px 0;
}
.deck-thumb-cap {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 5px 0;
  font-size: var(--fs-xs);
  color: var(--text-2);
  background: var(--bg-sunken);
  border-top: 1px solid var(--line-1);
}
.deck-thumb:hover .deck-thumb-cap {
  color: var(--brand-600);
  background: var(--brand-50);
}

@media (max-width: 820px) {
  .card-body {
    padding-left: var(--sp-4);
    padding-right: var(--sp-4);
  }
}
</style>

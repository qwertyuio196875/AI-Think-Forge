<template>
  <div class="gpanel card" :class="{ 'is-locked': locked }">
    <div class="card-head">
      <h3>生成面板</h3>
      <span class="sub">选格式 · 选模板 · 拿产物</span>
      <span class="right">
        <el-tag size="small" :type="locked ? 'warning' : 'success'" effect="plain">
          <el-icon class="tag-ico"><Lock v-if="locked" /><Select v-else /></el-icon>
          {{ locked ? '未解锁 · 方案还没确认' : '已解锁 · 可生成 Word 成品' }}
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
          <label class="fmt" :class="{ sel: format === 'docx' }">
            <input v-model="format" type="radio" name="gpfmt" value="docx" />
            <span><b>Word 文档</b><span class="d">python-docx 按模板写入，回读校验完整性；产出 .docx</span></span>
          </label>
          <label class="fmt is-plan" :title="'属 TB-6'">
            <input v-model="format" type="radio" name="gpfmt" value="html" disabled />
            <span>
              <b>单文件 HTML 演示<el-tag class="mini" size="small" type="info" effect="plain">属 TB-6</el-tag></b>
              <span class="d">ADR-0003 的另一轨；此刻后端对 format=html 返回 501，不可生成</span>
            </span>
          </label>
          <label class="fmt is-plan" title="v1.1 计划">
            <input type="radio" name="gpfmt" disabled />
            <span>
              <b>PowerPoint .pptx<el-tag class="mini" size="small" type="info" effect="plain">v1.1 计划</el-tag></b>
              <span class="d">v1 不生成 .pptx，也不会把 HTML 或截图冒充 PPT</span>
            </span>
          </label>
        </div>
      </div>

      <!-- Word 模板：任务级临时覆盖 -->
      <div class="gfield">
        <label>Word 模板 · 本任务临时选择</label>
        <el-select v-model="templateSel" class="tpl-select" placeholder="跟随全局默认模板">
          <el-option label="跟随全局默认模板" value="" />
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

      <!-- 生成动作 -->
      <div class="gp-actions">
        <el-button type="primary" size="large" :loading="generating" :icon="Box" @click="runGenerate()">
          {{ generating ? '正在生成…' : '生成 Word 成品' }}
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

        <div v-if="generations.length === 0" class="pend-empty">还没有生成记录；点上方「生成 Word 成品」产出一份</div>

        <div v-for="g in generations" :key="g.id" class="art">
          <div class="art-head">
            <el-icon class="ico a-ico"><Document /></el-icon>
            <span class="art-name">{{ baseName(g.file_path) }}</span>
            <span class="sp"></span>
            <el-tag size="small" :type="g.format === 'docx' ? 'primary' : 'info'" effect="plain">
              {{ g.format === 'docx' ? 'Word' : 'HTML' }}
            </el-tag>
            <el-tag size="small" :type="meta(g) ? (meta(g)!.integrity_ok ? 'success' : 'danger') : 'info'" effect="plain">
              {{ meta(g) ? (meta(g)!.integrity_ok ? '完整性通过' : '完整性未过') : '完整性未附带' }}
            </el-tag>
          </div>

          <dl class="art-kv">
            <dt>实际所用模板</dt>
            <dd>
              {{ g.template_used }}
              <span class="muted">（{{ tplSource(g.template_used) }}）</span>
            </dd>
            <dt>生成时间</dt>
            <dd>{{ formatDateTime(g.created_at) }}</dd>
            <dt>产物位置</dt>
            <dd class="mono path">{{ g.file_path }}</dd>
            <template v-if="meta(g)">
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
            <p v-else class="hint">样式映射 / 标题数等明细仅随本次生成响应返回，历史列表项不附带。</p>
          </dl>

          <div class="art-acts">
            <!-- 无打开接口：如实标注不可用，不伪造已打开 -->
            <el-button size="small" disabled>打开文件（无接口）</el-button>
            <span class="xs muted">可在文件管理器中按上方路径定位该 .docx</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Box,
  Document,
  Lock,
  Select,
  WarningFilled
} from '@element-plus/icons-vue'
import {
  BackendUnavailableError,
  generateDeliverable,
  getTemplates,
  listGenerations,
  type Generation,
  type GenerationFormat,
  type GenerationResponse,
  type Template
} from '../api/client'
import { formatDateTime } from '../utils/taskMeta'

const props = defineProps<{
  taskId: number
  locked: boolean
  lockReason?: string
}>()

const BUILTIN_TEMPLATE = '_builtin/minimal-default.docx'

const format = ref<GenerationFormat>('docx')
const templateSel = ref('')
const templates = ref<Template[]>([])
const generations = ref<Generation[]>([])
const metaById = ref<Record<number, GenerationResponse>>({})
const generating = ref(false)
const genError = ref('')
const genErrorTitle = ref('')
const canRetryBuiltin = ref(false)

const docxTemplates = computed(() => templates.value.filter((t) => t.format === 'docx'))
const globalDefaultName = computed(
  () => docxTemplates.value.find((t) => t.is_default)?.name || ''
)

function meta(g: Generation): GenerationResponse | null {
  return metaById.value[g.id] ?? null
}
function baseName(p: string): string {
  return p.split(/[\\/]/).pop() || p
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
  const template = override !== undefined ? override : templateSel.value || null
  try {
    const resp = await generateDeliverable(props.taskId, { format: format.value, template })
    generations.value = [resp, ...generations.value]
    metaById.value = { ...metaById.value, [resp.id]: resp }
    ElMessage.success('已生成 Word 成品')
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
  if (msg.includes('409')) {
    genErrorTitle.value = '生成闸门未放行'
    genError.value = '方案未确认或仍有未处置的待确认事项：' + tailDetail(msg)
  } else if (msg.includes('400')) {
    genErrorTitle.value = '模板不可用，已按规则拒绝生成（不会静默产出空白文档）'
    genError.value = tailDetail(msg)
    canRetryBuiltin.value = true
  } else if (msg.includes('501')) {
    genErrorTitle.value = '该格式暂不可用'
    genError.value = '单文件 HTML 演示由 TB-6 落地。'
  } else if (msg.includes('500')) {
    genErrorTitle.value = '完整性检查未通过，产物已丢弃'
    genError.value = tailDetail(msg)
  } else {
    genErrorTitle.value = '生成失败'
    genError.value = msg
  }
}

/** 从「请求失败：<code> <text> · <detail>」里取可读 detail 部分。 */
function tailDetail(msg: string): string {
  const idx = msg.indexOf('·')
  return idx >= 0 ? msg.slice(idx + 1).trim() : msg
}

function retryBuiltin(): void {
  templateSel.value = BUILTIN_TEMPLATE
  void runGenerate(BUILTIN_TEMPLATE)
}

function refresh(): void {
  if (props.taskId > 0) {
    loadTemplates()
    loadGenerations()
  }
}

watch(() => props.taskId, refresh)
onMounted(refresh)
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
.art-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.art-head .a-ico {
  color: var(--brand-600);
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

@media (max-width: 820px) {
  .card-body {
    padding-left: var(--sp-4);
    padding-right: var(--sp-4);
  }
}
</style>

<template>
  <div class="card sfc-card">
    <div class="card-head">
      <h3>逐章填充</h3>
      <span class="sub">一章一写 · 可选引用 · 即刻出成品</span>
    </div>

    <!-- 读取中：不先渲染空清单，否则会闪一下「没有章节」 -->
    <div v-if="state === 'loading'" class="card-body sfc-loading">
      <el-skeleton :rows="3" animated />
    </div>

    <!-- 读取失败 -->
    <div v-else-if="state === 'error'" class="card-body">
      <div class="note err" role="alert">
        <el-icon class="ico"><WarningFilled /></el-icon>
        <div class="note-body">
          <b>章节清单读取失败</b>
          <span>{{ errorText }}</span>
        </div>
      </div>
      <div class="sfc-actions">
        <el-button size="small" @click="load">重新读取</el-button>
      </div>
    </div>

    <div v-else class="card-body">
      <ol v-if="sections.length" class="sfc-list">
        <li v-for="it in sections" :key="it.seq" class="sfc-item">
          <span class="sfc-line">{{ sectionLine(it) }}</span>
          <el-tag
            size="small"
            :type="sectionStatusTag(it.status).type"
            effect="plain"
            class="sfc-tag"
          >
            {{ sectionStatusLabel(it) }}
          </el-tag>
          <el-button
            size="small"
            type="primary"
            plain
            :disabled="it.status === 'completed'"
            @click="openSection(it)"
          >
            {{ it.status === 'completed' ? '已写完' : '写这一章' }}
          </el-button>
        </li>
      </ol>

      <div v-else class="note warn" role="status">
        <el-icon class="ico"><WarningFilled /></el-icon>
        <div class="note-body">
          <b>{{ sectionListHeadline(0) }}</b>
          <span>{{ EMPTY_SECTIONS_HINT }}</span>
        </div>
      </div>

      <p class="sfc-hint xs muted">
        每章写前可选「引用片段」：默认全选知识库资料，可逐条取消；取消的不进本章正文。
        成品末尾的「参考资料」只列实际用到的来源。
      </p>
    </div>

    <!-- 单章填充弹窗：先预览引用卡片（默认全选），确认后再真正写 -->
    <ParamDialog
      :model-value="dialog.visible"
      title="写这一章"
      confirm-text="开始写这一章"
      :loading="dialog.writing"
      @confirm="write"
      @cancel="close"
      @update:model-value="onDialogVisible"
    >
      <template v-if="dialog.section">
        <p class="sfc-dialog-title">
          <b>{{ dialog.section.title }}</b>
          <span class="xs muted">（{{ sectionLengthText(dialog.section.target_length) }}）</span>
        </p>

        <!-- 预览中的检索状态：降级 / 未使用知识库必须明示 -->
        <div v-if="retrievalNoticeText" class="note warn sfc-retrieval" role="status">
          <el-icon class="ico"><WarningFilled /></el-icon>
          <div class="note-body">
            <b>检索未完全生效</b>
            <span>{{ retrievalNoticeText }}</span>
          </div>
        </div>

        <div v-if="dialog.previewError" class="note err sfc-preview-error" role="alert">
          <el-icon class="ico"><WarningFilled /></el-icon>
          <div class="note-body">
            <b>{{ dialog.previewErrorTitle }}</b>
            <span>{{ dialog.previewError }}</span>
          </div>
        </div>

        <!-- 引用卡片：默认全选、逐条可取消 -->
        <div v-if="dialog.cards.length && state === 'ready'" class="sfc-cites">
          <div class="sfc-cites-head">
            <span class="xs muted">{{ adoptionSummary(dialog.cards) }}</span>
          </div>
          <el-checkbox-group v-model="dialog.keptChunkIds" class="sfc-cite-group">
            <div v-for="card in dialog.cards" :key="card.chunk_id" class="sfc-cite">
              <el-checkbox :value="card.chunk_id" class="sfc-cite-check">
                {{ citationHeadline(card) }}
              </el-checkbox>
              <div v-if="isCollapsible(card)" class="sfc-cite-text xs muted">{{ card.text }}</div>
            </div>
          </el-checkbox-group>
          <el-checkbox
            :model-value="allAdopted"
            :indeterminate="someAdopted && !allAdopted"
            class="sfc-cite-toggle"
            @change="toggleAll"
          >
            <span class="xs">{{ allAdopted ? '保留全部引用' : '取消全部引用' }}</span>
          </el-checkbox>
        </div>
        <div v-else-if="dialog.previewing" class="sfc-cite-empty xs muted">正在检索引用片段…</div>
        <div v-else class="sfc-cite-empty xs muted">
          本次没有可用引用片段（本章将不使用知识库资料）。
        </div>

        <p class="sfc-dialog-note xs muted">
          写这一章会调用模型生成正文，随即拼装成品；本章若已写过，会覆盖既有正文。
        </p>
      </template>
    </ParamDialog>

    <!-- 写成功：轻提示并给出成品下载入口 -->
    <el-dialog v-model="resultVisible" title="写完了" width="460px" append-to-body>
      <p class="sfc-result-text">
        <b>{{ resultTitle }}</b> 已写入，并拼装出完整正文成品。
      </p>
      <template #footer>
        <el-button @click="resultVisible = false">关闭</el-button>
        <el-button
          type="primary"
          :loading="downloading"
          @click="openResult"
        >打开文件</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
/**
 * 逐章填充 + 引用卡片（工单 24）。
 *
 * 在方案确认后出现，把「成品章节」逐章摆出来，每章一个「写这一章」入口。点击后：
 * 1. 先向后端 `POST /sections/{seq}/references` 预览本章可用引用片段（**只读不改库**）；
 * 2. 以折叠卡片呈现引用（文件名 · 定位 · 相关度），默认全选、逐条可取消；
 * 3. 确认后 `POST /sections/{seq}/fill`，把**保留**的片段注入提示词写正文；
 * 4. 成功后返回成品记录，供下载。
 *
 * 参照 ADR-0005 的两道闸：
 * - **引用可撤销**：被取消的片段不进本章 prompt（前端只把保留的传回去）；
 * - **成品参考资料只列实际用到的来源**（后端拼装，前端不另行计算）。
 *
 * 只读边界（ADR-0006）：不改名、不排序、不增删章节；要改章回去走对话修订。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { WarningFilled } from '@element-plus/icons-vue'
import {
  ApiHttpError,
  BackendUnavailableError,
  downloadDeliverable,
  fillSection,
  listPlanSections,
  previewSectionReferences,
  type CitationCard,
  type GenerationResponse,
  type PlanSectionItem,
  type RetrievalStatusInfo
} from '../api/client'
import {
  EMPTY_SECTIONS_HINT,
  sectionLengthText,
  sectionLine,
  sectionListHeadline,
  sectionStatusLabel,
  sectionStatusTag
} from '../utils/sectionList'
import {
  adoptionSummary,
  citationHeadline,
  isAdopted,
  isCollapsible,
  retrievalNotice
} from '../utils/citationCard'
import ParamDialog from './ParamDialog.vue'

const props = defineProps<{
  taskId: number
}>()

type LoadState = 'loading' | 'ready' | 'error'
const state = ref<LoadState>('loading')
const sections = ref<PlanSectionItem[]>([])
const errorText = ref('')

const dialog = reactive<{
  visible: boolean
  section: PlanSectionItem | null
  cards: CitationCard[]
  keptChunkIds: number[]
  previewing: boolean
  previewError: string
  previewErrorTitle: string
  retrieval: RetrievalStatusInfo | null
  writing: boolean
}>({
  visible: false,
  section: null,
  cards: [],
  keptChunkIds: [],
  previewing: false,
  previewError: '',
  previewErrorTitle: '',
  retrieval: null,
  writing: false
})

const resultVisible = ref(false)
const resultDeliverable = ref<GenerationResponse | null>(null)
const downloading = ref(false)

const resultTitle = computed(() => dialog.section?.title ?? '本章')

/** 本次预览中「保留」的片段（勾选集合），用于驱动全选 / 半选显示。 */
const adoptedCount = computed(
  () => dialog.cards.filter((c) => dialog.keptChunkIds.includes(c.chunk_id)).length
)
const allAdopted = computed(
  () => dialog.cards.length > 0 && adoptedCount.value === dialog.cards.length
)
const someAdopted = computed(() => adoptedCount.value > 0)

/** 检索降级 / 未使用知识库的明示文案；正常检索不打扰。 */
const retrievalNoticeText = computed(() =>
  retrievalNotice(dialog.retrieval)
)

async function load(): Promise<void> {
  errorText.value = ''
  try {
    const res = await listPlanSections(props.taskId)
    sections.value = res.items
    state.value = 'ready'
  } catch (err) {
    if (err instanceof BackendUnavailableError) {
      errorText.value = '后端未启动，无法读取章节清单'
    } else if (err instanceof ApiHttpError && err.status === 404) {
      errorText.value = err.detail || '当前任务还没有已确认的结构化方案'
    } else {
      errorText.value = (err as Error).message || '章节清单读取失败'
    }
    sections.value = []
    state.value = 'error'
  }
}

async function openSection(item: PlanSectionItem): Promise<void> {
  dialog.section = item
  dialog.cards = []
  dialog.keptChunkIds = []
  dialog.previewError = ''
  dialog.previewErrorTitle = ''
  dialog.retrieval = null
  dialog.previewing = true
  dialog.writing = false
  dialog.visible = true

  try {
    const res = await previewSectionReferences(props.taskId, item.seq)
    dialog.cards = res.cards
    dialog.retrieval = res.retrieval_status
    // 默认全选：被取消的片段不进提示词，所以 keep 列表初始化为全部。
    dialog.keptChunkIds = res.cards.filter(isAdopted).map((c) => c.chunk_id)
  } catch (err) {
    dialog.previewError = friendlyError(err, '引用预览失败')
    dialog.previewErrorTitle = '引用预览失败'
  } finally {
    dialog.previewing = false
  }
}

function toggleAll(checked: boolean): void {
  dialog.keptChunkIds = checked
    ? dialog.cards.filter(isAdopted).map((c) => c.chunk_id)
    : []
}

async function write(): Promise<void> {
  if (!dialog.section || dialog.writing) return
  dialog.writing = true
  dialog.previewError = ''
  dialog.previewErrorTitle = ''
  try {
    const keptCards = dialog.cards.filter((c) => dialog.keptChunkIds.includes(c.chunk_id))
    const res = await fillSection(props.taskId, dialog.section.seq, {
      reference_cards: keptCards.length ? keptCards : undefined
    })
    const wrote = res.deliverable
    resultDeliverable.value = wrote
    dialog.visible = false
    dialog.section = null
    resultVisible.value = true
    // 刷新章节清单：刚写的这章状态变为已完成
    await load()
  } catch (err) {
    dialog.previewError = friendlyError(err, '写这一章失败')
    dialog.previewErrorTitle = '写这一章失败'
  } finally {
    dialog.writing = false
  }
}

async function openResult(): Promise<void> {
  if (!resultDeliverable.value) return
  downloading.value = true
  try {
    await downloadDeliverable(
      resultDeliverable.value.id,
      `task-${props.taskId}-section-body-${resultDeliverable.value.id}.docx`
    )
    resultVisible.value = false
  } catch {
    // 下载失败保持弹窗打开，让用户重试
  } finally {
    downloading.value = false
  }
}

function onDialogVisible(v: boolean): void {
  dialog.visible = v
}

function close(): void {
  dialog.visible = false
}

function friendlyError(err: unknown, _fallback: string): string {
  if (err instanceof BackendUnavailableError) return '后端未启动'
  if (err instanceof ApiHttpError) {
    return err.status === 409 || err.status === 422 ? err.detail : `${err.status}：${err.detail || '请求失败'}`
  }
  return (err as Error).message || '请求失败'
}

onMounted(load)
</script>

<style scoped>
.sfc-card {
  border-color: var(--line-1);
}
.sfc-loading {
  min-height: 72px;
}
.sfc-list {
  list-style: none;
  margin: 0;
  padding: 0;
  border-top: 1px solid var(--line-1);
}
.sfc-item {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  min-width: 0;
  padding: var(--sp-2) 0;
  border-bottom: 1px solid var(--line-1);
}
.sfc-line {
  flex: 1;
  min-width: 0;
  font-size: var(--fs-sm);
  color: var(--text-1);
}
.sfc-tag {
  flex: none;
}
.sfc-hint {
  margin: var(--sp-3) 0 0;
}
.sfc-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin-top: var(--sp-3);
}
.sfc-dialog-title {
  margin: 0 0 var(--sp-3);
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
}
.sfc-retrieval,
.sfc-preview-error {
  margin-bottom: var(--sp-3);
}
.sfc-cites {
  border: 1px solid var(--line-1);
  border-radius: 6px;
  padding: var(--sp-2);
}
.sfc-cites-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: var(--sp-2);
}
.sfc-cite-group {
  display: block;
}
.sfc-cite {
  padding: var(--sp-2) 0;
  border-bottom: 1px solid var(--line-1);
}
.sfc-cite-check {
  width: 100%;
  align-items: flex-start;
}
.sfc-cite-text {
  padding-left: 24px;
}
.sfc-cite-toggle {
  margin-top: var(--sp-2);
}
.sfc-cite-empty {
  padding: var(--sp-3) 0;
}
.sfc-dialog-note {
  margin: var(--sp-3) 0 0;
}
.sfc-result-text {
  margin: 0;
}
</style>
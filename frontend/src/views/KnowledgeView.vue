<template>
  <section class="view" aria-label="知识库">
    <header class="view-head">
      <div class="head-row">
        <div class="head-title">
          <h1>知识库</h1>
          <p>上传即入库：解析、切块与索引一次完成；这里放的是跨任务复用的长期资料</p>
        </div>
        <div class="head-actions">
          <el-tag size="small" type="info" effect="plain">
            分块 {{ chunkTarget }} / 上限 {{ chunkMax }} 字符
          </el-tag>
          <el-button
            size="small"
            :icon="Refresh"
            :loading="reindexing"
            :disabled="state !== 'ready' || total === 0"
            @click="reindexAll"
          >
            重建索引
          </el-button>
          <el-button size="small" :icon="Refresh" :loading="state === 'loading'" @click="load">
            刷新
          </el-button>
        </div>
      </div>
    </header>

    <div class="view-body">
      <div class="wrap wrap--wide">
        <!-- 上传：与资料分析同一白名单与 50MB 上限，先校验再上传 -->
        <div class="card upload-card">
          <div class="card-body">
            <button
              type="button"
              class="drop"
              :class="{ 'is-drag': dragging, 'is-busy': uploading }"
              :disabled="uploading"
              aria-describedby="kb-drop-help"
              @click="openPicker"
              @dragover.prevent="onDragOver"
              @dragleave.prevent="dragging = false"
              @drop.prevent="onDrop"
            >
              <el-icon class="ico"><Upload /></el-icon>
              <b>{{ uploading ? '正在上传并入库…' : '拖拽文件到此处，或点击选择文件' }}</b>
              <span id="kb-drop-help">
                单次一份 · 不超过 50 MB · TXT / MD / DOCX / PDF / PPTX
              </span>
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
              <span class="xs muted">
                {{ uploadName }} · {{ uploadPercent }}%{{
                  uploadPercent >= 100 ? '（上传完成，正在解析入库）' : ''
                }}
              </span>
            </div>

            <div v-if="rejectNote" class="note err" role="alert" style="margin-top: var(--sp-4)">
              <el-icon class="ico"><WarningFilled /></el-icon>
              <div class="note-body"><span>{{ rejectNote }}</span></div>
            </div>

            <!-- 失败必须可见：解析 / 索引失败仍留在清单里，这里再提示一次原因 -->
            <div v-if="lastFailure" class="note warn" role="alert" style="margin-top: var(--sp-4)">
              <el-icon class="ico"><WarningFilled /></el-icon>
              <div class="note-body">
                <b>{{ lastFailure.name }} 未完成索引</b>
                <span>{{ lastFailure.reason }}。资料已保存，可删除后重新上传。</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 加载 -->
        <div v-if="state === 'loading'" class="list-loading">
          <el-skeleton v-for="n in 4" :key="n" :rows="1" animated />
        </div>

        <!-- 错误 -->
        <div v-else-if="state === 'error'" class="note err" role="alert">
          <el-icon class="ico"><WarningFilled /></el-icon>
          <div class="note-body">
            <b>{{ errorText }}</b>
            <span>本地后端未启动或连接失败。请双击「启动.bat」拉起服务后重试。</span>
            <div><el-button size="small" @click="load">重新加载</el-button></div>
          </div>
        </div>

        <!-- 数据 -->
        <template v-else>
          <div v-if="items.length === 0" class="empty">
            <el-icon class="ico-lg"><Collection /></el-icon>
            <b>知识库还是空的</b>
            <p>上传的资料会自动切块并建立索引，之后在主题创作中可被检索引用。</p>
            <el-button type="primary" size="small" @click="openPicker">上传第一份资料</el-button>
          </div>

          <div v-else class="card list-card">
            <div class="card-head">
              <h3>已入库资料</h3>
              <span class="sub">{{ countText }}</span>
              <span class="right small muted">
                共 {{ total }} 份 · {{ chunkTotal }} 个分块
              </span>
            </div>
            <table class="tbl">
              <thead>
                <tr>
                  <th style="width: 46%">资料</th>
                  <th style="width: 12%">分块数</th>
                  <th style="width: 22%">索引状态</th>
                  <th class="col-hide">入库时间</th>
                  <th class="num">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in items" :key="row.source_id">
                  <td>
                    <div class="t-name">
                      <el-icon class="src-ico" aria-hidden="true"><Document /></el-icon>
                      <span :title="knowledgeDisplayName(row)">{{ knowledgeDisplayName(row) }}</span>
                    </div>
                    <div class="t-sub">
                      {{ row.size != null ? formatFileSize(row.size) : '体积未知' }}
                      <template v-if="row.parse_status">
                        · 解析状态 {{ parseStatusTag(row.parse_status).label }}
                      </template>
                    </div>
                  </td>
                  <td>
                    <span class="small">{{ formatChunkCount(row.chunk_count) }}</span>
                  </td>
                  <td>
                    <el-tag size="small" :type="indexStatusTag(row.index_status).type" effect="plain">
                      {{ indexStatusTag(row.index_status).label }}
                    </el-tag>
                    <div
                      v-if="indexStatusDetail(row)"
                      class="status-detail xs"
                      :class="{ 'is-err': row.index_status === 'failed' }"
                    >
                      {{ indexStatusDetail(row) }}
                    </div>
                  </td>
                  <td class="col-hide nowrap muted xs">{{ formatDateTime(row.created_at) }}</td>
                  <td>
                    <div class="row-acts">
                      <el-button
                        size="small"
                        :loading="reindexingId === row.source_id"
                        :disabled="reindexing || deleting"
                        @click="reindexOne(row)"
                      >
                        重建索引
                      </el-button>
                      <el-button
                        size="small"
                        type="danger"
                        plain
                        :disabled="reindexing"
                        @click="askDelete(row)"
                      >
                        删除
                      </el-button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>

            <div v-if="total > limit" class="pager">
              <span class="small muted">{{ rangeText }}</span>
              <div class="right">
                <el-button size="small" :disabled="offset === 0" @click="goPage(offset - limit)">
                  上一页
                </el-button>
                <span class="xs muted">第 {{ curPage }} / {{ totalPages }} 页</span>
                <el-button
                  size="small"
                  :disabled="offset + limit >= total"
                  @click="goPage(offset + limit)"
                >
                  下一页
                </el-button>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- 删除确认：明示连带删除的分块，避免误删长期资料 -->
    <el-dialog v-model="deleteDialog" title="删除知识库资料" width="520px" append-to-body>
      <div class="del-body">
        <p class="del-title">将删除：{{ deleteTarget ? knowledgeDisplayName(deleteTarget) : '' }}</p>
        <p class="small muted">
          该资料的文档记录与 {{ deleteTarget?.chunk_count ?? 0 }} 个分块会一并删除，删除后无法恢复；
          已发出的创作任务不受影响。
        </p>
        <div class="warnline">
          <el-icon class="ico"><WarningFilled /></el-icon>
          <span>这是真正的删除（不是回收站留痕），请确认不再需要这份资料。</span>
        </div>
      </div>
      <template #footer>
        <el-button @click="deleteDialog = false">取消</el-button>
        <el-button type="danger" :loading="deleting" @click="confirmDelete">确认删除</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Collection,
  Document,
  Refresh,
  Upload,
  WarningFilled
} from '@element-plus/icons-vue'
import {
  BackendUnavailableError,
  deleteKnowledgeSource,
  listKnowledgeSources,
  reindexKnowledge,
  uploadKnowledgeSource,
  type KnowledgeSourceItem
} from '../api/client'
import {
  ALLOWED_SUFFIXES,
  formatFileSize,
  parseStatusTag,
  validateUploadFile
} from '../utils/analysisMeta'
import {
  formatChunkCount,
  indexStatusDetail,
  indexStatusTag,
  knowledgeDisplayName
} from '../utils/knowledgeMeta'
import { formatDateTime } from '../utils/taskMeta'

type State = 'loading' | 'ready' | 'error'

// 分块参数与分析管线同一套（backend/app/analysis/chunking.py），页面上如实说明，
// 让用户知道「分块数」是怎么来的，也避免两套参数看花眼。
const chunkTarget = 1200
const chunkMax = 1800
const LIMIT = 20

const items = ref<KnowledgeSourceItem[]>([])
const total = ref(0)
const limit = ref(LIMIT)
const offset = ref(0)
const state = ref<State>('loading')
const errorText = ref('')

const fileRef = ref<HTMLInputElement | null>(null)
const dragging = ref(false)
const uploading = ref(false)
const uploadPercent = ref(0)
const uploadName = ref('')
const rejectNote = ref('')

const reindexing = ref(false)
const reindexingId = ref<number | null>(null)

const deleteDialog = ref(false)
const deleting = ref(false)
const deleteTarget = ref<KnowledgeSourceItem | null>(null)

const acceptAttr = computed(() => ALLOWED_SUFFIXES.join(','))

const chunkTotal = computed(() =>
  items.value.reduce((sum, row) => sum + (row.chunk_count || 0), 0)
)
const countText = computed(() => `共 ${total.value} 条`)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / limit.value)))
const curPage = computed(() => Math.floor(offset.value / limit.value) + 1)
const rangeText = computed(() => {
  if (total.value === 0) return '显示 0 条'
  const start = offset.value + 1
  const end = offset.value + items.value.length
  return `显示 ${start}–${end} 条，共 ${total.value} 条`
})

/** 最近一次上传的失败提示：失败可见但清空后不长期占位。 */
const lastFailure = ref<{ name: string; reason: string } | null>(null)

async function load(): Promise<void> {
  state.value = 'loading'
  try {
    const res = await listKnowledgeSources({ limit: limit.value, offset: offset.value })
    items.value = res.items
    total.value = res.total
    limit.value = res.limit
    offset.value = res.offset
    state.value = 'ready'
  } catch (err) {
    items.value = []
    total.value = 0
    state.value = 'error'
    errorText.value =
      err instanceof BackendUnavailableError ? '后端未启动，无法读取知识库' : '知识库读取失败'
  }
}

function openPicker(): void {
  if (uploading.value) return
  fileRef.value?.click()
}

function onDragOver(): void {
  if (!uploading.value) dragging.value = true
}

function onPick(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) void upload(file)
}

function onDrop(event: DragEvent): void {
  dragging.value = false
  if (uploading.value) return
  const file = event.dataTransfer?.files?.[0]
  if (file) void upload(file)
}

async function upload(file: File): Promise<void> {
  rejectNote.value = ''
  lastFailure.value = null
  const invalid = validateUploadFile(file.name, file.size)
  if (invalid) {
    rejectNote.value = invalid
    return
  }

  uploading.value = true
  uploadPercent.value = 0
  uploadName.value = file.name
  try {
    const res = await uploadKnowledgeSource(file, (percent) => {
      uploadPercent.value = percent
    })
    if (res.message) {
      lastFailure.value = { name: knowledgeDisplayName(res.item), reason: res.message }
    } else {
      ElMessage.success(`已入库：${knowledgeDisplayName(res.item)}`)
    }
    offset.value = 0
    await load()
  } catch (err) {
    rejectNote.value =
      err instanceof BackendUnavailableError
        ? '后端未启动，无法上传；请先拉起本地服务'
        : (err as Error).message || '上传失败'
  } finally {
    uploading.value = false
    uploadPercent.value = 0
    uploadName.value = ''
  }
}

async function reindexOne(row: KnowledgeSourceItem): Promise<void> {
  reindexingId.value = row.source_id
  try {
    const res = await reindexKnowledge(row.source_id)
    const entry = res.items[0]
    if (entry && entry.index_status === 'failed') {
      ElMessage.warning(`重建索引失败：${entry.message || '原因未记录'}`)
    } else {
      ElMessage.success('索引已重建')
    }
    await load()
  } catch (err) {
    ElMessage.error(err instanceof BackendUnavailableError ? '后端未启动' : '重建索引失败')
  } finally {
    reindexingId.value = null
  }
}

async function reindexAll(): Promise<void> {
  reindexing.value = true
  try {
    const res = await reindexKnowledge()
    const failed = res.items.filter((entry) => entry.index_status === 'failed').length
    if (failed > 0) {
      ElMessage.warning(`重建完成：${res.total - failed} 份成功，${failed} 份失败（原因见清单）`)
    } else {
      ElMessage.success(`重建完成：${res.total} 份资料已重新入库`)
    }
    await load()
  } catch (err) {
    ElMessage.error(err instanceof BackendUnavailableError ? '后端未启动' : '重建索引失败')
  } finally {
    reindexing.value = false
  }
}

function askDelete(row: KnowledgeSourceItem): void {
  deleteTarget.value = row
  deleteDialog.value = true
}

async function confirmDelete(): Promise<void> {
  const target = deleteTarget.value
  if (!target) return
  deleting.value = true
  try {
    const res = await deleteKnowledgeSource(target.source_id)
    ElMessage.success(`已删除，同时清掉 ${res.deleted_chunk_count} 个分块`)
    deleteDialog.value = false
    deleteTarget.value = null
    // 删掉本页最后一条时回退一页，避免停在空页
    if (items.value.length === 1 && offset.value >= limit.value) {
      offset.value -= limit.value
    }
    await load()
  } catch (err) {
    ElMessage.error(err instanceof BackendUnavailableError ? '后端未启动' : '删除失败')
  } finally {
    deleting.value = false
  }
}

function goPage(newOffset: number): void {
  if (newOffset < 0 || newOffset >= total.value + limit.value) return
  offset.value = newOffset
  void load()
}

onMounted(load)
</script>

<style scoped>
.upload-card {
  margin-bottom: var(--sp-4);
}
.drop {
  cursor: pointer;
}
.drop.is-drag {
  border-color: var(--brand-500);
  background: var(--brand-50);
}
.drop.is-busy {
  cursor: progress;
  opacity: 0.72;
}
.drop:focus-visible {
  outline: 2px solid var(--brand-500);
  outline-offset: 2px;
}
.file-input {
  display: none;
}

.up-progress {
  margin-top: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.up-progress .bar {
  height: 4px;
  border-radius: var(--r-pill);
  background: var(--line-1);
  overflow: hidden;
}
.up-progress .bar > i {
  display: block;
  height: 100%;
  background: var(--brand-500);
  transition: width 0.2s ease;
}

.list-loading {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.list-card {
  padding-bottom: var(--sp-2);
}
.list-card :deep(.tbl th:first-child),
.list-card :deep(.tbl td:first-child) {
  padding-left: var(--sp-4);
}
.list-card :deep(.tbl th:last-child),
.list-card :deep(.tbl td:last-child) {
  padding-right: var(--sp-4);
}

.t-name {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-sm);
  color: var(--text-1);
  font-weight: 600;
  min-width: 0;
}
.t-name span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.src-ico {
  color: var(--text-3);
  flex: none;
}
.t-sub {
  margin-top: 2px;
  padding-left: 22px;
  font-size: var(--fs-xs);
  color: var(--text-3);
}

.status-detail {
  margin-top: 4px;
  line-height: 1.5;
  color: var(--text-3);
  max-width: 260px;
}
.status-detail.is-err {
  color: var(--err-fg);
}

.row-acts {
  display: flex;
  gap: var(--sp-2);
  justify-content: flex-end;
}

.pager {
  display: flex;
  align-items: center;
  padding: var(--sp-3) var(--sp-4);
  border-top: 1px solid var(--line-1);
}
.pager .right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.del-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.del-title {
  margin: 0;
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text-1);
}
.warnline {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-2);
  padding: var(--sp-3);
  border-radius: var(--r-sm);
  background: var(--warn-bg);
  border: 1px solid var(--warn-line);
  color: var(--warn-fg);
  font-size: var(--fs-xs);
  line-height: 1.6;
}

.nowrap {
  white-space: nowrap;
}

@media (max-width: 960px) {
  .col-hide {
    display: none;
  }
}
</style>

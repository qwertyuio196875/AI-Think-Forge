<template>
  <section class="view" aria-label="任务历史">
    <header class="view-head">
      <div class="head-row">
        <div class="head-title">
          <h1>任务历史</h1>
          <p>任务、对话、方案与待确认事项全程持久化；关闭工作台不等于从头再来</p>
        </div>
        <div class="head-actions">
          <el-button size="small" :icon="Download" @click="exportUnavailable">导出列表</el-button>
          <el-button size="small" :icon="Refresh" :loading="state === 'loading'" @click="reload">刷新</el-button>
        </div>
      </div>
    </header>

    <div class="view-body">
      <div class="wrap wrap--wide">
        <!-- 工具条：真实计数 tabs + 搜索 + 计数文案 -->
        <div class="toolbar">
          <div class="tabs" role="tablist" aria-label="任务筛选">
            <button
              v-for="t in tabs"
              :key="t.key"
              type="button"
              class="tab"
              role="tab"
              :aria-selected="t.key === tab"
              :class="{ 'is-active': t.key === tab }"
              @click="switchTab(t.key)"
            >
              {{ t.label }}<span v-if="t.countText" class="tab-count">{{ t.countText }}</span>
            </button>
          </div>
          <el-input
            v-model="search"
            class="search"
            clearable
            placeholder="按任务名搜索本页"
            aria-label="搜索任务（仅过滤当前页）"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <span class="small muted">{{ countText }}</span>
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
            <div><el-button size="small" @click="reload">重新加载</el-button></div>
          </div>
        </div>

        <!-- 数据：表格 + 分页（或空态） -->
        <template v-else>
          <div v-if="visibleRows.length === 0" class="empty">
            <el-icon class="ico-lg"><Delete v-if="tab === 'trash'" /><Clock v-else /></el-icon>
            <b>{{ emptyTitle }}</b>
            <p>{{ emptyText }}</p>
            <el-button v-if="search.trim()" size="small" @click="search = ''">清除搜索</el-button>
            <el-button v-else-if="tab === 'trash'" size="small" @click="switchTab('all')">查看全部任务</el-button>
            <el-button v-else-if="total === 0" type="primary" size="small" @click="goCreate">去发起主题创作</el-button>
          </div>

          <table v-else class="tbl">
            <thead>
              <tr>
                <th style="width: 40%">任务</th>
                <th class="col-hide">类型</th>
                <th style="width: 15%">状态</th>
                <th class="col-hide" style="width: 12%">进度</th>
                <th class="col-hide">更新</th>
                <th class="num">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in visibleRows" :key="row.id">
                <td>
                  <div class="t-name">
                    <button type="button" @click="open(row)">{{ row.title || '未命名任务' }}</button>
                  </div>
                  <div class="t-sub">第 {{ row.rounds }} 轮 · {{ row.dialogue_messages }} 条对话</div>
                </td>
                <td class="col-hide">
                  <el-tag size="small" type="info" effect="plain">{{ kindLabel(row.kind) }}</el-tag>
                </td>
                <td>
                  <span class="st"><i class="tf-dot" :class="statusInfo(row.status).dot"></i>{{ statusInfo(row.status).label }}</span>
                </td>
                <td class="col-hide"><span class="small muted">{{ row.rounds }} 轮</span></td>
                <td class="col-hide nowrap muted xs">{{ formatDateTime(row.updated_at) }}</td>
                <td>
                  <div class="row-acts">
                    <el-button
                      v-if="row.kind === 'creation' && row.status !== 'deleted'"
                      size="small"
                      type="primary"
                      plain
                      @click="open(row)"
                    >
                      {{ row.status === 'in_progress' ? '继续' : '打开' }}
                    </el-button>
                    <el-button v-else size="small" @click="open(row)">
                      {{ row.kind === 'analysis' ? '打开' : '查看' }}
                    </el-button>

                    <el-button
                      v-if="row.status === 'in_progress'"
                      size="small"
                      :loading="busyId === row.id"
                      @click="mark(row, 'completed')"
                    >
                      标记完成
                    </el-button>
                    <el-button
                      v-else-if="row.status === 'completed'"
                      size="small"
                      :loading="busyId === row.id"
                      @click="mark(row, 'in_progress')"
                    >
                      重新打开
                    </el-button>

                    <el-button
                      v-if="row.status !== 'deleted'"
                      size="small"
                      type="danger"
                      plain
                      @click="askDelete(row)"
                    >
                      删除
                    </el-button>
                    <span v-else class="xs muted">已删除 · 留痕</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>

          <div v-if="total > limit" class="pager">
            <span class="small muted">{{ rangeText }}</span>
            <div class="right">
              <el-button size="small" :disabled="offset === 0" @click="goPage(offset - limit)">上一页</el-button>
              <span class="xs muted">第 {{ curPage }} / {{ totalPages }} 页</span>
              <el-button size="small" :disabled="offset + limit >= total" @click="goPage(offset + limit)">下一页</el-button>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- 删除确认弹层：明示影响范围 -->
    <el-dialog v-model="deleteDialog" title="删除任务" width="560px" append-to-body>
      <div class="del-body">
        <p class="del-title">将删除：{{ impact?.title || '未命名任务' }}</p>
        <p class="small muted">{{ impact?.summary }}</p>
        <dl class="del-grid">
          <div><dt>对话</dt><dd>{{ impact?.dialogue_messages ?? 0 }} 条 · {{ impact?.rounds ?? 0 }} 轮</dd></div>
          <div><dt>结构化方案</dt><dd>{{ impact?.plans ?? 0 }} 份（修订记录 {{ impact?.plan_revisions ?? 0 }} 条）</dd></div>
          <div><dt>待确认事项</dt><dd>{{ impact?.open_items ?? 0 }} 条</dd></div>
          <div><dt>成品文件</dt><dd>{{ impact?.deliverable_files ?? 0 }} 个</dd></div>
        </dl>
        <div class="warnline">
          <el-icon class="ico"><WarningFilled /></el-icon>
          <span>删除为软删除：对话、方案与版本记录一条不删，任务改为「已删除」留痕，可在「回收站」视图回看。</span>
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
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Clock, Delete, Download, Refresh, Search, WarningFilled } from '@element-plus/icons-vue'
import {
  BackendUnavailableError,
  deleteTask,
  getDeletionImpact,
  listHistory,
  setTaskStatus,
  type DeletionImpact,
  type HistoryCounts,
  type HistoryItem,
  type TaskKind,
  type TaskStatus
} from '../api/client'
import { formatDateTime, kindLabel } from '../utils/taskMeta'
import { statusFromTask } from '../utils/resumeMeta'

type TabKey = 'all' | 'creation' | 'analysis' | 'trash'
type State = 'loading' | 'ready' | 'error'

const router = useRouter()
const LIMIT = 20

const rows = ref<HistoryItem[]>([])
const total = ref(0)
const limit = ref(LIMIT)
const offset = ref(0)
const counts = ref<HistoryCounts>({ all: 0, creation: 0, analysis: 0 })
const state = ref<State>('loading')
const errorText = ref('')

const tab = ref<TabKey>('all')
const search = ref('')
const busyId = ref<number | null>(null)

const deleteDialog = ref(false)
const deleting = ref(false)
const impact = ref<DeletionImpact | null>(null)
const deleteTarget = ref<HistoryItem | null>(null)

const tabs = computed(() => {
  const c = counts.value
  return [
    { key: 'all' as TabKey, label: '全部任务', countText: String(c.all) },
    { key: 'creation' as TabKey, label: '主题创作', countText: String(c.creation) },
    { key: 'analysis' as TabKey, label: '资料分析', countText: String(c.analysis) },
    { key: 'trash' as TabKey, label: '回收站', countText: '' }
  ]
})

const filteredRows = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return rows.value
  return rows.value.filter((r) => (r.title || '未命名任务').toLowerCase().includes(q))
})
const visibleRows = computed(() => filteredRows.value)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / limit.value)))
const curPage = computed(() => Math.floor(offset.value / limit.value) + 1)
const rangeText = computed(() => {
  if (total.value === 0) return '显示 0 条'
  const start = offset.value + 1
  const end = offset.value + rows.value.length
  return `显示 ${start}–${end} 条，共 ${total.value} 条`
})
const countText = computed(() => {
  if (state.value !== 'ready') return ''
  if (search.value.trim()) return `本页匹配 ${filteredRows.value.length} / ${rows.value.length} 条`
  return `共 ${total.value} 条`
})

const emptyTitle = computed(() => {
  if (tab.value === 'trash') return '回收站为空'
  if (search.value.trim()) return '没有匹配的任务'
  if (tab.value === 'creation') return '还没有主题创作任务'
  if (tab.value === 'analysis') return '还没有资料分析任务'
  return '还没有任务'
})
const emptyText = computed(() => {
  if (tab.value === 'trash')
    return '删除的任务在这里留痕；对话与方案仍保留，可随时回看。'
  if (search.value.trim()) return '换个关键词试试，或清除搜索查看全部任务。'
  if (tab.value === 'analysis') return '资料分析功能将在 TB-7 接入。'
  return '到「主题创作」用一句话发起，拷问进度会自动保存。'
})

function statusInfo(status: TaskStatus): { label: string; dot: string } {
  return statusFromTask(status)
}

async function load(): Promise<void> {
  state.value = 'loading'
  try {
    const res = await listHistory(queryFor(tab.value))
    rows.value = res.items
    total.value = res.total
    limit.value = res.limit
    offset.value = res.offset
    counts.value = res.counts
    state.value = 'ready'
  } catch (err) {
    rows.value = []
    total.value = 0
    counts.value = { all: 0, creation: 0, analysis: 0 }
    state.value = 'error'
    errorText.value = err instanceof BackendUnavailableError ? '后端未启动，无法读取任务历史' : '任务历史读取失败'
  }
}

function queryFor(t: TabKey): { kind?: TaskKind; status?: TaskStatus; limit: number; offset: number } {
  const base = { limit: limit.value, offset: offset.value }
  if (t === 'creation') return { kind: 'creation', ...base }
  if (t === 'analysis') return { kind: 'analysis', ...base }
  if (t === 'trash') return { status: 'deleted', ...base }
  return base
}

async function reload(): Promise<void> {
  await load()
}

function switchTab(t: TabKey): void {
  if (tab.value === t) return
  tab.value = t
  offset.value = 0
  search.value = ''
  load()
}

async function goPage(newOffset: number): Promise<void> {
  if (newOffset < 0 || newOffset >= total.value + limit.value) return
  offset.value = newOffset
  search.value = ''
  await load()
}

async function open(row: HistoryItem): Promise<void> {
  if (row.kind === 'creation') {
    // 续作跳转：把任务 id 交给创作页，由它拉取 history 详情按 awaiting 落在正确一步
    router.push(`/creation?task=${row.id}`)
  } else {
    router.push('/analysis')
    ElMessage.info('资料分析的打开与续作将在 TB-7 接入；该任务已记录在历史')
  }
}

async function mark(row: HistoryItem, next: 'in_progress' | 'completed'): Promise<void> {
  busyId.value = row.id
  try {
    const t = await setTaskStatus(row.id, next)
    // 就地更新该行状态，避免整表重拉闪动
    rows.value = rows.value.map((r) => (r.id === t.id ? { ...r, status: t.status, updated_at: t.updated_at } : r))
    ElMessage.success(next === 'completed' ? '已标记为已完成' : '已重新打开')
  } catch (err) {
    ElMessage.error(describe(err, '状态迁移'))
  } finally {
    busyId.value = null
  }
}

async function askDelete(row: HistoryItem): Promise<void> {
  try {
    impact.value = await getDeletionImpact(row.id)
    deleteTarget.value = row
    deleteDialog.value = true
  } catch (err) {
    ElMessage.error(describe(err, '获取影响范围'))
  }
}

async function confirmDelete(): Promise<void> {
  const target = deleteTarget.value
  if (!target || deleting.value) return
  deleting.value = true
  try {
    const res = await deleteTask(target.id, true)
    deleteDialog.value = false
    ElMessage.success(res.already_deleted ? '该任务此前已删除（留痕保持）' : '已删除 · 数据留痕，可在回收站查看')
    await load()
  } catch (err) {
    ElMessage.error(describe(err, '删除'))
  } finally {
    deleting.value = false
  }
}

function goCreate(): void {
  router.push('/creation')
}

function exportUnavailable(): void {
  ElMessage.info('后端尚未提供导出接口，列表导出暂不可用')
}

function describe(err: unknown, action: string): string {
  if (err instanceof BackendUnavailableError) return `后端未启动，${action}失败`
  const msg = (err as Error).message || ''
  if (msg.includes('404')) return '对应的任务不存在或已被清理'
  if (msg.includes('409')) return '该操作不被允许（如已删除任务不可再变更状态）'
  return `${action}失败：${msg}`
}

onMounted(load)
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  margin-bottom: var(--sp-4);
  flex-wrap: wrap;
}
.tabs {
  display: flex;
  gap: var(--sp-1);
  padding: var(--sp-1);
  background: var(--bg-sunken);
  border-radius: var(--r-sm);
  width: max-content;
}
.tab {
  border: 0;
  background: none;
  padding: 5px var(--sp-3);
  border-radius: var(--r-xs);
  font-size: var(--fs-sm);
  color: var(--text-2);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.tab:hover {
  color: var(--text-1);
}
.tab.is-active {
  background: var(--bg-surface);
  color: var(--text-1);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(20, 28, 46, 0.08);
}
.tab-count {
  font-size: var(--fs-xs);
  color: var(--text-3);
  background: var(--bg-sunken);
  border-radius: var(--r-pill);
  padding: 0 6px;
}
.tab.is-active .tab-count {
  background: var(--brand-50);
  color: var(--brand-600);
}
.search {
  flex: 1;
  min-width: 180px;
  max-width: 320px;
}
.list-loading {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  padding: var(--sp-4) 0;
}
.num {
  text-align: right;
}
.t-name {
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text-1);
}
.t-name button {
  border: 0;
  background: none;
  padding: 0;
  font: inherit;
  color: inherit;
  text-align: left;
  max-width: 420px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}
.t-name button:hover {
  color: var(--brand-600);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.t-sub {
  font-size: var(--fs-xs);
  color: var(--text-3);
  margin-top: 2px;
}
.st {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  white-space: nowrap;
}
.nowrap {
  white-space: nowrap;
}
.row-acts {
  display: flex;
  gap: var(--sp-1);
  justify-content: flex-end;
  flex-wrap: wrap;
}
.pager {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin-top: var(--sp-4);
  font-size: var(--fs-xs);
  color: var(--text-3);
}
.pager .right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

/* 删除弹层 */
.del-title {
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text-1);
  margin: 0 0 var(--sp-1);
}
.del-body > .small {
  line-height: 1.6;
  margin-bottom: var(--sp-4);
}
.del-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--sp-2) var(--sp-5);
  margin: 0;
  padding: var(--sp-3) var(--sp-4);
  border: 1px solid var(--line-1);
  border-radius: var(--r-md);
  background: var(--bg-sunken);
}
.del-grid div {
  display: flex;
  gap: var(--sp-2);
  justify-content: space-between;
  font-size: var(--fs-sm);
}
.del-grid dt {
  color: var(--text-3);
}
.del-grid dd {
  margin: 0;
  color: var(--text-1);
  font-weight: 500;
}
.warnline {
  display: flex;
  gap: var(--sp-2);
  align-items: flex-start;
  color: var(--warn-fg);
  font-size: var(--fs-sm);
  background: var(--warn-bg);
  border: 1px solid var(--warn-line);
  border-radius: var(--r-sm);
  padding: var(--sp-3);
  margin-top: var(--sp-4);
  line-height: 1.55;
}
.warnline .ico {
  margin-top: 2px;
  flex: none;
}

@media (max-width: 960px) {
  .row-acts {
    justify-content: flex-start;
  }
}
@media (max-width: 820px) {
  .col-hide {
    display: none;
  }
  .t-name button {
    max-width: 200px;
  }
}
</style>

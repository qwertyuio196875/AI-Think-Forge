<template>
  <div class="shell" :class="{ rail: collapsed }">
    <!-- ============ 左侧栏 ============ -->
    <aside class="sidebar">
      <!-- A2：全站唯一折叠控件位于 .side-head 右端 -->
      <div class="side-head">
        <!-- A1：折叠态下品牌标记即展开控件（button 语义 / aria-label / 焦点环 / 键盘可触发） -->
        <button
          class="mark"
          type="button"
          aria-label="展开侧栏"
          :aria-expanded="!collapsed"
          :aria-hidden="collapsed ? undefined : 'true'"
          :tabindex="collapsed ? 0 : -1"
          @click="expandRail"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.9"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M3.5 8.5 12 4l8.5 4.5v7L12 20l-8.5-4.5z" />
            <path d="M3.5 8.5 12 13l8.5-4.5M12 13v7" />
          </svg>
        </button>

        <div class="wordmark">
          <b>ThinkForge</b>
          <span>阅读与创作工作台</span>
        </div>

        <button
          class="rail-toggle"
          type="button"
          title="折叠 / 展开侧栏"
          aria-label="折叠或展开侧栏"
          :aria-expanded="!collapsed"
          @click="toggleRail"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.7"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M15 5 9 12l6 7" />
          </svg>
        </button>
      </div>

      <el-menu
        class="nav-menu"
        :default-active="activeRoute"
        :collapse="collapsed"
        :collapse-transition="false"
        router
      >
        <el-menu-item index="/creation">
          <el-icon><EditPen /></el-icon>
          <template #title>主题创作<span v-if="counts.creation" class="nav-count">{{ counts.creation }}</span></template>
        </el-menu-item>
        <el-menu-item index="/analysis">
          <el-icon><Document /></el-icon>
          <template #title>资料分析<span v-if="counts.analysis" class="nav-count">{{ counts.analysis }}</span></template>
        </el-menu-item>
        <el-menu-item index="/history">
          <el-icon><Clock /></el-icon>
          <template #title>任务历史</template>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <template #title>设置</template>
        </el-menu-item>
      </el-menu>

      <!-- 最近任务：读真实历史（最近 5 条），点击续作 / 打开 -->
      <div class="side-block">
        <div class="side-block-head">
          <h2>最近任务</h2>
        </div>
        <div v-if="recent.length" class="side-task-list">
          <button
            v-for="it in recent"
            :key="it.id"
            class="task-item"
            type="button"
            @click="clickRecent(it)"
          >
            <div class="t-top">
              <i class="tf-dot" :class="statusInfo(it.status).dot"></i>
              <span class="t-name">{{ it.title || '未命名任务' }}</span>
            </div>
            <div class="t-meta">第 {{ it.rounds }} 轮 · {{ it.dialogue_messages }} 条 · {{ relTime(it.updated_at) }}</div>
          </button>
        </div>
        <p v-else class="side-empty">
          {{ backend === 'down' ? '后端未启动，暂无法加载最近任务。' : '还没有任务，到「主题创作」发起一条。' }}
        </p>
      </div>

      <!-- 侧栏脚部：真实运行环境信息（地址 / 隐私边界），额度等属后续工单 -->
      <div class="side-foot">
        <div class="env-row">
          <i
            class="tf-dot"
            :class="{
              'tf-dot--ok': backend === 'ok',
              'tf-dot--err': backend === 'down'
            }"
          ></i>
          <span>本地服务</span>
          <span class="mono">127.0.0.1:8720</span>
          <span class="env-state">{{ backendLabel }}</span>
        </div>
        <div class="env-row">
          <el-icon class="env-ico"><Lock /></el-icon>
          <span>仅监听本机回环 · 数据不出机（除调用云端模型）</span>
        </div>
        <div class="budget">
          <div class="budget-line">额度 · <b>暂无数据</b></div>
          <div class="bar"><i style="width: 0"></i></div>
          <div class="budget-sub">无额度统计接口，未伪造数字（属后续工单）</div>
        </div>
      </div>
    </aside>

    <!-- ============ 主列 ============ -->
    <main class="main">
      <div class="content-area">
        <router-view />
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Clock, Document, EditPen, Lock, Setting } from '@element-plus/icons-vue'
import { checkHealth, listHistory, type HistoryCounts, type HistoryItem } from '../api/client'
import { statusFromTask } from '../utils/resumeMeta'

const route = useRoute()
const router = useRouter()

// 侧栏高亮跟随当前路由（/creation、/analysis、/history、/settings）。
const activeRoute = computed(() => route.path)

// A1/A2：折叠态。全站仅此处一份状态，驱动 .side-head 折叠控件与品牌标记同步。
const collapsed = ref(false)

function toggleRail(): void {
  collapsed.value = !collapsed.value
}

function expandRail(): void {
  if (collapsed.value) collapsed.value = false
}

// 后端健康状态：检查中 / 正常 / 未启动。复用 client 的 BackendUnavailableError 归类。
type BackendState = 'checking' | 'ok' | 'down'
const backend = ref<BackendState>('checking')
const backendLabel = computed(
  () =>
    ({ checking: '检测中…', ok: '正常', down: '未启动' })[backend.value]
)

// 最近任务 + 导航徽标分计数（一次 GET /history 拿齐）。
const recent = ref<HistoryItem[]>([])
const counts = ref<HistoryCounts>({ all: 0, creation: 0, analysis: 0 })

function statusInfo(status: HistoryItem['status']) {
  return statusFromTask(status)
}

function relTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `今天 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  if (diff < 172800) return '昨天'
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日`
}

async function loadRecent(): Promise<void> {
  try {
    const res = await listHistory({ limit: 5 })
    recent.value = res.items
    counts.value = res.counts
  } catch {
    recent.value = []
    counts.value = { all: 0, creation: 0, analysis: 0 }
  }
}

function clickRecent(item: HistoryItem): void {
  if (item.kind === 'creation') router.push(`/creation?task=${item.id}`)
  else router.push('/analysis')
}

// 窄屏自动收为图标栏，保证内容区不被挤压；
// 真正的离屏抽屉（遮罩 + 浮层）成本高，留待后续工单实现（见报告遗留点）。
function applyResponsive(): void {
  if (window.innerWidth <= 760) collapsed.value = true
}

// 进入各视图时刷新最近任务（本地单用户，一次 limit=5 的 GET 足够轻）。
watch(() => route.path, loadRecent)

onMounted(() => {
  applyResponsive()
  window.addEventListener('resize', applyResponsive)
  checkHealth()
    .then(() => {
      backend.value = 'ok'
    })
    .catch(() => {
      backend.value = 'down'
    })
    .finally(loadRecent)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', applyResponsive)
})
</script>

<style scoped>
/* 三栏壳（对齐原型 .shell）：左栏宽走 --side-w，rail 态收为图标栏 */
.shell {
  display: grid;
  grid-template-columns: var(--side-w) minmax(0, 1fr);
  height: 100vh;
}
.shell.rail {
  --side-w: 64px;
}

/* 左侧栏 */
.sidebar {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--bg-surface);
  border-right: 1px solid var(--line-1);
  overflow: hidden;
}

.side-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-4) var(--sp-4) var(--sp-3);
}

/* 品牌标记：折叠态即展开控件 */
.mark {
  width: 28px;
  height: 28px;
  flex: none;
  border: 0;
  padding: 0;
  border-radius: var(--r-sm);
  background: var(--brand-500);
  color: #fff;
  display: grid;
  place-items: center;
  cursor: default;
}
.mark svg {
  width: 16px;
  height: 16px;
}
.shell.rail .mark {
  cursor: pointer;
}
.shell.rail .mark:hover {
  box-shadow: 0 0 0 3px var(--brand-50);
}
.shell.rail .mark:focus-visible {
  outline: 2px solid var(--brand-500);
  outline-offset: 2px;
  border-radius: var(--r-sm);
}

.wordmark {
  min-width: 0;
}
.wordmark b {
  display: block;
  font-size: var(--fs-lg);
  letter-spacing: 0.2px;
}
.wordmark span {
  display: block;
  font-size: var(--fs-xs);
  color: var(--text-3);
}

/* 折叠控件（A2）：右端对齐，唯一一处 */
.rail-toggle {
  margin-left: auto;
  border: 1px solid var(--line-1);
  background: var(--bg-surface);
  color: var(--text-3);
  width: 28px;
  height: 28px;
  border-radius: var(--r-sm);
  display: grid;
  place-items: center;
  flex: none;
}
.rail-toggle svg {
  width: 14px;
  height: 14px;
}
.rail-toggle:hover {
  color: var(--brand-500);
  border-color: var(--brand-200);
  background: var(--brand-50);
}

/* 导航：Element Plus 标准组件，主题由 token 继承 */
.nav-menu {
  border-right: none;
  background: transparent;
}
.nav-count {
  margin-left: 8px;
  font-size: var(--fs-xs);
  color: var(--text-3);
  background: var(--bg-sunken);
  border-radius: var(--r-pill);
  padding: 0 7px;
  font-weight: 400;
}
:deep(.el-menu-item.is-active) .nav-count {
  background: var(--bg-surface);
  color: var(--brand-600);
}

/* 最近任务骨架 */
.side-block {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: var(--sp-4) var(--sp-3) 0;
  border-top: 1px solid var(--line-1);
  margin-top: var(--sp-4);
}
.side-block-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 0 var(--sp-1) var(--sp-2);
}
.side-block-head h2 {
  margin: 0;
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--text-3);
  letter-spacing: 0.6px;
}
.side-empty {
  margin: 0;
  padding: var(--sp-3);
  font-size: var(--fs-xs);
  line-height: 1.6;
  color: var(--text-4);
  background: var(--bg-sunken);
  border-radius: var(--r-sm);
}

/* 最近任务列表（状态点 + 名称 + 元信息行，对齐原型 .task-item） */
.side-task-list {
  overflow: auto;
  min-height: 0;
  padding-bottom: var(--sp-2);
}
.task-item {
  display: block;
  width: 100%;
  text-align: left;
  border: 1px solid transparent;
  background: none;
  border-radius: var(--r-sm);
  padding: var(--sp-2);
  margin-bottom: 2px;
}
.task-item:hover {
  background: var(--bg-hover);
  border-color: var(--line-1);
}
.t-top {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.t-name {
  font-size: var(--fs-sm);
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
.t-meta {
  font-size: var(--fs-xs);
  color: var(--text-3);
  padding-left: 16px;
  margin-top: 2px;
}

/* 侧栏脚部：真实环境信息 */
.side-foot {
  border-top: 1px solid var(--line-1);
  padding: var(--sp-3) var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.env-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--text-3);
}
.env-row .mono {
  font-family: var(--font-mono);
  color: var(--text-2);
}
.env-state {
  margin-left: auto;
  color: var(--text-4);
}
.env-ico {
  font-size: 14px;
  color: var(--text-3);
}

/* 额度条：无数据时如实标注，进度条留空不伪造 */
.budget {
  font-size: var(--fs-xs);
  color: var(--text-3);
}
.budget-line b {
  color: var(--text-2);
  font-weight: 600;
}
.bar {
  height: 4px;
  border-radius: var(--r-pill);
  background: var(--line-1);
  overflow: hidden;
  margin-top: 5px;
}
.bar > i {
  display: block;
  height: 100%;
  border-radius: var(--r-pill);
  background: var(--brand-500);
  width: 0;
}
.budget-sub {
  margin-top: 3px;
  color: var(--text-4);
}

/* 主列 */
.main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}
.content-area {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* 折叠态：隐藏文字，仅留图标（导航由 el-menu :collapse 接管） */
.shell.rail .side-head {
  padding: var(--sp-3) var(--sp-2);
  justify-content: center;
}
.shell.rail .wordmark,
.shell.rail .rail-toggle,
.shell.rail .side-block,
.shell.rail .budget {
  display: none;
}
.shell.rail .side-foot {
  padding: var(--sp-3) 0;
  align-items: center;
}
.shell.rail .env-row {
  justify-content: center;
}
.shell.rail .env-row span {
  display: none;
}
.shell.rail .env-state {
  display: none;
}

/*
 * 响应式（≤760px）：本单以「窄屏自动收成图标栏」保证内容可用为先。
 * 原型在窄屏改为遮罩式离屏抽屉（浮层 + 遮罩 + 滚动锁定），实现成本高，
 * 由 JS 在挂载时自动 collapsed=true 兜底；离屏抽屉留待后续工单（见报告遗留点）。
 */
</style>

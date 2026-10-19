<template>
  <section class="view creation" aria-label="主题创作">
    <!-- 视图页眉：标题 + 新建任务 + 四步流程骨架 -->
    <header class="view-head">
      <div class="head-row">
        <div class="head-title">
          <h1>主题创作</h1>
          <p>把模糊想法经拷问收敛为确认后的结构化方案，再生成成品</p>
        </div>
        <div class="head-actions">
          <el-button type="primary" :loading="creating" @click="newTask">
            <el-icon class="ico"><Plus /></el-icon>
            <span>新建任务</span>
          </el-button>
        </div>
      </div>

      <ol class="steps" aria-label="任务流程">
        <li v-for="(s, i) in steps" :key="s.label" class="step">
          <span class="step-no">{{ i + 1 }}</span>
          <span class="step-txt"><b>{{ s.label }}</b><em>{{ s.note }}</em></span>
        </li>
      </ol>
    </header>

    <!-- 会话流区：本单呈现任务列表的真实状态（加载 / 错误 / 空 / 列表） -->
    <div class="thread">
      <section class="card">
        <div class="card-head">
          <h3>任务列表</h3>
          <span class="sub">状态每轮自动保存，重启后可继续</span>
          <span v-if="listState === 'ready'" class="right small muted">{{ items.length }} 条</span>
        </div>
        <div class="card-body">
          <!-- 加载中 -->
          <div v-if="listState === 'loading'" class="list-loading">
            <el-skeleton v-for="n in 3" :key="n" :rows="1" animated class="sk-row" />
          </div>

          <!-- 后端不可达 / 失败 -->
          <div v-else-if="listState === 'error'" class="note err" role="alert">
            <el-icon class="ico"><WarningFilled /></el-icon>
            <div class="note-body">
              <b>{{ listError }}</b>
              <span>本地后端未启动或连接失败。请双击「启动.bat」拉起服务后重试。</span>
              <el-button size="small" @click="loadTasks">重新加载</el-button>
            </div>
          </div>

          <!-- 空态 -->
          <div v-else-if="items.length === 0" class="empty">
            <el-icon class="ico-lg"><EditPen /></el-icon>
            <b>还没有创作任务</b>
            <p>从一句话想法、一段描述或一份资料起步。新建任务后，拷问对话将在后续工单接入。</p>
            <el-button type="primary" :loading="creating" @click="newTask">新建任务</el-button>
          </div>

          <!-- 列表 -->
          <ul v-else class="task-list">
            <li v-for="t in items" :key="t.id" class="task-item">
              <div class="t-top">
                <i class="tf-dot" :class="statusDotClass(t.status)"></i>
                <span class="t-name">{{ t.title || '未命名任务' }}</span>
                <el-tag size="small" type="info" effect="plain">{{ kindLabel(t.kind) }}</el-tag>
              </div>
              <div class="t-meta">
                {{ statusLabel(t.status) }} · 更新于 {{ formatDateTime(t.updated_at) }}
              </div>
            </li>
          </ul>
        </div>
      </section>
    </div>

    <!-- 底部输入胶囊：当前在问什么 / 已确定什么 / 还有什么未确定 —— 本单为信息骨架 + 空态 -->
    <footer class="composer">
      <div class="composer-inner">
        <div class="composer-state">
          <span class="cap">
            <i class="tf-dot"></i>当前在问什么：尚无进行中的拷问轮次
          </span>
          <span class="cap">已确定 <b>0</b> 项</span>
          <span class="cap">未确定 <b>0</b> 项</span>
        </div>
        <div class="pill">
          <textarea
            class="pill-input"
            rows="1"
            disabled
            placeholder="补充信息、提出修改意见，或直接回答本轮问题（拷问对话将在 TB-2 接入）"
          ></textarea>
          <button class="send" type="button" disabled aria-label="发送">
            <el-icon><Promotion /></el-icon>
          </button>
        </div>
        <div class="composer-hint">
          本单仅搭建输入胶囊的信息骨架与空态，真实拷问内容将在后续工单接入
        </div>
      </div>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { EditPen, Plus, Promotion, WarningFilled } from '@element-plus/icons-vue'
import { BackendUnavailableError, createTask, listTasks, type Task } from '../api/client'
import { formatDateTime, kindLabel, statusDotClass, statusLabel } from '../utils/taskMeta'

// 四步流程骨架（想法发起 → 拷问收敛 → 方案确认 → 生成成品）。
// 本单只呈现结构，真实进度由后续工单（拷问 TB-2 / 方案确认 TB-6 / 生成 TB-8）填充。
const steps = [
  { label: '想法发起', note: '新建任务即可起步' },
  { label: '拷问收敛', note: '未开始' },
  { label: '方案确认', note: '未开始' },
  { label: '生成成品', note: '未开始' }
]

type ListState = 'loading' | 'ready' | 'error'
const items = ref<Task[]>([])
const listState = ref<ListState>('loading')
const listError = ref('')
const creating = ref(false)

async function loadTasks(): Promise<void> {
  listState.value = 'loading'
  try {
    const res = await listTasks({ kind: 'creation' })
    items.value = res.items
    listState.value = 'ready'
  } catch (err) {
    items.value = []
    listState.value = 'error'
    listError.value =
      err instanceof BackendUnavailableError
        ? '后端未启动，无法加载任务列表'
        : '任务列表加载失败'
  }
}

async function newTask(): Promise<void> {
  creating.value = true
  try {
    const task = await createTask({ kind: 'creation' })
    items.value = [task, ...items.value]
    listState.value = 'ready'
    ElMessage.success('已新建任务')
  } catch (err) {
    listState.value = 'error'
    listError.value =
      err instanceof BackendUnavailableError ? '后端未启动，无法新建任务' : '新建任务失败'
    ElMessage.error('无法新建任务，请确认后端已启动')
  } finally {
    creating.value = false
  }
}

onMounted(loadTasks)
</script>

<style scoped>
/* 步骤条（结构骨架，无伪造进度） */
.steps {
  list-style: none;
  display: flex;
  align-items: stretch;
  gap: var(--sp-2);
  margin: 0;
  padding: var(--sp-2) 0 var(--sp-3);
  overflow-x: auto;
  scrollbar-width: none;
}
.steps::-webkit-scrollbar {
  display: none;
}
.step {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex: none;
}
.step + .step {
  padding-left: var(--sp-2);
}
.step + .step::before {
  content: "";
  width: 20px;
  height: 1px;
  background: var(--line-2);
  margin-right: var(--sp-2);
  flex: none;
}
.step-no {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  border: 1px solid var(--line-3);
  background: var(--bg-surface);
  color: var(--text-4);
  font-size: 11px;
  flex: none;
}
.step-txt b {
  display: block;
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--text-2);
  white-space: nowrap;
}
.step-txt em {
  display: block;
  font-style: normal;
  font-size: var(--fs-xs);
  color: var(--text-4);
  white-space: nowrap;
}

/* thread 内容（中间滚动区） */
.thread {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: var(--sp-6) var(--sp-5) var(--sp-10);
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
}
.thread > .card {
  width: 100%;
  max-width: var(--content-max);
  margin: 0 auto;
}

/* 任务列表 */
.task-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.task-item {
  border: 1px solid var(--line-1);
  border-radius: var(--r-md);
  padding: var(--sp-3) var(--sp-4);
  background: var(--bg-surface);
}
.task-item:hover {
  background: var(--bg-hover);
  border-color: var(--line-2);
}
.t-top {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.t-name {
  font-size: var(--fs-md);
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
  margin-top: 3px;
}

/* 加载骨架 */
.list-loading {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

/* 底部输入胶囊 */
.composer {
  border-top: 1px solid var(--line-1);
  background: var(--bg-surface);
  padding: var(--sp-3) var(--sp-6) var(--sp-5);
}
.composer-inner {
  max-width: var(--content-max);
  margin: 0 auto;
}
.composer-state {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  padding-bottom: var(--sp-2);
}
.pill {
  display: flex;
  align-items: flex-end;
  gap: var(--sp-2);
  border: 1px solid var(--line-2);
  border-radius: var(--r-pill);
  padding: 6px 6px 6px 14px;
  background: var(--bg-surface);
}
.pill:focus-within {
  border-color: var(--brand-500);
  box-shadow: 0 0 0 3px var(--brand-50);
}
.pill-input {
  flex: 1;
  min-width: 0;
  border: 0;
  background: none;
  resize: none;
  overflow: hidden;
  max-height: 120px;
  padding: 7px 0;
  font: inherit;
  font-size: var(--fs-md);
  line-height: 1.5;
  color: var(--text-1);
}
.pill-input:focus {
  outline: none;
}
.pill-input:disabled {
  color: var(--text-4);
  cursor: not-allowed;
}
.send {
  width: 32px;
  height: 32px;
  flex: none;
  border-radius: var(--r-pill);
  border: 1px solid var(--brand-500);
  background: var(--brand-500);
  color: #fff;
  display: grid;
  place-items: center;
}
.send:disabled {
  background: var(--line-2);
  border-color: var(--line-2);
  box-shadow: inset 0 0 0 1px var(--line-3);
  cursor: not-allowed;
}
.composer-hint {
  margin-top: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--text-4);
}

@media (max-width: 960px) {
  .composer {
    padding-left: var(--sp-4);
    padding-right: var(--sp-4);
  }
  .thread {
    padding: var(--sp-5) var(--sp-4) var(--sp-8);
  }
}
</style>

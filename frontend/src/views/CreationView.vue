<template>
  <section class="view creation" aria-label="主题创作">
    <!-- 视图页眉 -->
    <header class="view-head">
      <div class="head-row">
        <div class="head-title">
          <h1>{{ isChat ? activeTask?.title || '主题创作' : '主题创作' }}</h1>
          <p>{{ headSubtitle }}</p>
        </div>
        <div class="head-actions">
          <el-button v-if="isChat" :icon="ArrowLeft" @click="backToList">任务列表</el-button>
          <el-button v-else :icon="Refresh" :loading="listState === 'loading'" @click="loadTasks">刷新</el-button>
        </div>
      </div>

      <ol class="steps" aria-label="任务流程">
        <li v-for="s in steps" :key="s.label" class="step" :class="'is-' + s.state">
          <span class="step-ico">
            <el-icon v-if="s.state === 'done'"><Select /></el-icon>
            <template v-else>{{ s.no }}</template>
          </span>
          <span class="step-txt"><b>{{ s.label }}</b><em>{{ s.note }}</em></span>
        </li>
      </ol>
    </header>

    <!-- 会话流区 -->
    <div class="thread">
      <div class="thread-inner">
        <!-- ============ 列表模式：发起入口 + 任务列表 ============ -->
        <template v-if="!isChat">
          <div class="note info start-hint">
            <el-icon class="ico"><EditPen /></el-icon>
            <div class="note-body">
              <b>用一句话或一段描述发起主题创作</b>
              <span>在下方输入框写下想法并发送，系统会产出第一轮「前沿」问题；也可点选下方已有任务继续拷问。</span>
            </div>
          </div>

          <section class="card">
            <div class="card-head">
              <h3>主题创作任务</h3>
              <span class="sub">状态每轮自动保存，重启后可继续</span>
              <span v-if="listState === 'ready'" class="right small muted">{{ items.length }} 条</span>
            </div>
            <div class="card-body">
              <div v-if="listState === 'loading'" class="list-loading">
                <el-skeleton v-for="n in 3" :key="n" :rows="1" animated />
              </div>

              <div v-else-if="listState === 'error'" class="note err" role="alert">
                <el-icon class="ico"><WarningFilled /></el-icon>
                <div class="note-body">
                  <b>{{ listError }}</b>
                  <span>本地后端未启动或连接失败。请双击「启动.bat」拉起服务后重试。</span>
                  <div><el-button size="small" @click="loadTasks">重新加载</el-button></div>
                </div>
              </div>

              <div v-else-if="items.length === 0" class="empty">
                <el-icon class="ico-lg"><EditPen /></el-icon>
                <b>还没有创作任务</b>
                <p>在下方输入框写下想法并发送即可发起第一轮拷问。</p>
              </div>

              <ul v-else class="task-list">
                <li v-for="t in items" :key="t.id">
                  <button class="task-item" type="button" @click="openTask(t)">
                    <div class="t-top">
                      <i class="tf-dot" :class="statusDotClass(t.status)"></i>
                      <span class="t-name">{{ t.title || '未命名任务' }}</span>
                      <el-tag size="small" type="info" effect="plain">{{ statusLabel(t.status) }}</el-tag>
                    </div>
                    <div class="t-meta">更新于 {{ formatDateTime(t.updated_at) }} · 点开继续拷问</div>
                  </button>
                </li>
              </ul>
            </div>
          </section>
        </template>

        <!-- ============ 对话模式：对话流 + 当前轮问题卡片 ============ -->
        <template v-else>
          <div v-if="dialogueState === 'loading'" class="list-loading">
            <el-skeleton :rows="4" animated />
            <el-skeleton :rows="4" animated />
          </div>

          <div v-else-if="dialogueState === 'error'" class="note err" role="alert">
            <el-icon class="ico"><WarningFilled /></el-icon>
            <div class="note-body">
              <b>{{ dialogueError }}</b>
              <div class="err-acts">
                <el-button size="small" @click="reloadDialogue">重新加载</el-button>
                <el-button size="small" @click="backToList">返回列表</el-button>
              </div>
            </div>
          </div>

          <template v-else-if="dialogue">
            <!-- 种子输入（用户想法） -->
            <div v-if="dialogue.seed_input" class="msg-user">
              <div class="bubble"><p>{{ dialogue.seed_input }}</p></div>
              <div class="msg-meta"><span>想法发起</span></div>
            </div>

            <!-- 无轮次（历史空任务） -->
            <div
              v-if="dialogue.rounds.length === 0"
              class="note info"
            >
              <el-icon class="ico"><InfoFilled /></el-icon>
              <div class="note-body">
                <span>该任务还没有拷问轮次。返回列表，在输入框写一句想法即可发起第一轮。</span>
              </div>
            </div>

            <!-- 轮次 -->
            <div v-for="r in dialogue.rounds" :key="r.round_no" class="round">
              <div class="qhead">
                <h2>第 {{ r.round_no }} 轮 · 前沿问题</h2>
                <p>本轮只问前置条件已定的问题。每题附推荐答案，采纳或改写都行。</p>
                <el-tag
                  size="small"
                  :type="r.answers.length >= r.frontier.length ? 'success' : 'warning'"
                  effect="plain"
                >
                  已回答 {{ r.answers.length }} / {{ r.frontier.length }}
                </el-tag>
              </div>

              <div class="card qcards">
                <div
                  v-for="(q, qi) in r.frontier"
                  :key="qi"
                  class="qcard"
                  :class="{ 'is-done': qi < r.answers.length }"
                >
                  <div class="q-top">
                    <span class="q-no">Q{{ qi + 1 }}</span>
                    <div class="q-main">
                      <div class="q-text">{{ q.title }}</div>
                      <p class="q-body">{{ q.body }}</p>
                    </div>
                  </div>

                  <div class="q-rec">
                    <b>→ 推荐答案</b>
                    <p>{{ q.recommended_answer }}</p>
                  </div>

                  <!-- 作答入口（仅当前可答轮的未答题） -->
                  <div v-if="r === openRound" class="ans">
                    <textarea
                      v-model="drafts[qi]"
                      rows="2"
                      :aria-label="`第 ${r.round_no} 轮第 ${qi + 1} 题作答`"
                      placeholder="直接写你的答案，或点「采纳推荐答案」后修改"
                    ></textarea>
                    <div class="ans-actions">
                      <el-button size="small" type="primary" :icon="Select" @click="adopt(qi)">
                        采纳推荐答案
                      </el-button>
                    </div>
                  </div>

                  <!-- 已回答展示 -->
                  <div v-else-if="qi < r.answers.length" class="q-done">
                    <div class="row">
                      <el-icon class="ico ok"><CircleCheck /></el-icon>
                      <b>已回答 · Q{{ qi + 1 }}</b>
                    </div>
                    <p>{{ r.answers[qi] }}</p>
                  </div>
                </div>
              </div>

              <div v-if="r === openRound" class="round-foot">
                <el-button
                  type="primary"
                  :loading="submitting"
                  :disabled="!canSubmit"
                  @click="submitRound"
                >
                  提交本轮回答
                </el-button>
                <span class="xs muted">需回答全部 {{ r.frontier.length }} 个问题（数量须与问题一致）</span>
              </div>
            </div>

            <!-- 本轮答完后如实说明（不伪造下一轮） -->
            <div v-if="openRound === null && dialogue.rounds.length" class="note info">
              <el-icon class="ico"><InfoFilled /></el-icon>
              <div class="note-body">
                <b>本轮回答已记录</b>
                <span>
                  下一轮会基于你的回答重新计算前沿；结构化方案与方案确认将在后续工单接入。
                  本单不伪造后续轮次，也不提供确认或生成入口。
                </span>
              </div>
            </div>

            <!-- 结构化方案：占位（TB-3） -->
            <div class="card plan-card">
              <div class="card-head">
                <h3>结构化方案</h3>
                <span class="tag tag-sunken">占位 · 尚未生成</span>
              </div>
              <div class="card-body">
                <div class="plan-ph">
                  <b>方案在拷问收敛后生成</b>
                  <p>未经你显式确认，方案不会进入生成；这里只是结构占位，暂无可用内容与确认闸门。</p>
                </div>
              </div>
            </div>
          </template>
        </template>
      </div>
    </div>

    <!-- 底部输入胶囊：列表模式=发起想法；对话模式=派生信息骨架 -->
    <footer class="composer">
      <div class="composer-inner">
        <div class="composer-state">
          <span class="cap">
            <i class="tf-dot" :class="openRound ? 'tf-dot--run' : ''"></i>当前在问什么：{{ askText }}
          </span>
          <span class="cap">已确定 <b>{{ settledCount }}</b> 项</span>
          <span class="cap">
            <i class="tf-dot" :class="openCount ? 'tf-dot--warn' : 'tf-dot--ok'"></i>未确定
            <b>{{ openCount }}</b> 项
          </span>
        </div>

        <div class="pill">
          <textarea
            v-if="!isChat"
            class="pill-input"
            v-model="idea"
            rows="1"
            placeholder="用一句话或一段描述发起主题创作…（Enter 发送 · Shift + Enter 换行）"
            @keydown.enter.exact.prevent="startIdea"
          ></textarea>
          <textarea
            v-else
            class="pill-input"
            rows="1"
            disabled
            placeholder="补充信息与送入资料分析将在后续工单接入"
          ></textarea>
          <button
            class="send"
            type="button"
            :disabled="isChat || starting || !idea.trim()"
            aria-label="发送"
            @click="startIdea"
          >
            <el-icon><Promotion /></el-icon>
          </button>
        </div>

        <div class="composer-hint">
          {{ isChat ? '当前轮次的作答请在上方问题卡片中完成' : '输入想法并发送，即可发起第一轮拷问' }}
        </div>
      </div>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft,
  CircleCheck,
  EditPen,
  InfoFilled,
  Promotion,
  Refresh,
  Select,
  WarningFilled
} from '@element-plus/icons-vue'
import {
  BackendUnavailableError,
  getDialogue,
  listTasks,
  startGrillingTask,
  submitAnswers,
  type Dialogue,
  type Task
} from '../api/client'
import { formatDateTime, statusDotClass, statusLabel } from '../utils/taskMeta'

type ListState = 'loading' | 'ready' | 'error'
type ChatState = 'loading' | 'ready' | 'error'

const items = ref<Task[]>([])
const listState = ref<ListState>('loading')
const listError = ref('')

const view = ref<'list' | 'chat'>('list')
const activeTask = ref<Task | null>(null)
const dialogue = ref<Dialogue | null>(null)
const dialogueState = ref<ChatState>('ready')
const dialogueError = ref('')
const submitting = ref(false)

const idea = ref('')
const starting = ref(false)
const drafts = ref<string[]>([])

const isChat = computed(() => view.value === 'chat')

const openRound = computed(() => {
  const rs = dialogue.value?.rounds ?? []
  for (let i = rs.length - 1; i >= 0; i--) {
    const r = rs[i]
    if (r.frontier.length > 0 && r.answers.length < r.frontier.length) return r
  }
  return null
})

const canSubmit = computed(() => {
  const r = openRound.value
  if (!r) return false
  if (drafts.value.length !== r.frontier.length) return false
  return drafts.value.every((a) => a.trim().length > 0)
})

const settledCount = computed(() =>
  (dialogue.value?.rounds ?? []).reduce((n, r) => n + r.answers.length, 0)
)
const openCount = computed(() =>
  (dialogue.value?.rounds ?? []).reduce(
    (n, r) => n + Math.max(0, r.frontier.length - r.answers.length),
    0
  )
)

const askText = computed(() => {
  if (!isChat.value) return '选一个任务继续，或在下方输入想法发起'
  const r = openRound.value
  if (r) return `第 ${r.round_no} 轮 · ${r.frontier.length} 个前沿问题待答`
  const rs = dialogue.value?.rounds ?? []
  if (rs.length) {
    const last = rs[rs.length - 1]
    if (last.answers.length >= last.frontier.length)
      return `第 ${last.round_no} 轮已答完 · 等待下一轮重算`
  }
  return '尚无进行中的拷问轮次'
})

const headSubtitle = computed(() => {
  if (isChat.value) return '按轮次作答，每轮把当前可决的问题一次问完；系统查事实、决策归你'
  return '把模糊想法经拷问收敛为确认后的结构化方案，再生成成品'
})

const steps = computed(() => {
  const started = isChat.value && !!dialogue.value
  const r = openRound.value
  return [
    { no: 1, label: '想法发起', state: started ? 'done' : 'now', note: started ? '已发起' : '输入一句话开始' },
    {
      no: 2,
      label: '拷问收敛',
      state: started ? 'now' : 'todo',
      note: started && r ? `第 ${r.round_no} 轮 · ${r.frontier.length} 问待答` : started ? '本轮已答' : '未开始'
    },
    { no: 3, label: '方案确认', state: 'todo', note: '未开始' },
    { no: 4, label: '生成成品', state: 'todo', note: '未开始' }
  ]
})

function syncDrafts(d: Dialogue): void {
  const rs = d.rounds
  for (let i = rs.length - 1; i >= 0; i--) {
    if (rs[i].frontier.length > 0 && rs[i].answers.length < rs[i].frontier.length) {
      drafts.value = rs[i].frontier.map(() => '')
      return
    }
  }
  drafts.value = []
}

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
      err instanceof BackendUnavailableError ? '后端未启动，无法加载任务列表' : '任务列表加载失败'
  }
}

async function startIdea(): Promise<void> {
  const text = idea.value.trim()
  if (!text || starting.value) return
  starting.value = true
  try {
    const res = await startGrillingTask(text)
    // 用发起返回真实构造对话态（seed = 我发送的想法，round = 后端第一轮前沿）。
    const d: Dialogue = {
      task_id: res.task.id,
      seed_input: text,
      rounds: [{ ...res.round, answers: res.round.answers ?? [] }],
      messages: []
    }
    activeTask.value = res.task
    dialogue.value = d
    syncDrafts(d)
    view.value = 'chat'
    idea.value = ''
    ElMessage.success('已发起第一轮拷问')
  } catch (err) {
    ElMessage.error(describeStartError(err))
  } finally {
    starting.value = false
  }
}

function describeStartError(err: unknown): string {
  if (err instanceof BackendUnavailableError) return '后端未启动，无法发起拷问'
  const msg = (err as Error).message || ''
  if (msg.includes('502')) return '模型输出无法解析为前沿问题，请稍后重试或检查默认模型配置'
  return '发起失败：' + msg
}

async function openTask(t: Task): Promise<void> {
  activeTask.value = t
  dialogue.value = null
  view.value = 'chat'
  await reloadDialogue()
}

async function reloadDialogue(): Promise<void> {
  if (!activeTask.value) return
  dialogueState.value = 'loading'
  try {
    const d = await getDialogue(activeTask.value.id)
    dialogue.value = d
    syncDrafts(d)
    dialogueState.value = 'ready'
  } catch (err) {
    dialogue.value = null
    dialogueState.value = 'error'
    dialogueError.value =
      err instanceof BackendUnavailableError ? '后端未启动，无法读取对话' : '对话读取失败'
  }
}

function backToList(): void {
  view.value = 'list'
  activeTask.value = null
  dialogue.value = null
  drafts.value = []
  loadTasks()
}

function adopt(qi: number): void {
  const r = openRound.value
  if (!r || !r.frontier[qi]) return
  drafts.value = drafts.value.map((v, i) => (i === qi ? r.frontier[qi].recommended_answer : v))
}

async function submitRound(): Promise<void> {
  const r = openRound.value
  const task = activeTask.value
  if (!r || !task) return
  if (!canSubmit.value) {
    ElMessage.warning('请回答全部问题，或先点「采纳推荐答案」')
    return
  }
  submitting.value = true
  try {
    const d = await submitAnswers(task.id, r.round_no, drafts.value.map((a) => a.trim()))
    dialogue.value = d
    syncDrafts(d)
    ElMessage.success('本轮回答已提交')
  } catch (err) {
    ElMessage.error(describeSubmitError(err))
  } finally {
    submitting.value = false
  }
}

function describeSubmitError(err: unknown): string {
  if (err instanceof BackendUnavailableError) return '后端未启动，提交失败'
  const msg = (err as Error).message || ''
  if (msg.includes('422')) return '回答数量与问题数量不一致，请确认每题都作答'
  if (msg.includes('404')) return '该轮次不存在或尚无前沿问题'
  return '提交失败：' + msg
}

onMounted(loadTasks)
</script>

<style scoped>
/* 步骤条 */
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
.step-ico {
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
.step-ico .el-icon {
  font-size: 11px;
}
.step.is-done .step-ico {
  background: var(--ok-bg);
  border-color: var(--ok-line);
  color: var(--ok-fg);
}
.step.is-done .step-txt b {
  color: var(--text-2);
}
.step.is-now .step-ico {
  background: var(--brand-500);
  border-color: var(--brand-500);
  color: #fff;
}
.step.is-now .step-txt b {
  color: var(--brand-700);
  font-weight: 600;
}
.step.is-now .step-txt em {
  color: var(--brand-600);
}
.step-txt b {
  display: block;
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--text-3);
  white-space: nowrap;
}
.step-txt em {
  display: block;
  font-style: normal;
  font-size: var(--fs-xs);
  color: var(--text-4);
  white-space: nowrap;
}

/* thread 内容 */
.thread {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: var(--sp-6) var(--sp-5) var(--sp-10);
}
.thread-inner {
  max-width: var(--content-max);
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
}
.thread-inner > .card {
  width: 100%;
}

.start-hint .note-body b {
  color: var(--text-1);
}

/* 列表 */
.task-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.task-item {
  display: block;
  width: 100%;
  text-align: left;
  border: 1px solid var(--line-1);
  background: var(--bg-surface);
  border-radius: var(--r-md);
  padding: var(--sp-3) var(--sp-4);
}
.task-item:hover {
  background: var(--bg-hover);
  border-color: var(--brand-200);
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

.list-loading {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}
.err-acts {
  display: flex;
  gap: var(--sp-2);
}

/* 用户气泡 */
.msg-user {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: var(--sp-2);
}
.bubble {
  max-width: min(78%, 560px);
  background: var(--brand-50);
  border: 1px solid var(--brand-100);
  border-radius: var(--r-lg) var(--r-lg) var(--r-sm) var(--r-lg);
  padding: var(--sp-3) var(--sp-4);
}
.bubble p {
  font-size: var(--fs-md);
  color: var(--text-1);
  white-space: pre-wrap;
}
.msg-meta {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--text-4);
}

/* 轮次 / 问题卡片 */
.qhead {
  display: flex;
  align-items: baseline;
  gap: var(--sp-3);
  flex-wrap: wrap;
}
.qhead h2 {
  margin: 0;
  font-size: var(--fs-xl);
  font-weight: 600;
}
.qhead p {
  font-size: var(--fs-sm);
  color: var(--text-3);
  flex: 1;
  min-width: 200px;
}
.qcards {
  margin-top: var(--sp-3);
}
.qcard {
  padding: var(--sp-4) var(--sp-5);
  border-top: 1px solid var(--line-1);
}
.qcard:first-of-type {
  border-top: 0;
}
.qcard.is-done {
  background: #fcfdfe;
}
.q-top {
  display: flex;
  gap: var(--sp-3);
  align-items: flex-start;
}
.q-no {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--brand-600);
  background: var(--brand-50);
  border: 1px solid var(--brand-100);
  border-radius: var(--r-xs);
  padding: 1px 6px;
  flex: none;
  margin-top: 2px;
}
.q-main {
  min-width: 0;
}
.q-text {
  font-size: var(--fs-lg);
  font-weight: 600;
  line-height: 1.5;
  color: var(--text-1);
}
.q-body {
  margin: 3px 0 0;
  font-size: var(--fs-sm);
  color: var(--text-3);
  line-height: 1.6;
}
.q-rec {
  margin-top: var(--sp-3);
  border-left: 2px solid var(--brand-200);
  background: var(--bg-sunken);
  border-radius: 0 var(--r-sm) var(--r-sm) 0;
  padding: var(--sp-3);
}
.q-rec b {
  font-size: var(--fs-sm);
  color: var(--brand-700);
  font-weight: 600;
}
.q-rec p {
  font-size: var(--fs-sm);
  margin: 2px 0 0;
  color: var(--text-2);
  line-height: 1.6;
}
.ans {
  margin-top: var(--sp-3);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.ans textarea {
  width: 100%;
  min-height: 60px;
  resize: vertical;
  border: 1px solid var(--line-2);
  border-radius: var(--r-sm);
  padding: var(--sp-2) var(--sp-3);
  font: inherit;
  font-size: var(--fs-sm);
  line-height: 1.6;
  background: var(--bg-surface);
  color: var(--text-1);
}
.ans textarea::placeholder {
  color: var(--text-4);
}
.ans textarea:focus {
  outline: none;
  border-color: var(--brand-500);
  box-shadow: 0 0 0 3px var(--brand-50);
}
.ans-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.q-done {
  margin-top: var(--sp-3);
  padding: var(--sp-3);
  border: 1px solid var(--line-1);
  border-radius: var(--r-sm);
  background: var(--bg-sunken);
}
.q-done .row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.q-done .row b {
  font-size: var(--fs-sm);
  color: var(--text-1);
}
.q-done .ico.ok {
  color: var(--ok-fg);
}
.q-done p {
  font-size: var(--fs-sm);
  color: var(--text-2);
  margin: var(--sp-2) 0 0;
  line-height: 1.6;
  white-space: pre-wrap;
}
.round-foot {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
  margin-top: var(--sp-3);
}

/* 方案占位 */
.plan-card {
  border-color: var(--line-2);
}
.tag-sunken {
  display: inline-flex;
  align-items: center;
  padding: 2px 9px;
  border-radius: var(--r-pill);
  font-size: var(--fs-xs);
  border: 1px solid var(--line-1);
  background: var(--bg-sunken);
  color: var(--text-2);
}
.plan-ph {
  padding: var(--sp-3) var(--sp-4);
  border-radius: var(--r-md);
  background: var(--bg-sunken);
}
.plan-ph b {
  display: block;
  font-size: var(--fs-sm);
  color: var(--text-1);
}
.plan-ph p {
  font-size: var(--fs-sm);
  color: var(--text-3);
  margin: var(--sp-1) 0 0;
  line-height: 1.6;
}

/* 底部胶囊 */
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
.send:hover:not(:disabled) {
  background: var(--brand-600);
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
  .qcard {
    padding-left: var(--sp-4);
    padding-right: var(--sp-4);
  }
}
</style>

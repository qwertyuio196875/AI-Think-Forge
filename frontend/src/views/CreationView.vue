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
          <el-tag
            v-if="statusChip"
            size="small"
            :type="statusChip.type"
            effect="plain"
            class="status-chip"
          >
            <i class="tf-dot" :class="statusChip.dot"></i>{{ statusChip.label }}
          </el-tag>
          <el-button :icon="Plus" @click="newTask">新任务</el-button>
          <el-button v-if="isChat" :icon="ArrowLeft" @click="backToList">任务列表</el-button>
          <el-button v-else :icon="Refresh" :loading="listState === 'loading'" @click="loadTasks">
            刷新
          </el-button>
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
        <!-- ============ 列表模式 ============ -->
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

        <!-- ============ 对话模式 ============ -->
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
            <div v-if="dayLabel" class="day-sep">{{ dayLabel }}</div>

            <!-- 续作提示：仅当由历史 / 侧栏进入（带真实 awaiting）时显示 -->
            <div v-if="awaiting" class="note resume" :class="awaiting === 'deleted' ? 'warn' : 'info'">
              <el-icon class="ico"><InfoFilled /></el-icon>
              <div class="note-body">
                <b>续作 · {{ awaitingLabel(awaiting) }}</b>
                <span>{{ awaitingResumeHint(awaiting) }}</span>
              </div>
            </div>

            <!-- 种子输入（用户原始想法）——真实内容，不拆解成“目标/背景” -->
            <div v-if="dialogue.seed_input" class="msg-user">
              <div class="bubble"><p>{{ dialogue.seed_input }}</p></div>
              <div class="msg-meta"><span>想法发起</span></div>
            </div>

            <!-- 无轮次且无方案（历史空任务） -->
            <div v-if="dialogue.rounds.length === 0 && !plan" class="note info">
              <el-icon class="ico"><InfoFilled /></el-icon>
              <div class="note-body">
                <span>该任务还没有拷问轮次。点「新任务」或在输入框写一句想法即可发起第一轮。</span>
              </div>
            </div>

            <!-- 轮次：已答完的历史轮折叠，当前轮可作答 -->
            <template v-for="r in dialogue.rounds" :key="r.round_no">
              <div
                v-if="isAnsweredRound(r) && r !== openRound"
                class="qround"
                :class="{ 'is-open': isExpanded(r.round_no) }"
              >
                <button
                  type="button"
                  class="qround-head"
                  :aria-expanded="isExpanded(r.round_no) ? 'true' : 'false'"
                  @click="toggleRound(r.round_no)"
                >
                  <el-icon v-if="!skippedCount(r)" class="ico ok"><CircleCheck /></el-icon>
                  <el-icon v-else class="ico warn"><Warning /></el-icon>
                  <b>第 {{ r.round_no }} 轮 · {{ r.frontier.length }} 个问题 · 已定 {{ answeredCount(r) }} · 未定 {{ skippedCount(r) }}</b>
                  <el-icon class="chev"><ArrowRight /></el-icon>
                </button>
                <div v-show="isExpanded(r.round_no)" class="qround-body">
                  <div
                    v-for="(q, qi) in r.frontier"
                    :key="qi"
                    class="done-qa"
                    :class="{ 'is-skip': isSkipAnswer(r.answers[qi]) }"
                  >
                    <b>Q{{ qi + 1 }} · {{ q.title }}</b>
                    <span v-if="isSkipAnswer(r.answers[qi])" class="muted">
                      （暂时跳过 · 未定）该问题已进入待确认事项
                    </span>
                    <span v-else>{{ r.answers[qi] }}</span>
                  </div>
                </div>
              </div>

              <div v-else-if="r === openRound" class="round">
                <div class="qhead">
                  <h2>第 {{ r.round_no }} 轮 · 前沿问题</h2>
                  <p>本轮只问前置条件已定的问题。每题附推荐答案，可采纳、改写，或「暂时跳过」把该题留作待确认事项。</p>
                  <el-tag size="small" type="warning" effect="plain">共 {{ r.frontier.length }} 题待处理</el-tag>
                </div>

                <div class="card qcards">
                  <div
                    v-for="(q, qi) in r.frontier"
                    :key="qi"
                    class="qcard"
                    :class="{ 'is-skip': isSkipped(qi) }"
                  >
                    <div class="q-top">
                      <span class="q-no">Q{{ qi + 1 }}</span>
                      <div class="q-main">
                        <div class="q-text">{{ q.title }}</div>
                        <p class="q-body">{{ q.body }}</p>
                        <p v-if="q.why" class="q-why">为什么现在问：{{ q.why }}</p>
                      </div>
                    </div>

                    <div class="q-rec">
                      <b>→ 推荐答案</b>
                      <p>{{ q.recommended_answer }}</p>
                      <div v-if="q.alternatives && q.alternatives.length" class="alt-row">
                        <span class="alt-label">备选方向</span>
                        <button
                          v-for="(alt, ai) in q.alternatives"
                          :key="ai"
                          type="button"
                          class="alt"
                          @click="pickAlternative(qi, alt)"
                        >
                          {{ alt }}
                        </button>
                      </div>
                    </div>

                    <div v-if="isSkipped(qi)" class="ans ans-skipped">
                      <span class="skip-note">已标记「暂时跳过」—— 提交后该题保持未定，并进入待确认事项</span>
                      <div class="ans-actions">
                        <el-button size="small" @click="undoSkip(qi)">撤销跳过</el-button>
                      </div>
                    </div>
                    <div v-else class="ans">
                      <textarea
                        v-model="drafts[qi]"
                        rows="2"
                        :aria-label="`第 ${r.round_no} 轮第 ${qi + 1} 题作答`"
                        placeholder="直接写你的答案，或点「采纳推荐答案」/ 备选方向后修改"
                      ></textarea>
                      <div class="ans-actions">
                        <el-button size="small" type="primary" :icon="Select" @click="adopt(qi)">
                          采纳推荐答案
                        </el-button>
                        <el-button size="small" @click="skipQuestion(qi)">暂时跳过</el-button>
                      </div>
                    </div>
                  </div>
                </div>

                <div class="round-foot">
                  <el-button
                    type="primary"
                    :loading="submitting"
                    :disabled="!canSubmit"
                    @click="submitRound"
                  >
                    提交并推进
                  </el-button>
                  <el-button :loading="submitting" @click="submitSkipAll">整轮跳过</el-button>
                  <span class="xs muted">
                    每题作答或明确跳过后提交，据此计算下一轮或收敛；跳过项会进入待确认事项
                  </span>
                </div>
              </div>
            </template>

            <!-- 重载后已到“全答完但未推进”的兜底入口 -->
            <div v-if="showAdvance" class="round-advance">
              <el-button type="primary" :loading="advancing" @click="doAdvance">推进下一轮 / 收敛</el-button>
              <span class="xs muted">本轮已答完，据此重新计算前沿，或收敛为结构化方案</span>
            </div>

            <!-- 收敛 + 结构化方案 + 待确认事项 + 修订 + 确认闸门 -->
            <template v-if="plan">
              <div class="note info converge">
                <el-icon class="ico"><InfoFilled /></el-icon>
                <div class="note-body">
                  <b>拷问收敛，无下一轮</b>
                  <span>
                    关键问题已解决后主动收敛，不再为延续对话而提问；未确认的推测只作为待确认事项，不会写进成品。
                    请审查下方结构化方案，处置完待确认事项后再确认，才会进入生成。
                  </span>
                </div>
              </div>

              <div class="card plan-card" :class="{ 'is-locked': plan.status === 'confirmed' }">
                <div class="card-head">
                  <h3>结构化方案</h3>
                  <el-tag
                    size="small"
                    :type="plan.status === 'confirmed' ? 'success' : 'warning'"
                    effect="plain"
                  >
                    {{ plan.status === 'confirmed' ? '已确认 · ' + confirmedAt : '草稿 · 未确认，不会进入生成' }}
                  </el-tag>
                  <span class="sub">由第 {{ plan.round_no }} 轮问答生成<template v-if="revisions.length"> · 已修订 {{ revisions.length }} 次</template></span>
                </div>

                <div class="card-body">
                  <!-- 最近一次修订的变更摘要 -->
                  <div v-if="latestRevision" class="plan-changed">
                    <b>本次修订</b>
                    <span class="ch-inst">「{{ latestRevision.instruction }}」· {{ formatDateTime(latestRevision.created_at) }}</span>
                    <div class="ch-list">
                      <span v-for="(c, ci) in latestRevision.change_summary" :key="ci" class="ch" :class="'ch-' + c.kind">
                        {{ changeKindText(c.kind) }} · {{ c.heading }}
                      </span>
                      <span v-if="!latestRevision.change_summary.length" class="ch muted">未检测到章节级变化</span>
                    </div>
                  </div>

                  <div v-if="planSectioned?.title" class="plan-title">{{ planSectioned.title }}</div>

                  <div v-if="planSectioned && planSectioned.sections.length" class="plan-grid">
                    <div v-for="(sec, si) in planSectioned.sections" :key="si" class="fld">
                      <h4 v-if="sec.heading">{{ sec.heading }}</h4>
                      <!-- 方案正文为后端真实 Markdown，转义后渲染 -->
                      <div class="fld-body" v-html="sec.body"></div>
                    </div>
                  </div>
                  <div v-else class="fld-body muted">方案正文为空。</div>

                  <!-- 待确认事项：真实清单 + 处置 -->
                  <div class="plan-pending">
                    <h4>
                      <el-icon class="ico"><Warning /></el-icon>待确认事项
                      <span v-if="openItemCount" class="pend-count">{{ openItemCount }} 项未处置</span>
                    </h4>
                    <p>系统标记的未定关键信息（多来自「暂时跳过」）。你不回应不等于同意；全部处置后才能确认方案。</p>
                    <div v-if="!openItems.length" class="pend-empty">暂无待确认事项</div>
                    <ul v-else class="pend-list">
                      <li
                        v-for="it in openItems"
                        :key="it.id"
                        class="pend"
                        :class="{ 'is-decided': it.status !== 'open' }"
                      >
                        <div class="pend-grow">
                          <div class="pend-name">{{ it.text }}</div>
                          <div class="pend-sub">来源：第 {{ it.round_no }} 轮 · 暂时跳过</div>
                        </div>
                        <template v-if="it.status === 'open'">
                          <el-button
                            size="small"
                            type="primary"
                            :loading="resolvingId === it.id"
                            @click="doResolve(it, 'confirmed')"
                          >
                            采纳推荐并定下
                          </el-button>
                          <el-button
                            size="small"
                            :loading="resolvingId === it.id"
                            @click="doResolve(it, 'dismissed')"
                          >
                            驳回
                          </el-button>
                          <el-tag size="small" type="warning" effect="plain">未定</el-tag>
                        </template>
                        <el-tag
                          v-else
                          size="small"
                          :type="it.status === 'confirmed' ? 'success' : 'info'"
                          effect="plain"
                        >
                          {{ it.status === 'confirmed' ? '已确认' : '已驳回'
                          }}{{ it.resolved_at ? ' · ' + formatDateTime(it.resolved_at) : '' }}
                        </el-tag>
                      </li>
                    </ul>
                  </div>

                  <!-- 对话式修订 -->
                  <div class="plan-revise">
                    <h4>继续对话修订方案</h4>
                    <textarea
                      v-model="reviseText"
                      rows="2"
                      placeholder="例如：把目标读者改成初级工程师；补充一节「常见问题」"
                    ></textarea>
                    <div class="revise-actions">
                      <el-button
                        size="small"
                        type="primary"
                        :loading="revising"
                        :disabled="!reviseText.trim()"
                        @click="doRevise"
                      >
                        提交修订
                      </el-button>
                      <span class="xs muted">修订会更新正文并把方案带回草稿态，需再次确认</span>
                    </div>
                  </div>

                  <!-- 修订历史（旧版本留痕） -->
                  <div v-if="revisions.length" class="revisions">
                    <button
                      type="button"
                      class="rev-toggle"
                      :aria-expanded="showRevisions ? 'true' : 'false'"
                      @click="showRevisions = !showRevisions"
                    >
                      <el-icon class="chev" :class="{ 'is-open': showRevisions }"><ArrowRight /></el-icon>
                      <b>修订历史 · {{ revisions.length }} 条</b>
                    </button>
                    <ol v-show="showRevisions" class="rev-list">
                      <li v-for="(rev, ri) in revisions" :key="rev.id" class="rev-item">
                        <div class="rev-head">第 {{ ri + 1 }} 次修订 · {{ formatDateTime(rev.created_at) }}</div>
                        <div class="rev-inst">对方案说：{{ rev.instruction }}</div>
                        <div class="rev-changes">
                          <span v-for="(c, ci) in rev.change_summary" :key="ci" class="ch" :class="'ch-' + c.kind">
                            {{ changeKindText(c.kind) }} · {{ c.heading }}
                          </span>
                          <span v-if="!rev.change_summary.length" class="ch muted">无章节级变化</span>
                        </div>
                      </li>
                    </ol>
                  </div>
                </div>

                <div class="plan-foot">
                  <span v-if="plan.status === 'draft'" class="gate" :class="{ 'gate-block': openItemCount > 0 }">
                    <el-icon class="ico lock"><Lock /></el-icon>
                    <span>{{ draftGateText }}</span>
                  </span>
                  <span v-else class="ok-note">
                    <el-icon class="ico"><CircleCheck /></el-icon>
                    <span>已于 {{ confirmedAt }} 由你显式确认</span>
                  </span>

                  <el-button
                    v-if="plan.status === 'draft'"
                    type="primary"
                    size="large"
                    :icon="Select"
                    :disabled="!canConfirm"
                    @click="confirmDialog = true"
                  >
                    确认方案
                  </el-button>

                  <p class="hint">{{ generationHint }}</p>
                </div>
              </div>

              <!-- 生成面板：确认且无未处置项后真实可用（Word 成品） -->
              <GenerationPanel
                :task-id="plan.task_id"
                :locked="panelLocked"
                :lock-reason="panelLockReason"
              />
            </template>
          </template>
        </template>
      </div>
    </div>

    <!-- 底部输入胶囊：列表模式=发起想法；对话模式=真实派生的信息骨架 -->
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
            ref="ideaRef"
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

        <div v-if="!isChat" class="composer-opts">
          <ModelSelect v-model="ideaProviderId" label="模型" default-label="跟随默认模型" />
          <span class="xs muted">{{ ideaProviderHint }}</span>
        </div>

        <div class="composer-hint">
          {{ isChat ? '当前轮次的作答请在上方问题卡片中完成' : '输入想法并发送，即可发起第一轮拷问' }}
        </div>
      </div>
    </footer>

    <!-- 确认方案弹层 -->
    <el-dialog v-model="confirmDialog" title="确认结构化方案" width="520px" append-to-body>
      <div class="confirm-body">
        <p>确认后才会进入生成阶段。你确认的是当前这份结构化方案；未经确认的推测不会写进任何文件。</p>
        <div class="cf-item">
          <b>方案来源轮次</b>
          <span>第 {{ plan?.round_no }} 轮问答之后收敛生成</span>
        </div>
        <div class="cf-item">
          <b>待确认事项</b>
          <span>{{ openItemCount ? `还有 ${openItemCount} 项未处置` : '全部已处置' }}</span>
        </div>
        <div class="warnline">
          <el-icon class="ico"><Warning /></el-icon>
          <span>方案确认是进入生成的唯一闸门。确认前不会生成任何成品；确认后可继续对话进行修订。</span>
        </div>
      </div>
      <template #footer>
        <el-button @click="confirmDialog = false">再想想</el-button>
        <el-button type="primary" :loading="confirming" @click="doConfirm">确认方案</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft,
  ArrowRight,
  CircleCheck,
  EditPen,
  InfoFilled,
  Lock,
  Plus,
  Promotion,
  Refresh,
  Select,
  Warning,
  WarningFilled
} from '@element-plus/icons-vue'
import {
  advanceGrilling,
  BackendUnavailableError,
  confirmPlan as confirmPlanApi,
  getDialogue,
  getHistoryDetail,
  getPlan,
  isApiStatus,
  isSkipAnswer,
  listOpenItems,
  listRevisions,
  listTasks,
  resolveOpenItem,
  revisePlan,
  startGrillingTask,
  submitAnswers,
  type Dialogue,
  type FrontierRound,
  type OpenItem,
  type Plan,
  type PlanChangeKind,
  type PlanRevision,
  type ResolveStatus,
  type ResumeNext,
  type Task
} from '../api/client'
import { splitPlanSections } from '../utils/markdown'
import { formatDateTime, statusDotClass, statusLabel } from '../utils/taskMeta'
import { awaitingLabel, awaitingResumeHint } from '../utils/resumeMeta'
import GenerationPanel from '../components/GenerationPanel.vue'
import ModelSelect from '../components/ModelSelect.vue'

type ListState = 'loading' | 'ready' | 'error'
type ChatState = 'loading' | 'ready' | 'error'

const route = useRoute()

const items = ref<Task[]>([])
const listState = ref<ListState>('loading')
const listError = ref('')

const view = ref<'list' | 'chat'>('list')
const activeTask = ref<Task | null>(null)
const dialogue = ref<Dialogue | null>(null)
const dialogueState = ref<ChatState>('ready')
const dialogueError = ref('')
const plan = ref<Plan | null>(null)
const openItems = ref<OpenItem[]>([])
const revisions = ref<PlanRevision[]>([])
const showRevisions = ref(false)
const revising = ref(false)
const reviseText = ref('')
const resolvingId = ref<number | null>(null)

const submitting = ref(false)
const advancing = ref(false)
const confirming = ref(false)
const confirmDialog = ref(false)
const expandedIds = ref<number[]>([])

const idea = ref('')
const starting = ref(false)
/** 发起创作时选定的任务级模型覆盖：null = 跟随默认档位（拷问 / 方案 / 修订都按它解析）。 */
const ideaProviderId = ref<number | null>(null)
const drafts = ref<string[]>([])
const skippedQ = ref<number[]>([])
const ideaRef = ref<HTMLTextAreaElement | null>(null)

const awaiting = ref<ResumeNext | null>(null)

const isChat = computed(() => view.value === 'chat')

const openRound = computed<FrontierRound | null>(() => {
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
  // 每题要么明确跳过，要么有非空作答
  return r.frontier.every((_, qi) => skippedQ.value.includes(qi) || (drafts.value[qi] || '').trim().length > 0)
})

const showAdvance = computed(
  () =>
    dialogueState.value === 'ready' &&
    !!dialogue.value &&
    !openRound.value &&
    !plan.value &&
    dialogue.value.rounds.length > 0
)

const settledCount = computed(() => {
  const answered = (dialogue.value?.rounds ?? []).reduce(
    (n, r) => n + r.answers.filter((a) => !isSkipAnswer(a)).length,
    0
  )
  return answered + openItems.value.filter((i) => i.status === 'confirmed').length
})
const openCount = computed(() => {
  const unresolved = openItems.value.filter((i) => i.status === 'open').length
  const r = openRound.value
  const unansweredActive = r ? Math.max(0, r.frontier.length - r.answers.length) : 0
  return unresolved + unansweredActive
})

const askText = computed(() => {
  if (!isChat.value) return '选一个任务继续，或在下方输入想法发起'
  const r = openRound.value
  if (r) return `第 ${r.round_no} 轮 · ${r.frontier.length} 个前沿问题待答`
  if (plan.value) return `已收敛 · 第 ${plan.value.round_no} 轮之后`
  const rs = dialogue.value?.rounds ?? []
  if (rs.length) {
    const last = rs[rs.length - 1]
    if (last.answers.length >= last.frontier.length) return '本轮已答完 · 等待推进下一轮'
  }
  return '尚无进行中的拷问轮次'
})

const headSubtitle = computed(() => {
  if (isChat.value && activeTask.value) {
    return `创建于 ${formatDateTime(activeTask.value.created_at)} · 状态每轮自动保存，重启后可继续`
  }
  return '把模糊想法经拷问收敛为确认后的结构化方案，再生成成品'
})

/** 模型选择器旁的一句说明：只讲已实现的覆盖范围。 */
const ideaProviderHint = computed(() =>
  ideaProviderId.value === null
    ? '不指定模型：拷问、方案与修订按默认档位解析'
    : '本任务全程用这一个配置：拷问、方案与修订都读它，不改变设置页的全局默认'
)

type ChipType = 'primary' | 'success' | 'info' | 'warning'
const statusChip = computed<{ label: string; type: ChipType; dot: string } | null>(() => {
  if (!isChat.value || !dialogue.value) return null
  if (plan.value?.status === 'confirmed')
    return { label: '已确认', type: 'success', dot: 'tf-dot--ok' }
  if (plan.value) return { label: '已收敛 · 待确认', type: 'warning', dot: 'tf-dot--warn' }
  if (openRound.value)
    return { label: `拷问进行中 · 第 ${openRound.value.round_no} 轮`, type: 'primary', dot: 'tf-dot--run' }
  const rs = dialogue.value.rounds
  if (rs.length && rs.every((r) => r.frontier.length > 0 && r.answers.length >= r.frontier.length))
    return { label: '已回答 · 待推进', type: 'info', dot: '' }
  return null
})

const planSectioned = computed(() => (plan.value ? splitPlanSections(plan.value.content_md) : null))

const confirmedAt = computed(() => (plan.value?.confirmed_at ? formatDateTime(plan.value.confirmed_at) : ''))

const openItemCount = computed(() => openItems.value.filter((i) => i.status === 'open').length)
const canConfirm = computed(() => plan.value?.status === 'draft' && openItemCount.value === 0)
const latestRevision = computed<PlanRevision | null>(() =>
  revisions.value.length ? revisions.value[revisions.value.length - 1] : null
)

const draftGateText = computed(() =>
  openItemCount.value > 0
    ? `还有 ${openItemCount.value} 项待确认事项未处置 · 全部处置后才能确认方案`
    : '方案确认是进入生成的唯一闸门 · 未经确认的推测不会写进任何文件'
)
const generationHint = computed(() => {
  if (!plan.value) return '尚无结构化方案'
  if (plan.value.status === 'draft')
    return openItemCount.value > 0
      ? `仍有 ${openItemCount.value} 项待确认事项未处置；处置并确认后才会进入生成`
      : '确认前不会生成任何成品；方案的修改通过上方「继续对话修订方案」进行'
  if (openItemCount.value > 0) return `仍有 ${openItemCount.value} 项待确认事项未处置 · 生成闸门关闭`
  return '方案已确认 · 可在下方「生成面板」产出 Word 或单文件 HTML 演示成品'
})

const panelLocked = computed(
  () => !(plan.value?.status === 'confirmed' && openItemCount.value === 0)
)
const panelLockReason = computed(() => {
  if (!plan.value) return '尚未生成结构化方案。'
  if (plan.value.status !== 'confirmed')
    return '方案还是草稿，确认后才进入生成；未经确认的推测不会写进任何文件。'
  if (openItemCount.value > 0)
    return `还有 ${openItemCount.value} 项待确认事项未处置，请先在上方处置（确认或驳回）后再生成。`
  return ''
})

function changeKindText(kind: PlanChangeKind): string {
  return kind === 'added' ? '新增' : kind === 'removed' ? '删除' : kind === 'modified' ? '修改' : kind
}
function answeredCount(r: FrontierRound): number {
  return r.answers.filter((a) => !isSkipAnswer(a)).length
}
function skippedCount(r: FrontierRound): number {
  return r.answers.filter((a) => isSkipAnswer(a)).length
}
function isSkipped(qi: number): boolean {
  return skippedQ.value.includes(qi)
}

const dayLabel = computed(() => {
  const iso = activeTask.value?.created_at
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : `${d.getMonth() + 1} 月 ${d.getDate()} 日`
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
      note: !started
        ? '未开始'
        : plan.value
          ? '已收敛 · 待确认'
          : r
            ? `第 ${r.round_no} 轮 · ${r.frontier.length} 问待答`
            : '本轮已答'
    },
    {
      no: 3,
      label: '方案确认',
      state: plan.value?.status === 'confirmed' ? 'done' : plan.value ? 'now' : 'todo',
      note: plan.value?.status === 'confirmed' ? '已确认' : plan.value ? '等待你显式批准' : '未开始'
    },
    {
      no: 4,
      label: '生成成品',
      state: plan.value?.status === 'confirmed' ? 'now' : 'todo',
      note: plan.value?.status === 'confirmed' ? 'Word / 单文件 HTML 均可' : '未开始'
    }
  ]
})

function isAnsweredRound(r: FrontierRound): boolean {
  return r.frontier.length > 0 && r.answers.length >= r.frontier.length
}
function isExpanded(n: number): boolean {
  return expandedIds.value.includes(n)
}
function toggleRound(n: number): void {
  expandedIds.value = expandedIds.value.includes(n)
    ? expandedIds.value.filter((x) => x !== n)
    : [...expandedIds.value, n]
}

function syncDrafts(d: Dialogue): void {
  const rs = d.rounds
  for (let i = rs.length - 1; i >= 0; i--) {
    if (rs[i].frontier.length > 0 && rs[i].answers.length < rs[i].frontier.length) {
      drafts.value = rs[i].frontier.map(() => '')
      skippedQ.value = []
      return
    }
  }
  drafts.value = []
  skippedQ.value = []
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
    const res = await startGrillingTask(text, ideaProviderId.value)
    const d: Dialogue = {
      task_id: res.task.id,
      seed_input: text,
      rounds: [{ ...res.round, answers: res.round.answers ?? [] }],
      messages: []
    }
    activeTask.value = res.task
    dialogue.value = d
    plan.value = null
    openItems.value = []
    revisions.value = []
    showRevisions.value = false
    reviseText.value = ''
    expandedIds.value = []
    awaiting.value = null
    syncDrafts(d)
    view.value = 'chat'
    idea.value = ''
    ElMessage.success('已发起第一轮拷问')
  } catch (err) {
    ElMessage.error(describeFlowError(err, '发起'))
  } finally {
    starting.value = false
  }
}

async function openTask(t: Task): Promise<void> {
  activeTask.value = t
  dialogue.value = null
  plan.value = null
  openItems.value = []
  revisions.value = []
  showRevisions.value = false
  reviseText.value = ''
  expandedIds.value = []
  awaiting.value = null
  view.value = 'chat'
  await reloadDialogue()
}

/** 从历史 / 侧栏进入：用 history 详情一次复原对话、方案与待确认事项，并显示「停在哪一步」。 */
async function resumeByTaskId(id: number): Promise<void> {
  activeTask.value = null
  dialogue.value = null
  plan.value = null
  openItems.value = []
  revisions.value = []
  showRevisions.value = false
  expandedIds.value = []
  dialogueState.value = 'loading'
  view.value = 'chat'
  try {
    const d = await getHistoryDetail(id)
    activeTask.value = d.task
    dialogue.value = d.dialogue
    plan.value = d.plan
    openItems.value = d.open_items
    awaiting.value = d.awaiting
    syncDrafts(d.dialogue)
    revisions.value = d.plan ? (await listRevisions(id)).items : []
    dialogueState.value = 'ready'
  } catch (err) {
    dialogue.value = null
    plan.value = null
    awaiting.value = null
    dialogueState.value = 'error'
    dialogueError.value =
      err instanceof BackendUnavailableError ? '后端未启动，无法打开任务' : '打开任务失败'
  }
}

async function reloadDialogue(): Promise<void> {
  if (!activeTask.value) return
  dialogueState.value = 'loading'
  try {
    await refreshChat()
    dialogueState.value = 'ready'
  } catch (err) {
    dialogue.value = null
    plan.value = null
    openItems.value = []
    revisions.value = []
    dialogueState.value = 'error'
    dialogueError.value =
      err instanceof BackendUnavailableError ? '后端未启动，无法读取对话' : '对话读取失败'
  }
}

/** 拉齐一次任务的权威态：对话 + 待确认事项 + 方案 + 修订历史。 */
async function refreshChat(): Promise<void> {
  const task = activeTask.value
  if (!task) return
  const [d, oi] = await Promise.all([getDialogue(task.id), listOpenItems(task.id)])
  dialogue.value = d
  syncDrafts(d)
  openItems.value = oi.items
  plan.value = await fetchPlan(task.id)
  revisions.value = plan.value ? (await listRevisions(task.id)).items : []
}

/** 取方案：404 视为「尚无方案」（正常草稿态），其它错误也按无方案处理（对话已成功加载）。 */
async function fetchPlan(taskId: number): Promise<Plan | null> {
  try {
    return await getPlan(taskId)
  } catch (err) {
    if (err instanceof BackendUnavailableError) throw err
    return null
  }
}

function backToList(): void {
  view.value = 'list'
  activeTask.value = null
  dialogue.value = null
  plan.value = null
  openItems.value = []
  revisions.value = []
  showRevisions.value = false
  reviseText.value = ''
  drafts.value = []
  skippedQ.value = []
  expandedIds.value = []
  awaiting.value = null
  loadTasks()
}

async function newTask(): Promise<void> {
  view.value = 'list'
  activeTask.value = null
  dialogue.value = null
  plan.value = null
  openItems.value = []
  revisions.value = []
  showRevisions.value = false
  reviseText.value = ''
  drafts.value = []
  skippedQ.value = []
  awaiting.value = null
  idea.value = ''
  await nextTick()
  ideaRef.value?.focus()
}

function ensureNotSkipped(qi: number): void {
  if (skippedQ.value.includes(qi)) skippedQ.value = skippedQ.value.filter((x) => x !== qi)
}
function adopt(qi: number): void {
  const r = openRound.value
  if (!r || !r.frontier[qi]) return
  ensureNotSkipped(qi)
  drafts.value = drafts.value.map((v, i) => (i === qi ? r.frontier[qi].recommended_answer : v))
}
function pickAlternative(qi: number, alt: string): void {
  ensureNotSkipped(qi)
  drafts.value = drafts.value.map((v, i) => (i === qi ? alt : v))
}
function skipQuestion(qi: number): void {
  drafts.value = drafts.value.map((v, i) => (i === qi ? '' : v))
  if (!skippedQ.value.includes(qi)) skippedQ.value = [...skippedQ.value, qi]
}
function undoSkip(qi: number): void {
  skippedQ.value = skippedQ.value.filter((x) => x !== qi)
}

function answersForRound(r: FrontierRound): Array<string | null> {
  return r.frontier.map((_, qi) => (skippedQ.value.includes(qi) ? null : (drafts.value[qi] || '').trim()))
}

/** 推进一次（写后刷新权威态）；返回是否收敛。 */
async function advanceAndRefresh(): Promise<boolean> {
  const task = activeTask.value
  if (!task) return false
  const res = await advanceGrilling(task.id)
  awaiting.value = null
  await refreshChat()
  return res.converged
}

async function submitRound(): Promise<void> {
  const r = openRound.value
  const task = activeTask.value
  if (!r || !task) return
  if (!canSubmit.value) {
    ElMessage.warning('请逐题作答，或点「暂时跳过」/ 采纳推荐答案')
    return
  }
  submitting.value = true
  try {
    await submitAnswers(task.id, r.round_no, answersForRound(r))
    const converged = await advanceAndRefresh()
    // 刚答完的轮次默认展开，让「我的回答」即时可见
    expandedIds.value = [...new Set([...expandedIds.value, r.round_no])]
    ElMessage.success(converged ? '拷问已收敛，生成结构化方案草稿' : '已推进到下一轮')
  } catch (err) {
    ElMessage.error(describeFlowError(err, '提交'))
  } finally {
    submitting.value = false
  }
}

async function submitSkipAll(): Promise<void> {
  const r = openRound.value
  const task = activeTask.value
  if (!r || !task || submitting.value) return
  submitting.value = true
  try {
    await submitAnswers(
      task.id,
      r.round_no,
      r.frontier.map(() => null)
    )
    const converged = await advanceAndRefresh()
    expandedIds.value = [...new Set([...expandedIds.value, r.round_no])]
    ElMessage.success(converged ? '已整轮跳过并收敛' : '已整轮跳过并推进到下一轮')
  } catch (err) {
    ElMessage.error(describeFlowError(err, '提交'))
  } finally {
    submitting.value = false
  }
}

async function doAdvance(): Promise<void> {
  if (advancing.value) return
  advancing.value = true
  try {
    const converged = await advanceAndRefresh()
    ElMessage.success(converged ? '拷问已收敛' : '已推进到下一轮')
  } catch (err) {
    ElMessage.error(describeFlowError(err, '推进'))
  } finally {
    advancing.value = false
  }
}

async function doConfirm(): Promise<void> {
  const task = activeTask.value
  if (!task || confirming.value) return
  if (openItemCount.value > 0) {
    ElMessage.warning(`还有 ${openItemCount.value} 项待确认事项未处置，无法确认`)
    return
  }
  confirming.value = true
  try {
    plan.value = await confirmPlanApi(task.id)
    confirmDialog.value = false
    awaiting.value = null
    ElMessage.success('方案已确认')
  } catch (err) {
    ElMessage.error(describeFlowError(err, '确认'))
  } finally {
    confirming.value = false
  }
}

async function doRevise(): Promise<void> {
  const task = activeTask.value
  const inst = reviseText.value.trim()
  if (!task || !inst || revising.value) return
  revising.value = true
  try {
    await revisePlan(task.id, inst)
    await refreshChat()
    reviseText.value = ''
    ElMessage.success('方案已更新为草稿 · 需要再次确认')
  } catch (err) {
    ElMessage.error(describeFlowError(err, '修订'))
  } finally {
    revising.value = false
  }
}

async function doResolve(item: OpenItem, status: ResolveStatus): Promise<void> {
  const task = activeTask.value
  if (!task || resolvingId.value === item.id) return
  resolvingId.value = item.id
  try {
    await resolveOpenItem(task.id, item.id, status)
    openItems.value = (await listOpenItems(task.id)).items
    ElMessage.success(status === 'confirmed' ? '已确认为已定需求' : '已搁置该待确认事项')
  } catch (err) {
    ElMessage.error(describeFlowError(err, '处置'))
  } finally {
    resolvingId.value = null
  }
}

function describeFlowError(err: unknown, action: string): string {
  if (err instanceof BackendUnavailableError) return `后端未启动，${action}失败`
  const msg = (err as Error).message || ''
  if (isApiStatus(err, 502))
    return '模型无法产出可用内容（前沿 / 方案 / 修订解析失败），请稍后重试或检查默认模型配置'
  if (isApiStatus(err, 501)) return '方案已确认，但成品生成管线由 TB-5 / TB-6 落地'
  if (isApiStatus(err, 422)) return '请求被拒绝：回答数量与问题数量不一致，或处置状态不合法'
  if (isApiStatus(err, 404)) return '对应的轮次 / 方案 / 待确认事项不存在'
  if (isApiStatus(err, 409)) return '生成闸门未放行：方案未确认或仍有未处置的待确认事项'
  return `${action}失败：${msg}`
}

function taskIdFromQuery(): number | null {
  const raw = route.query.task
  const id = Array.isArray(raw) ? Number(raw[0]) : Number(raw)
  return Number.isFinite(id) && id > 0 ? id : null
}

// 进入本页时：带 ?task=id（来自历史页 / 左栏「最近任务」）→ 直接续作；否则显示任务列表。
watch(
  () => route.query.task,
  () => {
    const id = taskIdFromQuery()
    if (id) void resumeByTaskId(id)
  },
  { immediate: true }
)

onMounted(() => {
  if (!taskIdFromQuery()) void loadTasks()
})
</script>

<style scoped>
/* 页眉 */
.head-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.status-chip .tf-dot {
  margin-right: 5px;
}

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
.day-sep {
  text-align: center;
  font-size: var(--fs-xs);
  color: var(--text-4);
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

/* 当前轮 / 问题卡片 */
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
.round-foot {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
  margin-top: var(--sp-3);
}
.round-advance {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

/* 可折叠历史轮次 */
.qround {
  background: var(--bg-surface);
  border: 1px solid var(--line-1);
  border-radius: var(--r-md);
  overflow: hidden;
}
.qround-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  width: 100%;
  padding: var(--sp-3) var(--sp-4);
  border: 0;
  background: none;
  text-align: left;
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.qround-head:hover {
  background: var(--bg-hover);
}
.qround-head .ico.ok {
  color: var(--ok-fg);
}
.qround .chev {
  margin-left: auto;
  color: var(--text-4);
  transition: transform 0.16s;
}
.qround.is-open .chev {
  transform: rotate(90deg);
}
.qround-body {
  padding: 0 var(--sp-4) var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.done-qa {
  border-left: 2px solid var(--line-2);
  padding-left: var(--sp-3);
}
.done-qa b {
  font-size: var(--fs-sm);
  font-weight: 600;
  display: block;
  color: var(--text-1);
}
.done-qa span {
  font-size: var(--fs-sm);
  color: var(--text-3);
  display: block;
  margin-top: 2px;
  white-space: pre-wrap;
}

/* 结构化方案卡 */
.plan-card {
  border-color: var(--brand-200);
  box-shadow: 0 1px 3px rgba(20, 28, 46, 0.05);
}
.plan-card.is-locked {
  border-color: var(--line-1);
  box-shadow: none;
}
.converge .note-body b {
  color: var(--text-1);
}
.plan-title {
  font-size: var(--fs-lg);
  font-weight: 600;
  color: var(--text-1);
  margin-bottom: var(--sp-4);
}
.plan-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--sp-6);
}
.fld {
  padding: 0 0 var(--sp-4);
  min-width: 0;
}
.fld h4 {
  margin: 0 0 var(--sp-1);
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--text-3);
  letter-spacing: 0.5px;
}
.fld-body {
  font-size: var(--fs-sm);
  color: var(--text-1);
  line-height: 1.65;
}
.fld-body :deep(p) {
  margin: 0 0 var(--sp-2);
}
.fld-body :deep(p:last-child) {
  margin-bottom: 0;
}
.fld-body :deep(ul),
.fld-body :deep(ol) {
  margin: 0 0 var(--sp-2);
  padding-left: var(--sp-4);
}
.fld-body :deep(li) {
  margin: 2px 0;
  line-height: 1.6;
}
.fld-body :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.92em;
  background: var(--bg-sunken);
  border-radius: var(--r-xs);
  padding: 1px 5px;
}
.fld-body :deep(a) {
  color: var(--brand-600);
  text-underline-offset: 2px;
}
.fld-body :deep(blockquote) {
  margin: 0 0 var(--sp-2);
  padding-left: var(--sp-3);
  border-left: 2px solid var(--line-2);
  color: var(--text-3);
}
.fld-body :deep(hr) {
  border: 0;
  border-top: 1px solid var(--line-1);
  margin: var(--sp-3) 0;
}
.fld-body :deep(strong) {
  color: var(--text-1);
}

/* 待确认事项（只读） */
.plan-pending {
  border-top: 1px solid var(--line-1);
  margin-top: var(--sp-2);
  padding-top: var(--sp-4);
}
.plan-pending h4 {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin: 0 0 var(--sp-1);
  font-size: var(--fs-md);
  color: var(--warn-fg);
}
.plan-pending h4 .ico {
  color: var(--warn-fg);
}
.plan-pending p {
  margin: 0 0 var(--sp-3);
  font-size: var(--fs-xs);
  color: var(--text-3);
}
.pend-empty {
  border: 1px dashed var(--line-3);
  border-radius: var(--r-sm);
  background: var(--bg-sunken);
  padding: var(--sp-3);
  font-size: var(--fs-sm);
  color: var(--text-3);
  text-align: center;
}

/* 方案脚：闸门 / 确认 / 生成 */
.plan-foot {
  border-top: 1px solid var(--line-1);
  padding: var(--sp-4) var(--sp-5);
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  flex-wrap: wrap;
}
.gate {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-sm);
  color: var(--text-2);
  flex: 1;
  min-width: 220px;
}
.gate .lock {
  color: var(--warn-fg);
}
.ok-note {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-sm);
  color: var(--ok-fg);
  flex: 1;
  min-width: 220px;
}
.plan-foot .hint {
  width: 100%;
  font-size: var(--fs-xs);
  color: var(--text-3);
  margin: 0;
}

/* 确认弹层 */
.confirm-body p {
  font-size: var(--fs-sm);
  color: var(--text-2);
  margin: 0 0 var(--sp-3);
  line-height: 1.6;
}
.cf-item {
  display: flex;
  gap: var(--sp-3);
  padding: var(--sp-2) 0;
  border-bottom: 1px solid var(--line-1);
  font-size: var(--fs-sm);
}
.cf-item b {
  color: var(--text-3);
  min-width: 96px;
  font-weight: 600;
}
.cf-item span {
  color: var(--text-1);
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

/* 发起创想旁的次级控件行（模型选择）：窄屏自动换行 */
.composer-opts {
  display: flex;
  align-items: center;
  gap: var(--sp-2) var(--sp-3);
  flex-wrap: wrap;
  margin-top: var(--sp-2);
}
.composer-opts > .xs {
  line-height: 1.55;
}

/* 「为什么现在问」与备选方向 */
.q-why {
  margin: 3px 0 0;
  font-size: var(--fs-xs);
  color: var(--text-3);
  line-height: 1.55;
}
.alt-row {
  margin-top: var(--sp-2);
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.alt-label {
  font-size: var(--fs-xs);
  color: var(--text-3);
}
.alt {
  font-size: var(--fs-xs);
  color: var(--text-2);
  background: var(--bg-surface);
  border: 1px solid var(--line-2);
  border-radius: var(--r-pill);
  padding: 2px 10px;
  cursor: pointer;
}
.alt:hover {
  border-color: var(--brand-200);
  color: var(--brand-600);
  background: var(--brand-50);
}

/* 跳过态 */
.qcard.is-skip {
  background: var(--warn-bg);
}
.ans-skipped {
  margin-top: var(--sp-3);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.skip-note {
  font-size: var(--fs-sm);
  color: var(--warn-fg);
  line-height: 1.55;
}

/* 历史轮：跳过条目标为未定 */
.done-qa.is-skip {
  border-left-color: var(--warn-line);
}
.ico.warn {
  color: var(--warn-fg);
}

/* 待确认事项清单 */
.pend-count {
  margin-left: var(--sp-2);
  font-size: var(--fs-xs);
  font-weight: 400;
  color: var(--warn-fg);
  background: var(--warn-bg);
  border: 1px solid var(--warn-line);
  border-radius: var(--r-pill);
  padding: 1px 8px;
}
.pend-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.pend {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-3) 0;
  border-top: 1px solid var(--line-1);
  flex-wrap: wrap;
}
.pend:first-child {
  border-top: 0;
}
.pend-grow {
  flex: 1;
  min-width: 180px;
}
.pend-name {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text-1);
}
.pend-sub {
  font-size: var(--fs-xs);
  color: var(--text-3);
  margin-top: 2px;
}
.pend.is-decided .pend-name {
  color: var(--text-3);
}

/* 最近修订的变更摘要 */
.plan-changed {
  border: 1px solid var(--brand-100);
  background: var(--brand-50);
  border-radius: var(--r-md);
  padding: var(--sp-3) var(--sp-4);
  margin-bottom: var(--sp-4);
  font-size: var(--fs-sm);
}
.plan-changed b {
  color: var(--brand-700);
}
.ch-inst {
  display: block;
  color: var(--text-2);
  margin-top: 2px;
}
.ch-list {
  display: flex;
  gap: var(--sp-2);
  flex-wrap: wrap;
  margin-top: var(--sp-2);
}
.ch {
  font-size: var(--fs-xs);
  border-radius: var(--r-xs);
  padding: 1px 8px;
  border: 1px solid var(--line-2);
  background: var(--bg-surface);
  color: var(--text-2);
}
.ch-added {
  background: var(--ok-bg);
  border-color: var(--ok-line);
  color: var(--ok-fg);
}
.ch-modified {
  background: var(--warn-bg);
  border-color: var(--warn-line);
  color: var(--warn-fg);
}
.ch-removed {
  background: var(--err-bg);
  border-color: var(--err-line);
  color: var(--err-fg);
}

/* 对话式修订输入 */
.plan-revise {
  border-top: 1px solid var(--line-1);
  margin-top: var(--sp-4);
  padding-top: var(--sp-4);
}
.plan-revise h4 {
  margin: 0 0 var(--sp-2);
  font-size: var(--fs-md);
  color: var(--text-1);
}
.plan-revise textarea {
  width: 100%;
  min-height: 56px;
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
.plan-revise textarea:focus {
  outline: none;
  border-color: var(--brand-500);
  box-shadow: 0 0 0 3px var(--brand-50);
}
.revise-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
  margin-top: var(--sp-2);
}

/* 修订历史 */
.revisions {
  border-top: 1px solid var(--line-1);
  margin-top: var(--sp-4);
  padding-top: var(--sp-2);
}
.rev-toggle {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  border: 0;
  background: none;
  text-align: left;
  padding: var(--sp-2) 0;
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.rev-toggle .chev {
  color: var(--text-4);
  transition: transform 0.16s;
}
.rev-toggle .chev.is-open {
  transform: rotate(90deg);
}
.rev-list {
  list-style: none;
  margin: var(--sp-1) 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.rev-item {
  border-left: 2px solid var(--line-2);
  padding-left: var(--sp-3);
}
.rev-head {
  font-size: var(--fs-xs);
  color: var(--text-3);
}
.rev-inst {
  font-size: var(--fs-sm);
  color: var(--text-1);
  margin-top: 2px;
}
.rev-changes {
  display: flex;
  gap: var(--sp-2);
  flex-wrap: wrap;
  margin-top: var(--sp-1);
}

/* 闸门被未定项挡住 */
.gate-block {
  color: var(--warn-fg);
}

/* 响应式：对齐原型断点（1360 / 1200 / 1000 / 820 / 560），保留 960 / 1100 现有行为 */
@media (max-width: 1360px) {
  .steps {
    gap: var(--sp-1);
  }
}
@media (max-width: 1200px) {
  .plan-grid {
    grid-template-columns: minmax(0, 1fr);
    gap: 0;
  }
  .plan-grid > .fld + .fld {
    margin-top: var(--sp-3);
    padding-top: var(--sp-3);
    border-top: 1px solid var(--line-1);
  }
}
@media (max-width: 1000px) {
  .steps {
    gap: 0;
  }
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
@media (max-width: 820px) {
  .step-txt em {
    display: none;
  }
  .card-body,
  .qcard,
  .plan-pending,
  .plan-foot {
    padding-left: var(--sp-4);
    padding-right: var(--sp-4);
  }
}
@media (max-width: 560px) {
  .pill textarea {
    min-height: 44px;
  }
  .composer-hint {
    display: none;
  }
}
</style>

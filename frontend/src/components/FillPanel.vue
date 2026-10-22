<template>
  <div class="card fb-card">
    <div class="card-head">
      <h3>填充为正文</h3>
      <span class="sub">先定篇幅 · 再逐章扩写</span>
      <span class="right">
        <el-tag size="small" type="info" effect="plain">
          <el-icon class="tag-ico"><Document /></el-icon>{{ statusText }}
        </el-tag>
      </span>
    </div>

    <div class="card-body">
      <p class="hint fb-lead">
        字数按<strong>汉字</strong>计，不含标点与空白。系统按方案各章的「建议字数」权重把总量
        分摊到每章，余数归最后一章，保证各章之和<strong>恰好</strong>等于目标；分摊后仍可逐章调整。
      </p>

      <div class="fb-actions">
        <el-button type="primary" :icon="EditPen" :disabled="busy" @click="openDialog">
          设定目标字数
        </el-button>
        <span v-if="allocation" class="xs muted">{{ summary }}</span>
        <span v-else class="xs muted">还没设定篇幅；点左侧按钮选档位或填自定义值</span>
      </div>

      <!-- 分摊结果：一章一行，逐章可改（工单 15 的核心诉求） -->
      <ol v-if="allocation && allocation.items.length" class="fb-list">
        <li v-for="row in rows" :key="row.seq" class="fb-item">
          <span class="fb-seq">{{ row.seq }}</span>
          <span class="fb-title">{{ row.title }}</span>
          <el-input
            v-model="row.text"
            class="fb-input"
            size="small"
            inputmode="numeric"
            maxlength="8"
            spellcheck="false"
            :disabled="busy"
            @blur="onEdit(row)"
          >
            <template #suffix><span class="fb-unit">字</span></template>
          </el-input>
          <span class="fb-hint xs" :class="{ err: row.issue !== '' }">
            {{ row.issue || sectionLengthHint(row.value, row.edited) }}
          </span>
        </li>
      </ol>

      <div v-if="allocation && !allocationExact" class="note warn fb-warn" role="status">
        <el-icon class="ico"><WarningFilled /></el-icon>
        <div class="note-body">
          <b>各章之和与目标不一致</b>
          <span>{{ summary }}；改动会在下一次分摊时归位，或直接把目标字数改成这个和。</span>
        </div>
      </div>

      <div v-if="error" class="note warn fb-warn" role="alert">
        <el-icon class="ico"><WarningFilled /></el-icon>
        <div class="note-body">
          <b>分摊没有成功</b>
          <span>{{ error }}</span>
        </div>
      </div>

      <p class="fb-note xs muted">
        分摊只算不写：调整字数不会改动章节表，也不会开始填充。
        真正的填充要再用下方「生成面板」出的成品才算数——这里只负责篇幅。
      </p>
    </div>

    <!-- 参数弹窗：档位 + 自定义（工单 4 的共享外壳），确认即向后端要一份分摊预览 -->
    <ParamDialog
      v-model="dialogVisible"
      title="设定目标字数"
      width="520px"
      confirm-text="按这个篇幅分摊"
      :loading="allocating"
      @confirm="applyTarget"
    >
      <ParamField v-model="draftTarget" :spec="WORD_COUNT_PARAM" />
      <p class="hint fb-dialog-hint">
        档位只是快捷方式，旁边随时可以输入 {{ MIN_TARGET_LENGTH }}–{{ MAX_TARGET_LENGTH }} 之间的自定义值；
        超出范围会说明原因，不会自动改成边界值。
      </p>
    </ParamDialog>
  </div>
</template>

<script setup lang="ts">
/**
 * 字数分摊面板（工单 15）。
 *
 * 职责只有一件：把「目标字数 → 每章多少字」这件事摆出来，并允许逐章微调。
 * **分摊算法不在前端**：每次改动都向后端 `POST /fill/allocation` 要结果（只算不写），
 * 前端只渲染。前端再摊一遍的后果是「预览一个数、真正写出另一个数」，
 * 正是规格 §2 点名反对的多套实现互相错位。
 *
 * 与生成面板分开：填充是**写作**（唯一会调模型的环节），生成是确定性渲染。
 * 混在一张卡里，用户就分不清「点了按钮到底会不会花模型额度」（ADR-0006 决策一）。
 */
import { computed, reactive, ref } from 'vue'
import { Document, EditPen, WarningFilled } from '@element-plus/icons-vue'
import {
  ApiHttpError,
  BackendUnavailableError,
  previewFillAllocation,
  type FillAllocationResponse
} from '../api/client'
import {
  MAX_TARGET_LENGTH,
  MIN_TARGET_LENGTH,
  allocationSummary,
  checkSectionLength,
  sectionLengthHint
} from '../utils/wordBudget'
import { WORD_COUNT_PARAM } from '../utils/paramField'
import ParamDialog from './ParamDialog.vue'
import ParamField from './ParamField.vue'

const props = defineProps<{
  taskId: number
  /** 没有进行中的填充任务时也允许分摊——篇幅是开工前的决定。 */
  disabled?: boolean
}>()

interface Row {
  seq: number
  title: string
  /** 输入框里的原文；失焦才解析，避免边输边报错。 */
  text: string
  /** 已确认生效的字数。 */
  value: number
  /** 用户是否手动改过这一章（改过的章在下次分摊时要作为约束带上）。 */
  edited: boolean
  /** 这一格的校验错误；空串表示没问题。 */
  issue: string
}

const dialogVisible = ref(false)
const draftTarget = ref<number | null>(null)
const allocating = ref(false)
const busy = computed(() => allocating.value || props.disabled === true)
const error = ref('')
const allocation = ref<FillAllocationResponse | null>(null)
const rows = reactive<Row[]>([])

const summary = computed(() =>
  allocation.value
    ? allocationSummary(
        allocation.value.target_length,
        rows.map((row) => row.value)
      ).text
    : ''
)
const allocationExact = computed(() =>
  allocation.value
    ? allocationSummary(
        allocation.value.target_length,
        rows.map((row) => row.value)
      ).exact
    : true
)
const statusText = computed(() => {
  if (allocating.value) return '正在分摊…'
  if (!allocation.value) return '尚未设定篇幅'
  return `目标 ${allocation.value.target_length} 字 · ${allocation.value.total} 章`
})

function openDialog(): void {
  // 已分摊过就把当前目标回填；没分摊过则留空（不伪造一个用户没选过的数）。
  draftTarget.value = allocation.value?.target_length ?? null
  dialogVisible.value = true
}

/**
 * 把当前所有**手动改过**的章作为约束带给后端，让分摊只重算剩下的章。
 *
 * 只带改过的：把系统算出来的值也当约束带上，会让下一次分摊完全没有余量可调。
 */
function overrides(): Record<number, number> {
  const result: Record<number, number> = {}
  for (const row of rows) {
    if (row.edited && row.issue === '') result[row.seq] = row.value
  }
  return result
}

function describeError(err: unknown): string {
  if (err instanceof BackendUnavailableError) return '后端未启动，无法分摊字数'
  if (err instanceof ApiHttpError) return err.detail || err.message
  return (err as Error).message || '分摊失败'
}

async function fetchAllocation(payload: { target_length: number }): Promise<void> {
  allocating.value = true
  error.value = ''
  try {
    const res = await previewFillAllocation(props.taskId, {
      target_length: payload.target_length,
      section_lengths: overrides()
    })
    allocation.value = res
    rows.splice(0, rows.length, ...res.items.map(toRow))
  } catch (err) {
    // 失败时保留上一次成功的分摊，不清空——用户还能看见原来的数。
    error.value = describeError(err)
  } finally {
    allocating.value = false
  }
}

function toRow(item: { seq: number; title: string; target_length: number }): Row {
  return {
    seq: item.seq,
    title: item.title,
    text: String(item.target_length),
    value: item.target_length,
    edited: false,
    issue: ''
  }
}

async function applyTarget(): Promise<void> {
  if (draftTarget.value === null) return
  await fetchAllocation({ target_length: draftTarget.value })
  // 成功才关弹窗：失败时留着，用户好在原处改字数重试。
  if (error.value === '') dialogVisible.value = false
}

/**
 * 某一章改完之后：先本地校验这一格，合法才向后端要新的分摊。
 *
 * 只把**这一格**作为约束、其余按目标重算，得到的结果仍然满足「各章之和 = 目标」；
 * 若用户把所有章都改成了固定值，后端会明确拒绝（和超过目标），不会偷偷压缩别的章。
 */
async function onEdit(row: Row): Promise<void> {
  const checked = checkSectionLength(row.text)
  if (checked.ok === false) {
    row.issue = checked.message
    return
  }
  row.issue = ''
  row.value = checked.value
  row.edited = true
  if (!allocation.value) return
  await fetchAllocation({ target_length: allocation.value.target_length })
}
</script>

<style scoped>
.fb-card {
  border-color: var(--line-1);
}
.fb-lead {
  margin-top: 0;
}
.fb-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
}
.fb-list {
  list-style: none;
  margin: var(--sp-3) 0 0;
  padding: 0;
  border-top: 1px solid var(--line-1);
}
.fb-item {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) 96px 180px;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-2) 0;
  border-bottom: 1px solid var(--line-1);
}
.fb-seq {
  font-size: var(--fs-xs);
  color: var(--text-4);
  font-variant-numeric: tabular-nums;
}
.fb-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-sm);
  color: var(--text-1);
}
.fb-unit {
  font-size: var(--fs-xs);
  color: var(--text-4);
}
.fb-hint {
  color: var(--text-3);
}
.fb-hint.err {
  color: var(--err-fg);
}
.fb-warn {
  margin-top: var(--sp-3);
}
.fb-note {
  margin: var(--sp-3) 0 0;
}
.fb-dialog-hint {
  margin-top: var(--sp-3);
}
.tag-ico {
  margin-right: 4px;
}
</style>

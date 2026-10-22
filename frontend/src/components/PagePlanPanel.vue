<script setup lang="ts">
/**
 * 页面规划面板（工单 26）：做 PPT 前定页数 → 预览「哪一章占哪几页」→ 增删单页。
 *
 * 后端契约（`routes/pageplans.py`）：
 * - `POST /tasks/{id}/page-plans`         按目标页数生成规划（页数 3–60，区间外 422）；
 * - `POST .../{planId}/pages`             在某页之后插一页，**另存新规划**；
 * - `DELETE .../{planId}/pages/{index}`   删一页，**另存新规划**。
 * 增删都产生新规划而不是就地改，所以每次操作后都要用响应里的新 `page_plan_id` 刷新。
 *
 * 页数语义：封面 + 结尾页都计入目标页数（见 #25），单页增删后实际页数会偏离最初目标，
 * 界面如实显示这个偏离（验收 ③），不假装相等。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Box, Delete, Plus } from '@element-plus/icons-vue'

import {
  addPlanPage,
  createPagePlan,
  deletePlanPage,
  getLatestPagePlan,
  type PagePlanResponse
} from '../api/client'
import {
  MAX_PAGES,
  MIN_PAGES,
  PAGE_PRESETS,
  crampedPages,
  isDeletable,
  pageCountSummary,
  pageOwnershipLabel,
  validatePageCount
} from '../utils/pagePlan'

const props = defineProps<{
  taskId: number
  /** 方案是否已确认：未确认时不让规划（后端会 409，界面先挡住）。 */
  unlocked: boolean
}>()

const targetPages = ref<number>(16)
const customPages = ref<string>('')
const plan = ref<PagePlanResponse | null>(null)
const loading = ref(false)
const editing = ref(false)
const error = ref('')

/** 当前生效的页数：自定义输入优先（留空则用预设档位）。 */
const effectivePages = computed<number | null>(() => {
  const raw = customPages.value.trim()
  if (!raw) return targetPages.value
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? parsed : null
})

/** 页数校验结果（null = 合法）。 */
const pageError = computed(() => validatePageCount(effectivePages.value))

const summary = computed(() => (plan.value ? pageCountSummary(plan.value) : ''))

/** 被挤压的页（多章并一页）：提示「重点可能被挤到最后」。 */
const cramped = computed(() => (plan.value ? crampedPages(plan.value) : []))

onMounted(() => {
  void refresh()
})

// 切换任务时清空旧规划，避免把上一个任务的页列表显示在新任务下。
watch(
  () => props.taskId,
  () => {
    plan.value = null
    error.value = ''
    void refresh()
  }
)

/**
 * 恢复「最近一次规划」（换任务 / 重进页面时）。
 *
 * 单页增删每次都另存新规划，所以「最新」就是最接近用户当前意图的那一份；没有规划时
 * 后端 404，属正常初始状态，不当作错误提示。
 */
async function refresh(): Promise<void> {
  error.value = ''
  plan.value = null
  if (!props.unlocked) return
  try {
    plan.value = await getLatestPagePlan(props.taskId)
    // 恢复后把页数输入对齐到该规划，避免界面显示 16 页、实际是上次的 12 页。
    targetPages.value = plan.value.target_pages
    customPages.value = ''
  } catch (err) {
    if ((err as { status?: number }).status !== 404) {
      error.value = '读取已有规划失败；仍可重新生成一份。'
    }
  }
}

async function generate(): Promise<void> {
  if (pageError.value) {
    error.value = pageError.value
    return
  }
  loading.value = true
  error.value = ''
  try {
    plan.value = await createPagePlan(props.taskId, effectivePages.value as number)
    ElMessage.success(`已生成 ${plan.value.actual_pages} 页规划`)
  } catch (err) {
    handleError(err, '生成规划')
  } finally {
    loading.value = false
  }
}

async function addPage(afterIndex: number): Promise<void> {
  if (!plan.value) return
  editing.value = true
  try {
    plan.value = await addPlanPage(props.taskId, plan.value.page_plan_id, afterIndex)
    ElMessage.success('已插入一页（另存为新规划）')
  } catch (err) {
    handleError(err, '插入页面')
  } finally {
    editing.value = false
  }
}

async function removePage(atIndex: number): Promise<void> {
  if (!plan.value) return
  editing.value = true
  try {
    plan.value = await deletePlanPage(props.taskId, plan.value.page_plan_id, atIndex)
    ElMessage.success('已删除该页（另存为新规划）')
  } catch (err) {
    handleError(err, '删除页面')
  } finally {
    editing.value = false
  }
}

function handleError(err: unknown, action: string): void {
  const status = (err as { status?: number }).status
  if (status === 409) {
    error.value = '方案未确认或还没有填充正文：先确认方案并完成填充，再规划页数。'
  } else if (status === 422) {
    error.value = `页数不合法：需在 ${MIN_PAGES}–${MAX_PAGES} 之间。`
  } else {
    error.value = `${action}失败，请确认本地服务已启动后重试。`
  }
}
</script>

<template>
  <div class="card page-plan">
    <div class="card-head">
      <h3>页面规划</h3>
      <span class="right xs muted">先定页数，再看「哪一章占哪几页」</span>
    </div>

    <div class="card-body">
      <p v-if="!unlocked" class="hint">方案确认并完成填充后才能规划页数。</p>

      <template v-else>
        <div class="gfield">
          <label>目标页数</label>
          <div class="preset-row">
            <button
              v-for="preset in PAGE_PRESETS"
              :key="preset"
              type="button"
              class="preset"
              :class="{ sel: !customPages.trim() && targetPages === preset }"
              @click="targetPages = preset; customPages = ''"
            >
              {{ preset }} 页
            </button>
            <input
              v-model="customPages"
              class="custom-input"
              type="number"
              :min="MIN_PAGES"
              :max="MAX_PAGES"
              placeholder="自定义 3–60"
            />
          </div>
          <p v-if="pageError" class="hint err">{{ pageError }}</p>
          <p v-else class="hint">
            封面与结尾页都计入总页数，所以「说 {{ effectivePages }} 页就是
            {{ effectivePages }} 页」。
          </p>
        </div>

        <div class="actions">
          <el-button
            type="primary"
            :icon="Box"
            :loading="loading"
            :disabled="!!pageError"
            @click="generate()"
          >
            生成页面规划
          </el-button>
        </div>

        <div v-if="error" class="note err" role="alert">{{ error }}</div>

        <template v-if="plan">
          <div class="plan-summary">
            <b>{{ summary }}</b>
            <span class="xs muted">规划 #{{ plan.page_plan_id }}</span>
          </div>

          <div v-if="cramped.length" class="note warn">
            有 {{ cramped.length }} 页合并了多章，重点章可能被挤到后面——可考虑加页拆开。
          </div>

          <table class="tbl plan-table">
            <thead>
              <tr>
                <th>页</th>
                <th>类型 / 归属</th>
                <th>标题</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="page in plan.pages" :key="page.index">
                <td class="mono">{{ page.index }}</td>
                <td>
                  <span class="own" :class="`own-${page.kind}`">{{ pageOwnershipLabel(page) }}</span>
                </td>
                <td>{{ page.title }}</td>
                <td class="ops">
                  <el-button
                    size="small"
                    :icon="Plus"
                    :disabled="editing"
                    title="在这一页之后插入一页"
                    @click="addPage(page.index)"
                  />
                  <el-button
                    size="small"
                    :icon="Delete"
                    :disabled="editing || !isDeletable(page)"
                    :title="isDeletable(page) ? '删除这一页' : '封面与结尾页不可删'"
                    @click="removePage(page.index)"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </template>
      </template>
    </div>
  </div>
</template>

<style scoped>
.page-plan .preset-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.page-plan .preset {
  border: 1px solid var(--el-border-color);
  background: transparent;
  border-radius: 6px;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 13px;
}
.page-plan .preset.sel {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
  font-weight: 600;
}
.page-plan .custom-input {
  width: 120px;
  padding: 6px 10px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
}
.page-plan .plan-summary {
  display: flex;
  gap: 10px;
  align-items: baseline;
  margin: 12px 0 8px;
}
.page-plan .plan-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.page-plan .plan-table th,
.page-plan .plan-table td {
  border-bottom: 1px solid var(--el-border-color-lighter);
  padding: 6px 8px;
  text-align: left;
}
.page-plan .own {
  font-size: 12px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
}
.page-plan .own-cover,
.page-plan .own-end {
  color: var(--el-text-color-secondary);
}
.page-plan .own-content {
  color: var(--el-color-primary);
}
.page-plan .ops {
  white-space: nowrap;
}
</style>

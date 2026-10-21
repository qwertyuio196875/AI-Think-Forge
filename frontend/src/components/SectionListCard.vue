<template>
  <div class="card slc-card">
    <div class="card-head">
      <h3>成品章节清单</h3>
      <span class="sub">{{ subText }}</span>
      <span class="right">
        <el-tag size="small" type="info" effect="plain">
          <el-icon class="tag-ico"><Document /></el-icon>只读
        </el-tag>
      </span>
    </div>

    <!-- 读取中：不先渲染空清单，否则会闪一下「没有章节」 -->
    <div v-if="state === 'loading'" class="card-body slc-loading">
      <el-skeleton :rows="3" animated />
    </div>

    <!-- 读取失败：说清是读不到而不是没有章节，并给重试 -->
    <div v-else-if="state === 'error'" class="card-body">
      <div class="note err" role="alert">
        <el-icon class="ico"><WarningFilled /></el-icon>
        <div class="note-body">
          <b>章节清单读取失败</b>
          <span>{{ errorText }}</span>
        </div>
      </div>
      <div class="slc-actions">
        <!-- 点重试后卡片立刻切回骨架屏，所以这里不需要再挂 loading -->
        <el-button size="small" @click="load">重新读取</el-button>
      </div>
    </div>

    <div v-else class="card-body">
      <!-- 清单本身：一行一章，文案由 sectionLine 统一生成。
           状态标签只在非「待写」时出现：填充前每章都是待写，逐行重复同一个标签
           只是噪声；等到 #9 填充后，已完成 / 失败这类**有信息量**的状态才需要突出。 -->
      <ol v-if="items.length" class="slc-list">
        <li v-for="it in items" :key="it.seq" class="slc-item">
          <span class="slc-line">{{ sectionLine(it) }}</span>
          <el-tag
            v-if="it.status !== 'pending'"
            class="slc-tag"
            size="small"
            :type="sectionStatusTag(it.status).type"
            effect="plain"
          >
            {{ sectionStatusLabel(it) }}
          </el-tag>
          <span v-if="it.hanzi_count > 0" class="slc-done xs muted">已写 {{ it.hanzi_count }} 字</span>
        </li>
      </ol>

      <!-- 空清单不是错误（后端 200 + items: []），但必须解释为什么空 -->
      <div v-else class="note warn" role="status">
        <el-icon class="ico"><WarningFilled /></el-icon>
        <div class="note-body">
          <b>{{ sectionListHeadline(0) }}</b>
          <span>{{ EMPTY_SECTIONS_HINT }}</span>
        </div>
      </div>

      <!-- 清单属于旧版方案：明说，别让人拿过期目录去填充。
           正常流程里方案一改本卡就会重读，走到这里说明两端看到的是不同版本方案。 -->
      <div v-if="stale" class="note warn slc-stale" role="status">
        <el-icon class="ico"><WarningFilled /></el-icon>
        <div class="note-body">
          <b>清单已过期</b>
          <span>这份清单属于方案 #{{ listPlanId }}，当前方案已是 #{{ planId }}；请以修订后的方案为准，不要按这份目录填充。</span>
        </div>
      </div>

      <!-- 只读说明 + 唯一出口：返回既有修订流程 -->
      <p class="slc-readonly">{{ READONLY_NOTICE }}</p>
      <div class="slc-actions">
        <el-button size="small" :icon="Back" @click="emit('back-to-revise')">
          {{ RETURN_TO_REVISE_LABEL }}
        </el-button>
        <span class="xs muted">章节能改的唯一方式是改方案：提交修订后方案回到草稿态，需再次确认。</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 确认后章节清单卡（工单 8）。
 *
 * 只做一件事：把后端「成品章节」清单（`GET /api/tasks/{id}/sections`）只读地摆出来，
 * 让人在花掉模型额度之前看见「将生成哪几章、每章大约多少字」。
 *
 * 刻意**没有任何编辑入口**——不改名、不拖拽排序、不增删章节（规格 §3 明确不做
 * 「方案直接编辑」）。唯一的出口是「返回修订方案」，交回既有对话式修订流程。
 * 所以本组件不碰方案正文，也不用前端那套按 `##` 段落做的展示切分来推导章节：
 * 那会把「方案分节」当成成品目录，正是 GLOSSARY 警告的混用。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { Back, Document, WarningFilled } from '@element-plus/icons-vue'
import {
  BackendUnavailableError,
  ApiHttpError,
  listPlanSections,
  type PlanSectionItem
} from '../api/client'
import {
  EMPTY_SECTIONS_HINT,
  READONLY_NOTICE,
  RETURN_TO_REVISE_LABEL,
  isSectionListStale,
  sectionLine,
  sectionListHeadline,
  sectionStatusLabel,
  sectionStatusTag
} from '../utils/sectionList'

const props = defineProps<{
  /** 任务 id：章节清单一律按任务取（后端再从当前方案切） */
  taskId: number
  /** 当前已确认方案的 id：方案一改就换，用来判断清单是否过期 */
  planId: number
}>()

const emit = defineEmits<{
  /** 返回方案修订流程（唯一出口，由父组件定位到既有的修订框） */
  (e: 'back-to-revise'): void
}>()

type LoadState = 'loading' | 'ready' | 'error'

const state = ref<LoadState>('loading')
const items = ref<PlanSectionItem[]>([])
const listPlanId = ref(0)
const errorText = ref('')

/**
 * 副标题：正常态说「将生成 N 章」，其余态各自说明，避免加载中/失败时
 * 头部就写着「没有可切分的成品章节」，让人以为方案真的切不出章节。
 */
const subText = computed(() => {
  if (state.value === 'loading') return '正在读取…'
  if (state.value === 'error') return '读取失败'
  return sectionListHeadline(items.value.length)
})
const stale = computed(
  () =>
    state.value === 'ready' &&
    listPlanId.value > 0 &&
    isSectionListStale(listPlanId.value, props.planId)
)

async function load(): Promise<void> {
  state.value = 'loading'
  errorText.value = ''
  try {
    const res = await listPlanSections(props.taskId)
    items.value = res.items
    listPlanId.value = res.plan_id
    state.value = 'ready'
  } catch (err) {
    if (err instanceof BackendUnavailableError) {
      errorText.value = '后端未启动，无法读取章节清单'
    } else if (err instanceof ApiHttpError && err.status === 404) {
      // 404 表示任务还没有结构化方案 / 方案不存在，与「空清单」不是一回事
      errorText.value = err.detail || '当前任务还没有已确认的结构化方案'
    } else {
      errorText.value = (err as Error).message || '章节清单读取失败'
    }
    items.value = []
    state.value = 'error'
  }
}

onMounted(load)
// 方案修订后 planId 变化 = 换了一版方案，旧清单立刻作废重读
watch([() => props.taskId, () => props.planId], load)
</script>

<style scoped>
.slc-card {
  border-color: var(--line-1);
}
.slc-loading {
  min-height: 72px;
}
.slc-list {
  list-style: none;
  margin: 0;
  padding: 0;
  border-top: 1px solid var(--line-1);
}
.slc-item {
  display: flex;
  align-items: baseline;
  gap: var(--sp-3);
  min-width: 0;
  padding: var(--sp-2) 0;
  border-bottom: 1px solid var(--line-1);
}
.slc-line {
  flex: 1;
  min-width: 0;
  font-size: var(--fs-sm);
  color: var(--text-1);
}
.slc-tag {
  flex: none;
}
.slc-done {
  flex: none;
  white-space: nowrap;
}
.slc-stale {
  margin-top: var(--sp-3);
}
.slc-readonly {
  margin: var(--sp-3) 0 0;
  font-size: var(--fs-xs);
  color: var(--text-3);
}
.slc-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
  margin-top: var(--sp-3);
}
.tag-ico {
  margin-right: 4px;
}
</style>

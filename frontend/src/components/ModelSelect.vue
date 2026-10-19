<template>
  <div class="model-select" role="group" :aria-label="label">
    <span class="ms-label">{{ label }}</span>

    <!-- 读取中：不可操作，不显示伪造选项 -->
    <el-select
      v-if="state === 'loading'"
      class="ms-select"
      size="small"
      disabled
      :loading="true"
      placeholder="正在读取模型配置…"
      :model-value="sentinel"
    />

    <!-- 读取失败：如实说明，给一个真实的重试入口；不阻塞主操作 -->
    <template v-else-if="state === 'error'">
      <span class="ms-note">模型列表不可用</span>
      <el-button link type="primary" size="small" @click="load">重试</el-button>
    </template>

    <!-- 读到了但一条配置也没有：只有一个「跟随默认」可选，不必摆出下拉 -->
    <span v-else-if="providers.length === 0" class="ms-note">
      还没有模型配置，将按默认档位解析
    </span>

    <el-select v-else class="ms-select" size="small" :model-value="current" @change="onChange">
      <el-option :label="defaultLabel" :value="sentinel" />
      <el-option v-for="p in providers" :key="p.id" :label="providerOptionLabel(p)" :value="p.id" />
    </el-select>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listProviders, type Provider } from '../api/client'
import { providerOptionLabel } from '../utils/providerMeta'

/**
 * 任务级模型选择器（次级控件）：值 `null` = 跟随默认档位，数字 = 该任务的模型覆盖。
 *
 * 选项只来自 `GET /api/providers` 的真实返回；读不到就如实说读不到，
 * 读取失败不阻塞发起创作 / 上传资料（父组件仍按 null 提交）。
 */
const props = defineProps<{
  /** 当前覆盖值：null = 跟随默认档位。 */
  modelValue: number | null
  /** 控件标签，例如「模型」「分析模型」。 */
  label: string
  /** 默认项文案，例如「跟随默认模型」「跟随档位」。 */
  defaultLabel: string
}>()

const emit = defineEmits<{ 'update:modelValue': [value: number | null] }>()

/** 「跟随默认」的下拉内部值：用字符串哨兵，避免与 provider id 冲突。 */
const sentinel = '__follow_default__'

type State = 'loading' | 'ready' | 'error'
const state = ref<State>('loading')
const providers = ref<Provider[]>([])

const current = computed(() => props.modelValue ?? sentinel)

async function load(): Promise<void> {
  state.value = 'loading'
  try {
    providers.value = (await listProviders()).items
    state.value = 'ready'
  } catch {
    providers.value = []
    state.value = 'error'
  }
}

/** el-select 的 change 事件回传选项原值：哨兵 → null，其余 → 数字 id。 */
function onChange(value: string | number): void {
  if (value === sentinel) {
    emit('update:modelValue', null)
    return
  }
  const id = Number(value)
  if (!Number.isFinite(id) || id <= 0) {
    ElMessage.warning('该模型配置编号无效，已保持原选择')
    return
  }
  emit('update:modelValue', id)
}

onMounted(load)

defineExpose({ reload: load })
</script>

<style scoped>
/* 次级控件：小字标签 + 紧凑下拉，窄屏自动换行，不抢主操作层级 */
.model-select {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  min-width: 0;
}
.ms-label {
  font-size: var(--fs-xs);
  color: var(--text-3);
  white-space: nowrap;
}
.ms-select {
  width: 210px;
  max-width: 100%;
}
.ms-note {
  font-size: var(--fs-xs);
  color: var(--text-3);
}
</style>

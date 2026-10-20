<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    :width="width"
    :close-on-click-modal="closeOnClickModal"
    append-to-body
    @update:model-value="onVisibleChange"
  >
    <slot />
    <template #footer>
      <slot name="footer">
        <el-button :disabled="loading" @click="onCancel">{{ cancelText }}</el-button>
        <el-button type="primary" :loading="loading" @click="emit('confirm')">
          {{ confirmText }}
        </el-button>
      </slot>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
/**
 * 弹窗外壳（工单 #4）：标题 + 正文插槽 + 「取消 / 确认」页脚。
 *
 * 本仓库此前没有共享弹窗组件，三处（设置页、创作页、历史页）各自内联 `el-dialog`，
 * 连 `append-to-body`、`close-on-click-modal` 这类细节都要各抄一遍。#4 要求把设置页
 * 那套「参数型表单弹窗」抽出来给字数（#15）与页数（#25）复用，所以这里只固化**外壳**
 * 与**交互约定**，字段由 `ParamField` 负责，业务校验留在调用方——弹窗不该知道什么是字数。
 *
 * 关闭有两条路：页脚「取消」与右上角 × / Esc，两者都只是把 `modelValue` 置 false，
 * 由调用方决定是否要清理草稿；「确认」不自行关闭，避免关闭后才发现保存失败。
 */
withDefaults(
  defineProps<{
    /** 可见性，配合 `v-model` 使用。 */
    modelValue: boolean
    title: string
    /** Element Plus 的宽度写法，默认与设置页原弹窗一致。 */
    width?: string
    confirmText?: string
    cancelText?: string
    /** 确认按钮转圈期间同时禁用取消，避免保存中反复开关弹窗。 */
    loading?: boolean
    closeOnClickModal?: boolean
  }>(),
  {
    width: '560px',
    confirmText: '确认',
    cancelText: '取消',
    loading: false,
    closeOnClickModal: false
  }
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  /** 点「确认」：校验与保存都由调用方处理。 */
  confirm: []
  /** 点「取消」或右上角关闭：仅表示用户放弃，不做任何保存。 */
  cancel: []
}>()

function onVisibleChange(value: boolean) {
  emit('update:modelValue', value)
  // 只有「关掉」才算取消；打开是调用方自己改的 modelValue，不该回传 cancel。
  if (!value) emit('cancel')
}

function onCancel() {
  emit('update:modelValue', false)
  emit('cancel')
}
</script>

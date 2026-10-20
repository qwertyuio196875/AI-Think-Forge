<template>
  <div class="pf" :class="{ 'is-disabled': disabled }">
    <div class="pf-head">
      <label class="pf-label" :for="inputId">{{ label || spec.name }}</label>
      <span class="pf-range">允许 {{ rangeText(spec) }} {{ spec.unit }}</span>
    </div>

    <!-- 档位是快捷方式，不是唯一入口：旁边永远有自定义输入框 -->
    <el-radio-group
      class="pf-presets"
      :model-value="active"
      :disabled="disabled"
      @change="onPickPreset"
    >
      <el-radio-button v-for="(text, i) in labels" :key="spec.presets[i]" :value="spec.presets[i]">
        {{ text }}
      </el-radio-button>
      <el-radio-button value="custom">自定义</el-radio-button>
    </el-radio-group>

    <el-input
      :id="inputId"
      class="pf-input"
      :model-value="text"
      :disabled="disabled"
      :placeholder="customPlaceholder(spec)"
      inputmode="numeric"
      maxlength="8"
      spellcheck="false"
      @update:model-value="onType"
      @blur="onBlur"
    >
      <template #suffix>
        <span class="pf-unit">{{ spec.unit }}</span>
      </template>
    </el-input>

    <!-- 出错时只说明「为什么不行」，不把输入改成边界值；没出错时给出规矩 -->
    <p v-if="shownIssue" class="pf-issue" role="alert">
      <el-icon class="pf-issue-ico"><WarningFilled /></el-icon>
      <span>{{ shownIssue.message }}</span>
    </p>
    <p v-else class="pf-hint">{{ paramHint(spec) }}</p>
  </div>
</template>

<script setup lang="ts">
/**
 * 数值参数输入（工单 #4）：预设档位 + 自定义输入 + 范围说明。
 *
 * 只管「一个数值参数怎么填」，不关心它属于字数还是页数——两者差异全部塞在
 * `spec` 里，因此下游的填充面板（#15）与页面规划（#25）可以共用这一个组件，
 * 不必各写一份。
 *
 * 硬规则（US 14 / US 23）：超范围只提示原因，**不静默改成边界值**。所以本组件
 * 不会把用户的输入替换成 min / max，也不会对小数取整；校验交不通过时向父组件
 * 报 `null`，让「确认」按钮自然不可用，而不是替用户决定一个数。
 */
import { computed, ref, useId, watch } from 'vue'
import { WarningFilled } from '@element-plus/icons-vue'
import {
  customPlaceholder,
  checkParamInput,
  describeParamValue,
  isPresetValue,
  paramHint,
  presetLabels,
  rangeText,
  shouldRevealIssue,
  type ParamIssue,
  type ParamSpec
} from '../utils/paramField'

const props = withDefaults(
  defineProps<{
    /** 参数规格：档位、上下界、单位、名称（字数与页数各一份，见 paramField.ts）。 */
    spec: ParamSpec
    /** 当前值；null 表示还没填出合法值。 */
    modelValue: number | null
    /** 分组标签，缺省用 spec.name。 */
    label?: string
    disabled?: boolean
  }>(),
  { label: '', disabled: false }
)

const emit = defineEmits<{
  /** 输入合法时给数值，非法或为空时给 null。 */
  'update:modelValue': [value: number | null]
}>()

/** 每个实例一个稳定 id，供 label 的 for 指向输入框（无障碍，不靠视觉关联）。 */
const inputId = `pf-${useId()}`

/** 输入框文本是组件自己的状态：父组件只能拿到「解出来的数」，拿不到半截输入。 */
const text = ref(describeParamValue(props.modelValue, props.spec).text)
/** 是否该摊牌（失焦过一次或提交过）——没摊牌前不摆那些「再敲几位就好」的红字。 */
const revealed = ref(false)
/** 最近一次向外报告的值，用来分辨「父组件改的」与「自己刚报的」。 */
let reported: number | null = props.modelValue

const labels = computed(() => presetLabels(props.spec))

/** 单选组选中项：命中档位选该档，否则一律停在「自定义」。 */
const active = computed<number | 'custom'>(() =>
  isPresetValue(props.modelValue, props.spec) ? (props.modelValue as number) : 'custom'
)

/**
 * 红字什么时候出现：`shouldRevealIssue` 统一裁决。
 *
 * 超上界这类怎么敲都救不回来的立刻说；「还没输完」「低于下界」要等失焦，
 * 否则用户输 2000 的途中会被标红三次。
 */
const shownIssue = computed<ParamIssue | null>(() =>
  shouldRevealIssue(checkParamInput(text.value, props.spec), revealed.value)
)

/** 外部改值（打开弹窗、切换参数）时才重建文本；自己刚报出去的回声不重建。 */
watch(
  () => props.modelValue,
  (value) => {
    if (value === reported) return
    reported = value
    text.value = describeParamValue(value, props.spec).text
    revealed.value = false
  }
)

function onType(raw: string) {
  text.value = raw
  const res = checkParamInput(raw, props.spec)
  // 非法输入报 null：父组件的「确认」随之不可用，而不是拿着旧值蒙混过关。
  reported = res.ok ? res.value : null
  emit('update:modelValue', reported)
}

/** 离开输入框才摊牌，避免边输边骂。 */
function onBlur() {
  revealed.value = true
}

function onPickPreset(value: string | number | boolean) {
  revealed.value = true
  if (typeof value === 'number') {
    text.value = String(value)
    reported = value
    emit('update:modelValue', value)
    return
  }
  // 点「自定义」：清空并等用户输入；不预填任何数字（预填等于替他选了一个值）。
  text.value = ''
  reported = null
  emit('update:modelValue', null)
}
</script>

<style scoped>
.pf {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.pf-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-3);
}

.pf-label {
  font-size: var(--fs-xs);
  color: var(--text-3);
  font-weight: 600;
  letter-spacing: 0.3px;
}

.pf-range {
  font-size: var(--fs-xs);
  color: var(--text-4);
  font-variant-numeric: tabular-nums;
}

.pf-presets {
  flex-wrap: wrap;
}

.pf-input {
  width: 100%;
}

.pf-unit {
  font-size: var(--fs-xs);
  color: var(--text-4);
}

.pf-hint {
  font-size: var(--fs-xs);
  color: var(--text-3);
  line-height: 1.55;
  margin: 0;
}

.pf-issue {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-1);
  font-size: var(--fs-xs);
  color: var(--err-fg);
  line-height: 1.55;
  margin: 0;
}

.pf-issue-ico {
  margin-top: 2px;
  flex: none;
}
</style>

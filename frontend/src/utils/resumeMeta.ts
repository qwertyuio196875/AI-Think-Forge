/**
 * 续作动作元信息：把后端 `awaiting`（ResumeNext）映射为工作台可读文案与操作。
 * 命名遵循 GLOSSARY（任务 / 轮次 / 结构化方案 / 待确认事项 / 成品 / 方案确认）。
 * 权威来源：backend/app/models/history.py::ResumeNext。
 */
import type { ResumeNext, TaskStatus } from '../api/client'

/** awaiting → 一句话「停在哪一步」。 */
export function awaitingLabel(a: ResumeNext): string {
  switch (a) {
    case 'answers':
      return '停在拷问中途 · 待作答'
    case 'advance':
      return '本轮已答 · 待推进或收敛'
    case 'plan_confirm':
      return '已有结构化方案 · 待方案确认'
    case 'generation':
      return '方案已确认 · 待生成成品'
    case 'completed':
      return '已完成'
    case 'deleted':
      return '已删除 · 仅留痕'
    default:
      return a
  }
}

/** awaiting → 列表「继续」按钮文案；返回 null 表示不提供续作入口。 */
export function awaitingActionLabel(a: ResumeNext): string | null {
  switch (a) {
    case 'answers':
      return '继续作答'
    case 'advance':
      return '继续推进'
    case 'plan_confirm':
      return '去确认方案'
    case 'generation':
      return '打开成品'
    default:
      return null
  }
}

/** 创作页续作提示：awaiting → 补充说明。 */
export function awaitingResumeHint(a: ResumeNext): string {
  switch (a) {
    case 'answers':
      return '已在停下的那一轮，继续作答即可。'
    case 'advance':
      return '本轮已答完，点「推进下一轮 / 收敛」继续。'
    case 'plan_confirm':
      return '处置完待确认事项后，在方案卡下方确认。'
    case 'generation':
      return '方案已确认；成品生成由 TB-5 / TB-6 落地，此处不提供可用假象。'
    case 'completed':
      return '任务已完成，可回看对话与方案。'
    case 'deleted':
      return '该任务已软删除，仅留痕可回看，不再出现在历史列表。'
    default:
      return ''
  }
}

/** 任务状态 → 点色（与 taskMeta 的 statusDotClass 一致，历史条目复用）。 */
export function statusFromTask(status: TaskStatus): { label: string; dot: string } {
  switch (status) {
    case 'in_progress':
      return { label: '进行中', dot: 'tf-dot--run' }
    case 'completed':
      return { label: '已完成', dot: 'tf-dot--ok' }
    case 'deleted':
      return { label: '已删除', dot: 'tf-dot--err' }
    default:
      return { label: String(status), dot: '' }
  }
}

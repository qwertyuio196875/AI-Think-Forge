/**
 * 任务展示辅助：把后端状态 / 类型映射为术语表词汇与状态点样式。
 * 命名遵循 GLOSSARY.md（主题创作 / 资料分析 / 任务 / 方案确认 / 成品）。
 * v1 后端 status 为自由字符串，这里对已知值取中文，未知值原样回退。
 */
import type { TaskKind, TaskStatus } from '../api/client'

const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  grilling: '拷问进行中',
  in_progress: '拷问进行中',
  waiting_confirm: '待方案确认',
  pending: '待方案确认',
  awaiting_confirm: '待方案确认',
  confirmed: '方案已确认',
  generating: '生成中',
  processing: '生成中',
  done: '已完成',
  completed: '已完成',
  failed: '生成失败',
  error: '生成失败',
  paused: '已中断',
  interrupted: '已中断',
  cancelled: '已取消'
}

const STATUS_DOT: Record<string, string> = {
  grilling: 'tf-dot--run',
  in_progress: 'tf-dot--run',
  generating: 'tf-dot--run',
  processing: 'tf-dot--run',
  waiting_confirm: 'tf-dot--warn',
  pending: 'tf-dot--warn',
  awaiting_confirm: 'tf-dot--warn',
  confirmed: 'tf-dot--warn',
  done: 'tf-dot--ok',
  completed: 'tf-dot--ok',
  failed: 'tf-dot--err',
  error: 'tf-dot--err'
}

export function statusLabel(status: TaskStatus): string {
  return STATUS_LABELS[status] ?? status
}

/** 返回状态修饰类（基础类 tf-dot 由模板静态给出）。草稿等默认返回空串。 */
export function statusDotClass(status: TaskStatus): string {
  return STATUS_DOT[status] ?? ''
}

export function kindLabel(kind: TaskKind): string {
  return kind === 'creation' ? '主题创作' : '资料分析'
}

/** ISO 时间 → 「10 月 19 日 14:58」；解析失败原样返回。 */
export function formatDateTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日 ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

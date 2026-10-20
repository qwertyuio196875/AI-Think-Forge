/**
 * 任务展示辅助：把后端状态 / 类型映射为术语表词汇与状态点样式。
 * 命名遵循 GLOSSARY.md（主题创作 / 资料分析 / 任务 / 方案确认 / 成品）。
 * v1 后端 status 为自由字符串，这里对已知值取中文，未知值原样回退。
 */
import type { TaskKind, TaskStatus } from '../api/client'

const STATUS_LABELS: Record<string, string> = {
  in_progress: '进行中',
  completed: '已完成',
  deleted: '已删除'
}

const STATUS_DOT: Record<string, string> = {
  in_progress: 'tf-dot--run',
  completed: 'tf-dot--ok',
  deleted: 'tf-dot--err'
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

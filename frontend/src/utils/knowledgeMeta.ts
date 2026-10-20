/**
 * 知识库清单页的纯展示辅助（工单 19）。
 *
 * 术语以 GLOSSARY 为准：**知识库** = 用户显式添加的本地资料集合，含分块与检索索引；
 * 上传即入库，索引状态（已入库 / 索引中 / 索引失败）必须对用户可见。
 *
 * 与后端契约逐一对齐（backend/app/models/knowledge.py）：
 * - 索引状态取值域：`stored` / `indexing` / `failed`；
 *   `indexing` 由工单 20（嵌入与向量写入）在重建索引期间写入，
 *   `failed` 也可能是「分块已入库但向量没写成」——资料仍可读、检索降级，
 *   清单页必须把三态都显示出来，否则界面会漏状态。
 * - `index_message`：失败原因（解析失败 / 未识别到文本 / 向量索引失败 / 重建索引失败等）。
 *
 * 这里是纯函数（无 IO、无组件依赖），由 `node --test tests/` 直接执行验证。
 */

/** Element Plus 标签色调，与资料分析页保持一致。 */
export type IndexTagType = 'success' | 'warning' | 'danger' | 'info'

/** 索引状态取值域，固定顺序（清单页筛选用）。 */
export const INDEX_STATUS_ORDER = ['stored', 'indexing', 'failed'] as const

/**
 * 索引状态 → 中文标签与色调。
 *
 * `failed` 必须是 `danger`：解析 / 索引失败若与「已入库」同色，用户会以为资料
 * 已经能参与检索（验收②要求失败状态明确可见）。未知值原样显示为中性标签，
 * 绝不猜成「已入库」。
 */
export function indexStatusTag(status: string): {
  label: string
  type: IndexTagType
} {
  if (status === 'stored') return { label: '已入库', type: 'success' }
  if (status === 'indexing') return { label: '索引中', type: 'warning' }
  if (status === 'failed') return { label: '索引失败', type: 'danger' }
  return { label: status, type: 'info' }
}

/** 清单行的最小形状（与后端 KnowledgeSourceItem 对齐）。 */
export interface KnowledgeRowLike {
  index_status: string
  index_message: string | null
}

/**
 * 索引状态的补充说明：失败时把原因原样给出。
 *
 * 失败但后端没给原因时也要说点什么（「原因未记录」），空白会让人以为没失败。
 * 已入库 / 索引中即使残留旧文案也不展示，避免成功项挂着历史错误。
 */
export function indexStatusDetail(row: KnowledgeRowLike): string {
  if (row.index_status !== 'failed') return ''
  const message = (row.index_message ?? '').trim()
  return message || '索引失败，原因未记录'
}

/**
 * 分块数的可读展示：`N 块`。
 *
 * 缺失（尚未解析 / 后端未返回）显示 `—`，不显示 `0 块`——两者含义不同：
 * 「没解析出来」和「解析了但切出 0 块」不能混为一谈。
 */
export function formatChunkCount(count: number | null | undefined): string {
  if (typeof count !== 'number' || !Number.isFinite(count)) return '—'
  return `${count} 块`
}

/** 清单行的名称字段形状。 */
export interface KnowledgeNameLike {
  name: string
  ref: string
}

/**
 * 清单行名称：文件名优先，其次原始相对路径（便于排查），都没有时给固定占位。
 * 不编造标题，也不显示空白行。
 */
export function knowledgeDisplayName(row: KnowledgeNameLike): string {
  const name = (row.name ?? '').trim()
  if (name) return name
  const ref = (row.ref ?? '').trim()
  if (ref) return ref
  return '未命名资料'
}

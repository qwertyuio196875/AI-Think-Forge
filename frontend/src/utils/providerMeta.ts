/**
 * 模型配置展示辅助：档位角色标签与连接测试结果的中文可读化。
 * 命名遵循 GLOSSARY.md（模型配置 / 连接测试）。
 * 权威依据：03-deepseek-facts.md §5 错误分类 + TB-1 契约的 category。
 */
import type { ConnectionTestResult, ProviderKind } from '../api/client'

export function kindLabel(kind: ProviderKind): string {
  switch (kind) {
    case 'plus':
      return '主流程'
    case 'turbo':
      return '总结流程'
    case 'max':
      return '任务级深问'
    default:
      return '未分档'
  }
}

export interface ConnectionReport {
  /** 展示语气：成功 / 可稍后重试 / 需修正。 */
  level: 'ok' | 'warn' | 'err'
  /** 一句话结论（中文）。 */
  title: string
  /** 补充说明（含可重试提示与服务商原始返回）。 */
  detail: string
}

/** category → 文案配置（内部用，retryable 仅决定补充提示语气）。 */
interface CategoryText {
  level: 'ok' | 'warn' | 'err'
  title: string
  retryable: boolean
}

/** category → 清晰可读中文原因。绝不直接展示 category 字符串。 */
const CATEGORY_TEXT: Record<string, CategoryText> = {
  ok: { level: 'ok', title: '连接成功', retryable: false },
  network_error: {
    level: 'warn',
    title: '无法连接到该地址（网络不可达或地址有误）',
    retryable: true
  },
  auth_error: {
    level: 'err',
    title: '鉴权失败：API 密钥无效或已过期',
    retryable: false
  },
  model_error: {
    level: 'err',
    title: '模型名无效：该服务商下不存在此模型',
    retryable: false
  },
  insufficient_balance: {
    level: 'err',
    title: '余额不足：该服务商账户余额已用尽',
    retryable: false
  },
  rate_limited: {
    level: 'warn',
    title: '触发限流：并发或请求频率超限',
    retryable: true
  },
  request_error: {
    level: 'err',
    title: '请求参数有误：配置内容被服务商拒绝',
    retryable: false
  },
  server_error: {
    level: 'warn',
    title: '服务商服务端错误',
    retryable: true
  }
}

export function describeConnection(result: ConnectionTestResult): ConnectionReport {
  const mapped = CATEGORY_TEXT[result.category] ?? {
    level: 'err' as const,
    title: `连接失败（${result.category || '未知错误'}）`,
    retryable: false
  }
  const parts: string[] = []
  if (result.message && result.message.trim()) parts.push(result.message.trim())
  if (mapped.retryable) parts.push('这类问题多为临时性的，可稍后重试。')
  if (result.category === 'network_error') parts.push('请核对 Base URL 是否可被本机访问。')
  if (result.category === 'auth_error') parts.push('请在「编辑」中重新填写 API 密钥。')
  if (result.category === 'model_error') parts.push('请核对模型名（DeepSeek 当前有效：deepseek-flash / deepseek-v4-pro）。')
  return { level: mapped.level, title: mapped.title, detail: parts.join(' ') }
}

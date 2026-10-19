/**
 * ThinkForge 后端 API 客户端。
 *
 * 后端约定：FastAPI 单进程，仅监听 http://127.0.0.1:8720，业务接口前缀 /api。
 * 前端不做代理，直连该地址（见工单 02）。
 */

export const API_BASE_URL = 'http://127.0.0.1:8720/api'

/** 后端健康检查响应（GET /api/health）。 */
export interface HealthResponse {
  status: string
  [key: string]: unknown
}

/** 后端未启动或网络不可达时抛出的错误。 */
export class BackendUnavailableError extends Error {
  constructor(message = '后端未启动') {
    super(message)
    this.name = 'BackendUnavailableError'
  }
}

/**
 * 统一 fetch 封装：拼接 base、解析 JSON、把网络/非 2xx 归为一类错误。
 */
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = path.startsWith('http') ? path : `${API_BASE_URL}${path}`
  let response: Response
  try {
    response = await fetch(url, {
      headers: {
        Accept: 'application/json',
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers
      },
      ...init
    })
  } catch {
    // fetch 抛错通常意味着后端未启动 / 端口不通。
    throw new BackendUnavailableError()
  }

  if (!response.ok) {
    throw new Error(`请求失败：${response.status} ${response.statusText}`)
  }

  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

/** 健康检查：GET /api/health。 */
export function checkHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health')
}

export default {
  API_BASE_URL,
  checkHealth,
  request
}
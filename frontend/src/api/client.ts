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

/* ============================================================
   任务（Task）—— TB-0 行走骨架的最小契约
   权威来源：TB-0 工单「后端 API 契约」。业务字段随后续工单扩展。
   ============================================================ */

/** 任务类型：主题创作 / 资料分析。 */
export type TaskKind = 'creation' | 'analysis'

/** 任务状态。v1 后端返回字符串（如 draft / grilling / confirmed / done），前端按原样展示。 */
export type TaskStatus = string

/** 任务对象（POST/GET /api/tasks 返回体）。 */
export interface Task {
  id: string
  kind: TaskKind
  title: string | null
  status: TaskStatus
  created_at: string
  updated_at: string
}

/** GET /api/tasks 列表返回体。 */
export interface TaskListResponse {
  items: Task[]
  total: number
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

/** 新建任务：POST /api/tasks。 */
export function createTask(input: { kind: TaskKind; title?: string }): Promise<Task> {
  return request<Task>('/tasks', {
    method: 'POST',
    body: JSON.stringify(input)
  })
}

/** 任务列表：GET /api/tasks?kind=&status=。参数为空则不带对应查询串。 */
export function listTasks(params?: {
  kind?: TaskKind
  status?: TaskStatus
}): Promise<TaskListResponse> {
  const query = new URLSearchParams()
  if (params?.kind) query.set('kind', params.kind)
  if (params?.status) query.set('status', params.status)
  const qs = query.toString()
  return request<TaskListResponse>(qs ? `/tasks?${qs}` : '/tasks')
}

/** 按 id 读取任务：GET /api/tasks/{id}。404 会走 request 的非 2xx 抛出。 */
export function getTask(id: string): Promise<Task> {
  return request<Task>(`/tasks/${encodeURIComponent(id)}`)
}

export default {
  API_BASE_URL,
  checkHealth,
  request,
  createTask,
  listTasks,
  getTask
}
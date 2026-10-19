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

/* ============================================================
   模型配置（Provider）与连接测试 —— TB-1
   权威来源：TB-1 工单「后端 API 契约」。响应体永不含密钥，仅 has_key。
   api_key 为只写字段：提交后不落任何前端持久化（localStorage/sessionStorage/日志）。
   ============================================================ */

/** 档位为角色标签（可空）：turbo=总结流程 / plus=主流程 / max=任务级深问。 */
export type ProviderKind = 'turbo' | 'plus' | 'max' | null

/** 模型配置对象（不含密钥；密钥状态只以 has_key 表达）。 */
export interface Provider {
  id: string
  name: string
  base_url: string
  model_name: string
  is_default: boolean
  kind: ProviderKind
  has_key: boolean
}

/** GET /api/providers 列表返回体。 */
export interface ProviderListResponse {
  items: Provider[]
  total: number
}

/** 新增 / 编辑提交的字段。api_key 留空即不携带（编辑时保留原凭据）。 */
export interface ProviderInput {
  name: string
  base_url: string
  model_name: string
  kind?: ProviderKind
  api_key?: string
}

/** 连接测试结果。category ∈ ok|network_error|auth_error|model_error|insufficient_balance|rate_limited|request_error|server_error。 */
export interface ConnectionTestResult {
  ok: boolean
  category: string
  message: string
}

/** 组装 provider 请求体：去掉 undefined / 空 api_key（只写字段，空即不发送）。 */
function buildProviderBody(input: ProviderInput): string {
  return JSON.stringify({
    name: input.name,
    base_url: input.base_url,
    model_name: input.model_name,
    kind: input.kind ?? undefined,
    api_key: input.api_key && input.api_key.length > 0 ? input.api_key : undefined
  })
}

/** 模型配置列表：GET /api/providers。 */
export function listProviders(): Promise<ProviderListResponse> {
  return request<ProviderListResponse>('/providers')
}

/** 新增模型配置：POST /api/providers（重名 409）。 */
export function createProvider(input: ProviderInput): Promise<Provider> {
  return request<Provider>('/providers', { method: 'POST', body: buildProviderBody(input) })
}

/** 编辑模型配置：PUT /api/providers/{id}（api_key 不传即保留原凭据）。 */
export function updateProvider(id: string, input: ProviderInput): Promise<Provider> {
  return request<Provider>(`/providers/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: buildProviderBody(input)
  })
}

/** 删除模型配置：DELETE /api/providers/{id}（204，同时清除该配置的凭据）。 */
export function deleteProvider(id: string): Promise<void> {
  return request<void>(`/providers/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

/** 设为全局默认：POST /api/providers/{id}/default。 */
export function setDefaultProvider(id: string): Promise<Provider> {
  return request<Provider>(`/providers/${encodeURIComponent(id)}/default`, { method: 'POST' })
}

/** 连接测试：POST /api/providers/{id}/test。 */
export function testProvider(id: string): Promise<ConnectionTestResult> {
  return request<ConnectionTestResult>(`/providers/${encodeURIComponent(id)}/test`, {
    method: 'POST'
  })
}

export default {
  API_BASE_URL,
  checkHealth,
  request,
  createTask,
  listTasks,
  getTask,
  listProviders,
  createProvider,
  updateProvider,
  deleteProvider,
  setDefaultProvider,
  testProvider
}
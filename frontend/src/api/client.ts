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
 * 非 2xx 响应错误：状态码与后端可读 detail 各自成字段。
 *
 * 消息格式与既有实现一致（`请求失败：<code> <statusText> · <detail>`），
 * 调用方不再需要用 `String(error).includes('404')` 反解析状态码，
 * 改用 `isApiStatus(error, 404)` 判定（避免 detail 文案里出现数字导致误判）。
 */
export class ApiHttpError extends Error {
  /** HTTP 状态码（如 404 / 409 / 500）。 */
  readonly status: number
  /** FastAPI 的可读 detail（无则为空串）。 */
  readonly detail: string

  constructor(status: number, statusText: string, detail: string) {
    const base = `请求失败：${status} ${statusText}`.trimEnd()
    super(detail ? `${base} · ${detail}` : base)
    this.name = 'ApiHttpError'
    this.status = status
    this.detail = detail
  }
}

/** 错误是否为指定 HTTP 状态码（后端未启动 / 网络错误恒为 false）。 */
export function isApiStatus(error: unknown, status: number): boolean {
  return error instanceof ApiHttpError && error.status === status
}

/* ============================================================
   任务（Task）—— TB-0 行走骨架的最小契约
   权威来源：TB-0 工单「后端 API 契约」。业务字段随后续工单扩展。
   ============================================================ */

/** 任务类型：主题创作 / 资料分析。 */
export type TaskKind = 'creation' | 'analysis'

/**
 * 任务状态。以后端 `app/models/task.py::TaskStatus` 为准：
 * in_progress / completed / deleted；保留 string 兜底以防后续扩展。
 */
export type TaskStatus = 'in_progress' | 'completed' | 'deleted' | (string & {})

/** 任务对象（POST/GET /api/tasks 返回体；id 为后端自增整数）。 */
export interface Task {
  id: number
  kind: TaskKind
  title: string | null
  /**
   * 任务级模型覆盖（US23）：null = 未覆盖，按默认档位解析；
   * 非空为该 provider 的 id，拷问 / 方案 / 修订与资料分析总结都读它。
   */
  provider_id: number | null
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
    // 附带 FastAPI 的可读 detail（若有），让 400/409/500 等原因在前端可直接展示；
    // 状态码同时以字段形式给出（isApiStatus 判定），消息格式保持「请求失败：<code> …」不变。
    let detail = ''
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (body && typeof body.detail === 'string') detail = body.detail
    } catch {
      // 非 JSON 错误体（如纯文本）忽略
    }
    throw new ApiHttpError(response.status, response.statusText, detail)
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

/** 新建任务：POST /api/tasks（可带任务级模型覆盖 provider_id）。 */
export function createTask(input: {
  kind: TaskKind
  title?: string
  provider_id?: number | null
}): Promise<Task> {
  return request<Task>('/tasks', {
    method: 'POST',
    body: JSON.stringify({
      kind: input.kind,
      title: input.title,
      provider_id: input.provider_id ?? null
    })
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
export function getTask(id: number): Promise<Task> {
  return request<Task>(`/tasks/${id}`)
}

/**
 * 设置 / 清除任务级模型覆盖：PUT /api/tasks/{id}/model（US23）。
 * `providerId = null` 回到默认档位；响应为更新后的完整任务。
 * 404 任务不存在 / 400 模型配置不存在 / 409 任务已删除。
 */
export function updateTaskModel(taskId: number, providerId: number | null): Promise<Task> {
  return request<Task>(`/tasks/${taskId}/model`, {
    method: 'PUT',
    body: JSON.stringify({ provider_id: providerId })
  })
}

/* ============================================================
   模型配置（Provider）与连接测试 —— TB-1
   权威来源：TB-1 工单「后端 API 契约」。响应体永不含密钥，仅 has_key。
   api_key 为只写字段：提交后不落任何前端持久化（localStorage/sessionStorage/日志）。
   ============================================================ */

/** 档位为角色标签（可空）：turbo=总结流程 / plus=主流程 / max=任务级深问。 */
export type ProviderKind = 'turbo' | 'plus' | 'max' | null

/** 模型配置对象（不含密钥；密钥状态只以 has_key 表达）。id 为后端自增整数。 */
export interface Provider {
  id: number
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
export function updateProvider(id: number, input: ProviderInput): Promise<Provider> {
  return request<Provider>(`/providers/${id}`, {
    method: 'PUT',
    body: buildProviderBody(input)
  })
}

/** 删除模型配置：DELETE /api/providers/{id}（204，同时清除该配置的凭据）。 */
export function deleteProvider(id: number): Promise<void> {
  return request<void>(`/providers/${id}`, { method: 'DELETE' })
}

/** 设为全局默认：POST /api/providers/{id}/default。 */
export function setDefaultProvider(id: number): Promise<Provider> {
  return request<Provider>(`/providers/${id}/default`, { method: 'POST' })
}

/** 连接测试：POST /api/providers/{id}/test。 */
export function testProvider(id: number): Promise<ConnectionTestResult> {
  return request<ConnectionTestResult>(`/providers/${id}/test`, {
    method: 'POST'
  })
}

/* ============================================================
   拷问（Grilling）—— TB-2 第一轮
   权威来源：backend/app/models/grilling.py（逐字段对齐）。
   前沿问题集内嵌在 assistant 消息里，但后端已在 /dialogue 的 rounds[].frontier 解析为结构；
   前端只消费 rounds / seed_input，不自行解析 message.content。
   ============================================================ */

/**
 * 一条引用卡片（工单 23）：文件名 · 段落号 · 相关度，可折叠、默认采用。
 *
 * 与 backend/app/models/grilling.py::CitationCard 逐字段对齐。
 * `adopted` 默认 true（规格：默认全选、逐条可取消）；`collapsible` 由后端给，
 * 前端不自己判断「这条能不能折叠」——展示形态是后端契约的一部分。
 */
export interface CitationCard {
  chunk_id: number
  document_id: number
  source_id: number
  /** 文件名（展示用）。 */
  name: string
  /** 该资料内的分块序号。 */
  seq: number
  /** 相关度（0–1）。 */
  similarity: number
  /** 段落号；PDF / PPT 类资料可能为空（用页 / 幻灯片定位）。 */
  paragraph: number | null
  /** 可读定位标签，前端直接显示，不自己拼。 */
  locator_label: string
  /** 将注入的正文片段（折叠时隐藏）。 */
  text: string
  adopted: boolean
  collapsible: boolean
}

/** 本次检索的状态（降级 / 未使用知识库时必须明示，不静默隐藏）。 */
export interface RetrievalStatusInfo {
  status: string
  status_label: string
  message: string | null
  degraded: boolean
  truncated: boolean
}

/**
 * 前沿中的一个问题：标题、正文、推荐答案，以及 TB-4 新增的
 * `why`（为什么现在问，缺失为 null）与 `alternatives`（备选方向，缺失为空列表）。
 * 工单 23 追加 `citations`（引用卡片）与 `retrieval_status`（检索状态）。
 * 与 backend/app/models/grilling.py::FrontierQuestion 逐字段对齐。
 */
export interface FrontierQuestion {
  title: string
  body: string
  recommended_answer: string
  why: string | null
  alternatives: string[]
  /** 引用卡片：决策型问题恒为空清单（判定过、不需要检索）。 */
  citations: CitationCard[]
  /** 检索状态：未检索 / 决策型时为 null。 */
  retrieval_status: RetrievalStatusInfo | null
}

/**
 * 一个轮次：该轮前沿问题集 + 用户回答。
 * 注意：后端把「暂时跳过」的答案以占位串 `（暂时跳过）` 落库以保持按位对齐，
 * 因此这里 answers 仍是 string[]；用 SKIP_ANSWER_MARKER 判定某题是否被跳过。
 */
export interface FrontierRound {
  round_no: number
  frontier: FrontierQuestion[]
  answers: string[]
}

/** 「暂时跳过」在消息表中的占位串（与 backend/app/grilling/open_items.py 一致）。 */
export const SKIP_ANSWER_MARKER = '（暂时跳过）'

/** 某条回答是否为「暂时跳过」（后端把 null / 纯空白 / 占位都归为跳过）。 */
export function isSkipAnswer(answer: string | null | undefined): boolean {
  if (answer === null || answer === undefined) return true
  const t = answer.trim()
  return t === '' || t === SKIP_ANSWER_MARKER
}

/** 对话流中的一条原始消息（role: system | assistant | user）。 */
export interface DialogueMessage {
  id: number
  round_no: number
  role: string
  content: string
  created_at: string
}

/** 某任务的完整对话状态：种子输入 + 各轮次 + 原始消息。 */
export interface Dialogue {
  task_id: number
  seed_input: string | null
  rounds: FrontierRound[]
  messages: DialogueMessage[]
}

/** 发起结果：新建任务 + 第一轮前沿。 */
export interface GrillingStartResponse {
  task: Task
  round: FrontierRound
}

/**
 * 发起主题创作：POST /api/grilling/tasks（一句话 / 一段描述 → 第一轮前沿）。
 * `providerId` 为该任务选定的模型配置（US23 任务级覆盖）；不传 / null 走默认档位。
 */
export function startGrillingTask(
  idea: string,
  providerId?: number | null
): Promise<GrillingStartResponse> {
  return request<GrillingStartResponse>('/grilling/tasks', {
    method: 'POST',
    body: JSON.stringify({ idea, provider_id: providerId ?? null })
  })
}

/**
 * 提交某轮回答：POST /api/grilling/tasks/{id}/answers（数量须与前沿问题一致）。
 * answers 项为 null（或纯空白）= 该题「暂时跳过」，入待确认事项、保持未定。返回写后对话状态。
 *
 * `rejectedChunkIds`（工单 23）：本次**取消采用**的引用片段。引用卡片默认全选、
 * 逐条可取消；取消过的片段必须带上来，后端会确保它们不进本次提示词——
 * 否则「界面上取消了、实际仍喂给了模型」，用户看到的与发生的就成了两回事。
 */
export function submitAnswers(
  taskId: number,
  roundNo: number,
  answers: Array<string | null>,
  rejectedChunkIds: number[] = []
): Promise<Dialogue> {
  return request<Dialogue>(`/grilling/tasks/${taskId}/answers`, {
    method: 'POST',
    body: JSON.stringify({ round_no: roundNo, answers, rejected_chunk_ids: rejectedChunkIds })
  })
}

/** 读取对话：GET /api/grilling/tasks/{id}/dialogue（复原轮次与问答顺序）。 */
export function getDialogue(taskId: number): Promise<Dialogue> {
  return request<Dialogue>(`/grilling/tasks/${taskId}/dialogue`)
}

/* ============================================================
   收敛 → 结构化方案 → 确认闸门（TB-3）
   权威来源：backend/app/models/{grilling,plan}.py、routes/{grilling,generations}.py
   ============================================================ */

/** 方案状态：草稿 / 已确认（方案确认是进入生成阶段的唯一闸门）。 */
export type PlanStatus = 'draft' | 'confirmed'

/** 结构化方案（content_md 为 Markdown 正文；confirmed_at 未确认为 null）。 */
export interface Plan {
  id: number
  task_id: number
  round_no: number
  content_md: string
  status: PlanStatus
  confirmed_at: string | null
}

/** 一次推进的结果：下一轮前沿，或收敛产出的方案草稿。 */
export interface AdvanceResponse {
  task_id: number
  converged: boolean
  next_round: FrontierRound | null
  plan: Plan | null
}

/** 推进轮次：POST /api/grilling/tasks/{id}/advance（无请求体；按上轮回答重算下一轮，收敛则出方案草稿）。 */
export function advanceGrilling(taskId: number): Promise<AdvanceResponse> {
  return request<AdvanceResponse>(`/grilling/tasks/${taskId}/advance`, { method: 'POST' })
}

/** 取结构化方案：GET /api/grilling/tasks/{id}/plan（尚无方案时后端 404）。 */
export function getPlan(taskId: number): Promise<Plan> {
  return request<Plan>(`/grilling/tasks/${taskId}/plan`)
}

/** 方案确认：POST /api/grilling/tasks/{id}/plan/confirm（draft→confirmed，幂等）。 */
export function confirmPlan(taskId: number): Promise<Plan> {
  return request<Plan>(`/grilling/tasks/${taskId}/plan/confirm`, { method: 'POST' })
}

/**
 * 请求生成成品：POST /api/tasks/{id}/generations。
 * 服务端硬闸门：无方案 / 未确认 / 有未处置待确认事项 → 409；
 * Word：模板缺失 / 非 .docx → 400；HTML：未知主题 → 400（不静默退回默认）；
 * 完整性检查未过（HTML 含外部网络引用亦 500）→ 500 且产物已丢弃。通过后 201 + 记录 + 产物元数据。
 */
export function generateDeliverable(
  taskId: number,
  req: GenerationRequest = {}
): Promise<GenerationResponse> {
  return request<GenerationResponse>(`/tasks/${taskId}/generations`, {
    method: 'POST',
    body: JSON.stringify({
      format: req.format ?? 'docx',
      template: req.template && req.template.length > 0 ? req.template : null,
      theme: req.theme && req.theme.length > 0 ? req.theme : null
    })
  })
}

/* ============================================================
   成品（generation）/ 模板（template）TB-5 · 单文件 HTML 演示 TB-6
   权威来源：backend/app/models/generation.py、routes/{generations,templates,deck,deliverables}.py
   术语：成品 / 单文件 HTML / 模板 / 默认模板 / 临时覆盖（临时选择不改变全局默认）。
   ============================================================ */

/**
 * 成品格式（工单 29/30/31：Word / 单文件 HTML / 截图版 PPT / 可选 PDF）。
 * 后三者同源（ADR-0004）：HTML 与截图版 PPT、PDF 都由同一份 deck 导出；Word 走模板。
 */
export type GenerationFormat = 'docx' | 'html' | 'pptx' | 'pdf'

/** 生成记录（GET 列表项的字段集）。 */
export interface Generation {
  id: number
  task_id: number
  plan_id: number
  format: GenerationFormat
  file_path: string
  template_used: string
  created_at: string
}

/** 生成结果：记录 + 产物元数据（Word 与 HTML 两轨共用，另一轨取默认值）。 */
export interface GenerationResponse extends Generation {
  // Word 轨
  template_style_applied: boolean
  missing_styles: string[]
  headings: number
  integrity_ok: boolean
  // HTML 轨（TB-6）
  theme_used: string | null
  inlined_fonts: string[]
  cjk_fallback: boolean
  slides: number
  external_resources: string[]
  network_resources_declared: string[]
  presenter_mode: string | null
}

/** 某任务的成品列表。 */
export interface GenerationListResponse {
  items: Generation[]
  total: number
}

/** 生成请求：格式 + Word 任务级临时覆盖模板 + HTML 演示主题（后两者都不改全局默认）。 */
export interface GenerationRequest {
  format?: GenerationFormat
  template?: string | null
  theme?: string | null
}

/** 模板条目：名称 / 格式 / 是否全局默认 / 是否内置 / 可用 / 已登记 / 文件已缺失。 */
export interface Template {
  name: string
  format: string
  is_default: boolean
  builtin: boolean
  usable: boolean
  registered: boolean
  missing: boolean
}

/** 模板清单。 */
export interface TemplateListResponse {
  items: Template[]
  total: number
}

/** 登记 / 设默认结果：模板条目 + 该格式当前生效的全局默认名。 */
export interface TemplateRegisterResponse {
  template: Template
  default_template: string | null
}

/** 某任务的成品记录列表：GET /api/tasks/{id}/generations。 */
export function listGenerations(taskId: number): Promise<GenerationListResponse> {
  return request<GenerationListResponse>(`/tasks/${taskId}/generations`)
}

/** 模板清单：GET /api/templates（以模板目录实际情况为准）。 */
export function getTemplates(): Promise<TemplateListResponse> {
  return request<TemplateListResponse>('/templates')
}

/** 登记模板：POST /api/templates（只接受已放入 templates/ 的 .docx；非 .docx → 400）。 */
export function registerTemplate(
  name: string,
  isDefault = false
): Promise<TemplateRegisterResponse> {
  return request<TemplateRegisterResponse>('/templates', {
    method: 'POST',
    body: JSON.stringify({ name, is_default: isDefault })
  })
}

/** 设为全局默认模板：PUT /api/templates/{name}/default（同格式至多一个默认）。 */
export function setDefaultTemplate(name: string): Promise<TemplateRegisterResponse> {
  return request<TemplateRegisterResponse>(
    `/templates/${encodeURIComponent(name)}/default`,
    { method: 'PUT' }
  )
}

/** 演示主题调色板（键与后端 `theme_catalog()` 一致：bg / fg / accent / line / muted）。 */
export interface DeckPalette {
  bg: string
  fg: string
  accent: string
  line: string
  muted: string
  [key: string]: string
}

/** 演示主题条目（GET /api/deck-themes，与生成入口同一份事实；前端不硬编码色板）。 */
export interface DeckTheme {
  id: string
  name: string
  palette: DeckPalette
  fonts: string[]
  cjk_fallback: boolean
  derived_from: string
  license: string
  network_resources: string[]
}

/** 主题族清单。 */
export interface DeckThemeListResponse {
  items: DeckTheme[]
  total: number
  cjk_fallback: boolean
}

/** 演示主题族清单：GET /api/deck-themes。 */
export function getDeckThemes(): Promise<DeckThemeListResponse> {
  return request<DeckThemeListResponse>('/deck-themes')
}

/** HTML 演示的全局默认主题（GET/PUT /api/settings/deck-theme）。 */
export interface DeckThemeSettings {
  /** 当前生效的全局默认主题 id。 */
  theme: string
  /** 后端认可的主题 id 清单（按内建顺序）。 */
  available: string[]
}

/** 读取 HTML 演示的全局默认主题。 */
export function getDeckThemeDefault(): Promise<DeckThemeSettings> {
  return request<DeckThemeSettings>('/settings/deck-theme')
}

/**
 * 写入 HTML 演示的全局默认主题：PUT /api/settings/deck-theme。
 * 未知主题 400（后端不写入任何值，也不静默退回默认）。
 */
export function setDeckThemeDefault(theme: string): Promise<DeckThemeSettings> {
  return request<DeckThemeSettings>('/settings/deck-theme', {
    method: 'PUT',
    body: JSON.stringify({ theme })
  })
}

/* ---------- 成品投递（GET /api/deliverables/{id}）----------
   浏览器 http 页无法加载 file://，产物由后端按 generation id 投递：
   HTML=inline（可应用内预览），Word=attachment（下载）。缺失 / 越界一律 404。 */

/** 按 id 取产物原始响应（用于下载）；非 2xx 不解析 JSON，交由调用方按 status 处理。 */
export async function fetchDeliverable(generationId: number): Promise<Response> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/deliverables/${generationId}`)
  } catch {
    throw new BackendUnavailableError()
  }
  return response
}

/** 按 id 取产物文本（HTML 预览用）；404 / 不可用 → DeliverableUnavailableError。 */
export async function fetchDeliverableHtml(generationId: number): Promise<string> {
  const response = await fetchDeliverable(generationId)
  if (response.status === 404) throw new DeliverableUnavailableError()
  if (!response.ok) throw new Error(`读取产物失败：${response.status}`)
  return await response.text()
}

/** 产物投递端点不可用 / 文件缺失（404）时抛出，供前端如实降级。 */
export class DeliverableUnavailableError extends Error {
  constructor(message = '产物暂不可用') {
    super(message)
    this.name = 'DeliverableUnavailableError'
  }
}

/** 触发浏览器下载某成品（Word 等）：先取回再存盘，借 Content-Disposition 文件名。 */
export async function downloadDeliverable(
  generationId: number,
  fallbackName: string
): Promise<void> {
  const response = await fetchDeliverable(generationId)
  if (response.status === 404) throw new DeliverableUnavailableError()
  if (!response.ok) throw new Error(`打开失败：${response.status}`)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filenameFromDisposition(response.headers.get('Content-Disposition')) || fallbackName
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** 从 Content-Disposition 头解析文件名（优先 RFC 5987 的 filename*=UTF-8''…）。 */
function filenameFromDisposition(header: string | null): string {
  if (!header) return ''
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (star) {
    try {
      return decodeURIComponent(star[1])
    } catch {
      /* 回退到 filename= */
    }
  }
  const plain = /filename="([^"]*)"/i.exec(header)
  return plain ? plain[1] : ''
}

/* ============================================================
   方案对话式修订 与 待确认事项 —— TB-4
   权威来源：backend/app/models/{plan,open_items}.py、routes/grilling.py
   ============================================================ */

/** 差异提示的一条改动类型。 */
export type PlanChangeKind = 'added' | 'removed' | 'modified'

/** 差异提示的一条：被改动的章节。 */
export interface PlanChange {
  kind: PlanChangeKind
  heading: string
}

/** 一次方案修订的版本记录（修订前 / 后正文 + 差异提示 + 时间）。 */
export interface PlanRevision {
  id: number
  plan_id: number
  task_id: number
  instruction: string
  previous_content_md: string
  content_md: string
  change_summary: PlanChange[]
  created_at: string
}

/** 修订结果：更新后的方案（回到 draft）+ 本次版本记录。 */
export interface PlanRevisionResponse {
  plan: Plan
  revision: PlanRevision
}

/** 方案修订历史。 */
export interface PlanRevisionListResponse {
  items: PlanRevision[]
  total: number
}

/** 待确认事项状态。 */
export type OpenItemStatus = 'open' | 'confirmed' | 'dismissed'

/** 处置允许的终态（open 不是处置结果）。 */
export type ResolveStatus = 'confirmed' | 'dismissed'

/** 一条待确认事项。 */
export interface OpenItem {
  id: number
  task_id: number
  round_no: number
  text: string
  status: OpenItemStatus
  created_at: string
  resolved_at: string | null
}

/** 待确认事项清单。 */
export interface OpenItemListResponse {
  items: OpenItem[]
  total: number
}

/** 对话式修订方案：POST /api/grilling/tasks/{id}/plan/revisions（body {instruction}）。 */
export function revisePlan(taskId: number, instruction: string): Promise<PlanRevisionResponse> {
  return request<PlanRevisionResponse>(`/grilling/tasks/${taskId}/plan/revisions`, {
    method: 'POST',
    body: JSON.stringify({ instruction })
  })
}

/** 方案修订历史：GET /api/grilling/tasks/{id}/plan/revisions。 */
export function listRevisions(taskId: number): Promise<PlanRevisionListResponse> {
  return request<PlanRevisionListResponse>(`/grilling/tasks/${taskId}/plan/revisions`)
}

/** 待确认事项清单：GET /api/grilling/tasks/{id}/open-items。 */
export function listOpenItems(taskId: number): Promise<OpenItemListResponse> {
  return request<OpenItemListResponse>(`/grilling/tasks/${taskId}/open-items`)
}

/** 处置一条待确认事项：POST /api/grilling/tasks/{id}/open-items/{item_id}/resolve（body {status}）。 */
export function resolveOpenItem(
  taskId: number,
  itemId: number,
  status: ResolveStatus
): Promise<OpenItem> {
  return request<OpenItem>(`/grilling/tasks/${taskId}/open-items/${itemId}/resolve`, {
    method: 'POST',
    body: JSON.stringify({ status })
  })
}

/* ============================================================
   成品章节清单（只读）—— 工单 7 / 8 / ADR-0006
   权威来源：backend/app/models/plan_section.py、routes/sections.py
   ============================================================ */

/**
 * 成品章节状态：待写 / 已完成 / 失败。
 *
 * 三态必须分开（ADR-0006）：把「没写」和「写挂了」并成一态，界面就没法说清
 * 到底哪一章需要重写。保留 string 兜底以防后端后续扩展。
 */
export type PlanSectionStatus = 'pending' | 'completed' | 'failed' | (string & {})

/**
 * 成品目录里的一章。
 *
 * **不含已写正文**：清单只回答「目录长什么样、写到哪一步」，正文由填充模块
 * 写库、由成品文件呈现。字段与后端 `PlanSectionItem` 逐一对应：
 * - `target_length` 是方案给的**建议字数**，旧格式方案可能为 null（前端说「字数未定」）；
 * - `hanzi_count` 是**已写汉字数**，由后端唯一入口 `app.hanzi.count_hanzi` 现算，前端不另算；
 * - `status_label` 是后端给的中文标签，前端优先用它，避免两边各翻一套。
 */
export interface PlanSectionItem {
  seq: number
  title: string
  key_points: string
  target_length: number | null
  hanzi_count: number
  status: PlanSectionStatus
  status_label: string
  completed_at: string | null
}

/**
 * 某任务的成品章节清单（只读）。
 *
 * `plan_id` 标出这份清单属于哪一版方案：方案修订会换一版，前端据此判断清单是否过期。
 * 方案没有可切分章节时是**空清单而不是错误**（`items: []`、`total: 0`）。
 */
export interface PlanSectionListResponse {
  plan_id: number
  items: PlanSectionItem[]
  total: number
}

/**
 * 成品章节清单：GET /api/tasks/{id}/sections（只读）。
 *
 * 刻意**只有这一个**章节接口——改名、拖拽排序、增删章节一律不做（ADR-0006：
 * 那等于把「方案直接编辑」提前，超出范围）。要改章节就回去对话修订方案。
 */
export function listPlanSections(taskId: number): Promise<PlanSectionListResponse> {
  return request<PlanSectionListResponse>(`/tasks/${taskId}/sections`)
}

/**
 * 单章填充的响应（工单 10 / 24）：刚写好的那章（章节项）与随即拼装出的正文成品。
 *
 * 与后端 `SectionWriteResponse` 逐字段对齐：`section` 是章节项（含字数 / 状态），
 * `deliverable` 是成品记录（`source` 标正文成品，文件名可下载）。单章端点成功即返回
 * 一个真实成品，`deliverable` 恒非空（被中断为 None 的那条属于全篇串行的回调，不在此处）。
 */
export interface SectionWriteResponse {
  task_id: number
  fill_id: number
  section: PlanSectionItem
  deliverable: GenerationResponse
}

/* ============================================================
   填充：目标字数分摊（工单 15）—— ADR-0006
   权威来源：backend/app/models/fill.py、routes/fill.py、fill/budget.py
   ============================================================ */

/**
 * 分摊预览里的一章。
 *
 * 只有「分到多少字」，不含正文与状态：预览发生在**尚未开始填充**时，
 * 那时还没有正文可谈。
 */
export interface FillAllocationItem {
  seq: number
  title: string
  target_length: number
}

/**
 * 目标字数的分摊预览（**只算不写**）。
 *
 * 与 `startFill` 的区别至关重要：预览不改章节表、不建填充任务。用户在参数弹窗里
 * 来回试字数时，系统不该因此留下一串填充记录。
 */
export interface FillAllocationResponse {
  plan_id: number
  target_length: number
  items: FillAllocationItem[]
  total: number
}

/** 开始填充的请求体（与后端 `FillRequest` 对应，`extra="forbid"`）。 */
export interface FillRequest {
  /** 目标字数（按汉字计）；省略时后端按方案各章建议字数求和。 */
  target_length?: number
  /** 逐章改过的字数（序号 → 字数）；只含改动的章。 */
  section_lengths?: Record<number, number>
}

/**
 * 试算字数分摊：POST /api/tasks/{id}/fill/allocation（只算不写）。
 *
 * 分摊规则只在后端实现一份（`app.fill.budget`），前端绝不自己摊一遍——
 * 两套实现一旦漂移，用户看到的预览与实际写出的正文就是两回事。
 *
 * 拒绝口径与 `startFill` 一致：无方案 / 未确认 → 409，无可切分章节 → 422，
 * 字数超 300–20000 或分摊不成立 → 422（detail 说明原因，不静默夹到边界值）。
 */
export function previewFillAllocation(
  taskId: number,
  payload: FillRequest = {}
): Promise<FillAllocationResponse> {
  return request<FillAllocationResponse>(`/tasks/${taskId}/fill/allocation`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

/* ============================================================
   填充·单章引用与正文（工单 24）
   权威来源：backend/app/models/fill.py、routes/fill.py
   ============================================================ */

/**
 * 一章可用引用片段的预览（工单 24）：**只读不改库**。
 *
 * 用户在写这一章之前先看到将注入哪些资料片段（默认全选、可逐条取消），再决定
 * 要不要真的用它们。`cards` 复用检索的 `CitationCard` 形状；`retrieval_status`
 * 复用 `RetrievalStatusInfo`——界面据此明示「降级 / 本次未使用知识库」。
 */
export interface SectionReferencesResponse {
  task_id: number
  seq: number
  /** 引用卡片（默认全选，可逐条取消）。 */
  cards: CitationCard[]
  retrieval_status: RetrievalStatusInfo | null
}

/** 单章填充的请求体（与后端 `SectionFillRequest` 对应，`extra="forbid"`）。 */
export interface SectionFillRequest {
  /**
   * 用户在该章**保留**的引用片段（从引用预览里勾选后带回）。
   * 省略表示本章不使用知识库。后端只把 `adopted=true` 的注入正文。
   */
  reference_cards?: CitationCard[]
}

/**
 * 给一章算一份可用引用片段预览：POST /api/tasks/{id}/sections/{seq}/references。
 *
 * 只读不改库——反复预览不会留下填充记录，也不会触发写正文。
 */
export function previewSectionReferences(
  taskId: number,
  seq: number
): Promise<SectionReferencesResponse> {
  return request<SectionReferencesResponse>(`/tasks/${taskId}/sections/${seq}/references`, {
    method: 'POST'
  })
}

/**
 * 写一章正文并随即拼装成品：POST /api/tasks/{id}/sections/{seq}/fill。
 *
 * `payload.reference_cards` 只在带引用片段时传：后端把保留的片段注入提示词、并在
 * 正文写成功后落库。返回 `SectionWriteResponse`（内含章节项与成品记录）。
 */
export function fillSection(
  taskId: number,
  seq: number,
  payload: SectionFillRequest = {}
): Promise<SectionWriteResponse> {
  return request<SectionWriteResponse>(`/tasks/${taskId}/sections/${seq}/fill`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

/* ============================================================
   历史、续作与删除 —— TB-10
   权威来源：backend/app/models/{history,task}.py、routes/{history,tasks}.py
   ============================================================ */

/** 续作的下一步动作（由已持久化数据推导）。 */
export type ResumeNext =
  | 'answers'
  | 'advance'
  | 'plan_confirm'
  | 'generation'
  | 'completed'
  | 'deleted'

/** 历史列表中的一条任务（含元信息行所需字段）。 */
export interface HistoryItem {
  id: number
  kind: TaskKind
  title: string | null
  status: TaskStatus
  created_at: string
  updated_at: string
  dialogue_messages: number
  rounds: number
  /**
   * 分析任务的最新来源 id（供「回看」直接落到该份资料的分析页）；
   * 创作任务与无来源的分析任务为 null。
   */
  source_id: number | null
}

/** 导航徽标用的分计数（全局，不随过滤变化）。 */
export interface HistoryCounts {
  all: number
  creation: number
  analysis: number
}

/** 历史列表响应：当页条目 + 过滤后总数 + 分页参数 + 分计数。 */
export interface HistoryListResponse {
  items: HistoryItem[]
  total: number
  limit: number
  offset: number
  counts: HistoryCounts
}

/** 任务详情 + 续作状态（「打开详情并续作」的单一入口）。 */
export interface HistoryDetail {
  task: Task
  deleted_at: string | null
  dialogue: Dialogue
  plan: Plan | null
  open_items: OpenItem[]
  unresolved_open_items: number
  last_round_no: number
  pending_round: FrontierRound | null
  awaiting: ResumeNext
}

/** 删除影响范围（确认弹层数据源；数字全部来自真实持久化数据）。 */
export interface DeletionImpact {
  task_id: number
  title: string | null
  kind: TaskKind
  status: TaskStatus
  dialogue_messages: number
  rounds: number
  plans: number
  plan_revisions: number
  open_items: number
  deliverable_files: number
  summary: string
}

/** 删除结果：软删除后的任务留痕 + 本次确认的影响范围。 */
export interface DeletionResult {
  task: Task
  deleted_at: string
  already_deleted: boolean
  impact: DeletionImpact
}

export interface HistoryQuery {
  kind?: TaskKind
  status?: TaskStatus
  limit?: number
  offset?: number
}

/** 历史列表：GET /api/history。默认排除已删除；显式 status=deleted 查留痕。 */
export function listHistory(params: HistoryQuery = {}): Promise<HistoryListResponse> {
  const query = new URLSearchParams()
  if (params.kind) query.set('kind', params.kind)
  if (params.status) query.set('status', params.status)
  if (params.limit != null) query.set('limit', String(params.limit))
  if (params.offset != null) query.set('offset', String(params.offset))
  const qs = query.toString()
  return request<HistoryListResponse>(qs ? `/history?${qs}` : '/history')
}

/** 打开详情并续作：GET /api/history/{id}（复原所需一切 + awaiting / pending_round）。 */
export function getHistoryDetail(taskId: number): Promise<HistoryDetail> {
  return request<HistoryDetail>(`/history/${taskId}`)
}

/** 删除影响范围预览：GET /api/tasks/{id}/deletion-impact（不改动任何数据）。 */
export function getDeletionImpact(taskId: number): Promise<DeletionImpact> {
  return request<DeletionImpact>(`/tasks/${taskId}/deletion-impact`)
}

/**
 * 删除任务：DELETE /api/tasks/{id}?confirm=true。
 * 不带 confirm 后端返回 409（detail 即影响范围）；带 confirm 走软删除（留痕、不丢数据）。
 */
export function deleteTask(taskId: number, confirm: boolean): Promise<DeletionResult> {
  return request<DeletionResult>(`/tasks/${taskId}?confirm=${confirm ? 'true' : 'false'}`, {
    method: 'DELETE'
  })
}

/** 状态迁移：POST /api/tasks/{id}/status（进行中 ↔ 已完成；deleted 只能走删除入口）。 */
export function setTaskStatus(taskId: number, status: 'in_progress' | 'completed'): Promise<Task> {
  return request<Task>(`/tasks/${taskId}/status`, {
    method: 'POST',
    body: JSON.stringify({ status })
  })
}

/* ============================================================
   资料分析（来源 → 文档 → 分块 → 总结）—— TB-7 / TB-8 / TB-9
   权威来源：backend/app/models/analysis.py、routes/analysis.py。
   术语：资料分析 / 总结 / 未识别 / 来源 / 分块 / 一键送入主题创作。
   命名纪律：这是「分块 → 逐块分析 → 综合」分析管线，不是 RAG（ADR-0002）。
   来源类型：file（TXT/MD/DOCX/PDF/PPTX 上传）与 url（公开网页抓取），共用后续端点。
   ============================================================ */

/** 未识别内容统一契约（一级输出字段，绝不以空字符串冒充成功）。 */
export interface UnrecognizedContent {
  unrecognized: boolean
  reason: string
  locator: Record<string, unknown>
  needs_ocr: boolean
}

/** 来源登记（kind: file；url 等来源类型由后续工单启用）。 */
export interface AnalysisSourceInfo {
  id: number
  kind: string
  ref: string
  meta: Record<string, unknown>
  task_id: number | null
  created_at: string
}

/** 文档解析结果；chunks 为已落库分块数。 */
export interface AnalysisDocumentInfo {
  id: number
  source_id: number
  path: string
  parse_status: string
  parse_message: string | null
  heading_source: string | null
  /** 解析器标识（plain-text / python-docx / pypdf / python-pptx）；解析失败或 URL 来源为 null。 */
  parser: string | null
  encoding: string | null
  headings: number
  images: number
  chunks: number
  created_at: string
}

/** 上传 / URL 抓取 + 解析的结果（两种来源同一形状；失败仍是 201 + failed + 可读 message）。 */
export interface AnalysisSourceResponse {
  source: AnalysisSourceInfo
  document: AnalysisDocumentInfo
  unrecognized: UnrecognizedContent | null
  unrecognized_parts: UnrecognizedContent[]
  message: string | null
}

/** 总结引用：来自哪个分块、什么位置、该块开头摘录。 */
export interface SummaryCitation {
  chunk_seq: number
  locator: Record<string, unknown>
  excerpt: string
}

/** 总结（含长度、引用与实际档位证据；档位缺失回退不静默）。 */
export interface AnalysisSummary {
  id: number
  source_id: number
  task_id: number | null
  text: string
  hanzi_count: number
  citations: SummaryCitation[]
  chunk_count: number
  truncated: boolean
  provider_kind: string | null
  provider_used: string | null
  model_used: string | null
  provider_fallback: boolean
  provider_note: string | null
  created_at: string
}

/** 一次分析的结果：有总结，或（未识别时）只有显式的未识别契约。 */
export interface AnalysisResultResponse {
  source: AnalysisSourceInfo
  document: AnalysisDocumentInfo
  summary: AnalysisSummary | null
  unrecognized: UnrecognizedContent | null
  unrecognized_parts: UnrecognizedContent[]
  message: string | null
}

/** 一键送入主题创作的结果：新建任务 + 预填的已知信息（后端不调用模型）。 */
export interface SendToCreationResponse {
  task: Task
  source_id: number
  summary_id: number
  known_input: string
}

/** 来源列表条目：来源 + 最新文档（可能为 null）+ 是否已有总结。 */
export interface AnalysisSourceListItem {
  source: AnalysisSourceInfo
  document: AnalysisDocumentInfo | null
  has_summary: boolean
  summary_id: number | null
  summary_created_at: string | null
}

/** GET /api/analysis/sources 列表返回体（按 id 倒序）。 */
export interface AnalysisSourceListResponse {
  items: AnalysisSourceListItem[]
  total: number
  limit: number
  offset: number
}

/** 总结生成 Word 的成品记录 + 产物元数据（实际所用模板如实回显）。 */
export interface SummaryWordDeliverable {
  id: number
  source_id: number
  task_id: number | null
  format: string
  file_path: string
  template_used: string
  created_at: string
  template_style_applied: boolean
  missing_styles: string[]
  headings: number
}

/**
 * 上传资料（multipart，字段 file）：走 XHR 以便回报真实上传进度（fetch 无上传进度事件）。
 * 支持 TXT / MD / DOCX / PDF / PPTX（TB-8 起含版式类）。
 * 错误语义与 request() 一致：网络失败 → BackendUnavailableError；非 2xx → ApiHttpError（附 detail）。
 * onProgress 收 0–100 百分比（按字节计，50MB 文件也有意义）。
 */
export function uploadAnalysisSource(
  file: File,
  onProgress?: (percent: number) => void
): Promise<AnalysisSourceResponse> {
  return new Promise((resolve, reject) => {
    const body = new FormData()
    body.append('file', file, file.name)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE_URL}/analysis/sources`)
    xhr.responseType = 'text'
    xhr.upload.onprogress = (event) => {
      if (onProgress && event.lengthComputable) {
        onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)))
      }
    }
    xhr.onerror = () => reject(new BackendUnavailableError())
    xhr.ontimeout = () => reject(new Error('上传超时，请检查后端是否在运行后重试'))
    xhr.onload = () => {
      let payload: unknown = null
      try {
        payload = JSON.parse(xhr.responseText)
      } catch {
        /* 非 JSON 响应体，保持 null */
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload as AnalysisSourceResponse)
        return
      }
      const detail =
        payload &&
        typeof payload === 'object' &&
        'detail' in payload &&
        typeof (payload as { detail?: unknown }).detail === 'string'
          ? (payload as { detail: string }).detail
          : ''
      reject(new ApiHttpError(xhr.status, xhr.statusText || '', detail))
    }
    xhr.send(body)
  })
}

/**
 * 提交 URL 来源：POST /api/analysis/sources/url（TB-9）。
 * 后端先做不联网的安全前置校验（仅 http/https、拒绝环回 / 私网 / 链路本地 / 云元数据等），
 * 不合格 → 400 且不落库；抓取失败 / 需登录 / 超时 / 超限 → 201 + parse_status="failed"。
 * 错误语义沿用 request()：非 2xx 抛 Error（detail 为后端可读中文原因，原样展示）。
 */
export function createAnalysisUrlSource(url: string): Promise<AnalysisSourceResponse> {
  return request<AnalysisSourceResponse>('/analysis/sources/url', {
    method: 'POST',
    body: JSON.stringify({ url })
  })
}

/** 读取来源与解析结果：GET /api/analysis/sources/{id}（供展示与重试）。 */
export function getAnalysisSource(sourceId: number): Promise<AnalysisSourceResponse> {
  return request<AnalysisSourceResponse>(`/analysis/sources/${sourceId}`)
}

/** 来源列表：GET /api/analysis/sources?limit=&offset=（按 id 倒序，供「最近资料」回看）。 */
export function listAnalysisSources(params: {
  limit?: number
  offset?: number
} = {}): Promise<AnalysisSourceListResponse> {
  const query = new URLSearchParams()
  if (params.limit != null) query.set('limit', String(params.limit))
  if (params.offset != null) query.set('offset', String(params.offset))
  const qs = query.toString()
  return request<AnalysisSourceListResponse>(qs ? `/analysis/sources?${qs}` : '/analysis/sources')
}

/**
 * 触发分析：POST /api/analysis/sources/{id}/analyze（分块 → 逐块 → 综合，同步返回）。
 * 未识别 → 200 + summary=null + 显式契约；解析失败 → 409；模型失败 → 502（已存数据保留，可安全重试）。
 */
export function analyzeSource(sourceId: number): Promise<AnalysisResultResponse> {
  return request<AnalysisResultResponse>(`/analysis/sources/${sourceId}/analyze`, {
    method: 'POST'
  })
}

/** 某来源最新总结：GET /api/analysis/sources/{id}/summary（尚无总结 404）。 */
export function getAnalysisSummary(sourceId: number): Promise<AnalysisSummary> {
  return request<AnalysisSummary>(`/analysis/sources/${sourceId}/summary`)
}

/**
 * 由某来源的总结生成 Word 成品：POST /api/analysis/sources/{id}/summary/word。
 * `template` 省略或空 = 走该格式的全局默认模板；无总结 → 409，模板缺失 / 损坏 → 400，完整性失败 → 500。
 */
export function createSummaryWord(
  sourceId: number,
  template?: string | null
): Promise<SummaryWordDeliverable> {
  const body = template && template.length > 0 ? JSON.stringify({ template }) : JSON.stringify({})
  return request<SummaryWordDeliverable>(`/analysis/sources/${sourceId}/summary/word`, {
    method: 'POST',
    body
  })
}

/** 总结 Word 成品的下载地址（GET /api/analysis/summary-deliverables/{id}，直接回 .docx）。 */
export function summaryWordDownloadUrl(deliverableId: number): string {
  return `${API_BASE_URL}/analysis/summary-deliverables/${deliverableId}`
}

/** 一键送入主题创作：POST /api/analysis/sources/{id}/send-to-creation（只预填、不调用模型）。 */
export function sendToCreation(
  sourceId: number,
  title?: string
): Promise<SendToCreationResponse> {
  return request<SendToCreationResponse>(`/analysis/sources/${sourceId}/send-to-creation`, {
    method: 'POST',
    body: JSON.stringify(title && title.trim() ? { title: title.trim() } : {})
  })
}

/* ============================================================
   知识库（工单 19 / ADR-0005）—— 上传即入库、清单、删除、重建索引
   权威来源：backend/app/models/knowledge.py、routes/knowledge.py。
   术语：知识库 / 索引状态（已入库 / 索引中 / 索引失败）。
   归属约定：知识库资料复用资料分析的来源 / 文档 / 分块三表，以「不隶属任何任务」
   （task_id IS NULL）表示；因此这里没有 task_id 字段，也不会出现在资料分析清单里。
   嵌入与检索属工单 20 / 21：本层只读状态，状态本身已经能表达「索引中」。
   ============================================================ */

/**
 * 知识库资料（清单条目）。
 * - index_status：`stored` 已入库 / `indexing` 索引中 / `failed` 索引失败；
 * - index_message：失败原因（解析失败、未识别到文本、重建索引失败等），成功时为 null；
 * - chunk_count 为真实落库分块数，0 表示没有切出可用内容（配合状态一起看）。
 */
export interface KnowledgeSourceItem {
  source_id: number
  name: string
  kind: string
  ref: string
  size: number | null
  document_id: number | null
  parse_status: string | null
  parse_message: string | null
  chunk_count: number
  index_status: string
  index_status_label: string
  index_message: string | null
  indexed_at: string | null
  created_at: string
}

/** GET /api/knowledge/sources 返回体（按 id 倒序）。 */
export interface KnowledgeSourceListResponse {
  items: KnowledgeSourceItem[]
  total: number
  limit: number
  offset: number
}

/** 上传结果：失败（解析不出内容）同样是 201，item.index_status 为 failed。 */
export interface KnowledgeUploadResponse {
  item: KnowledgeSourceItem
  message: string | null
}

/** 删除结果：连带清掉的分块数，供界面回显真实影响。 */
export interface KnowledgeDeleteResponse {
  source_id: number
  deleted_chunk_count: number
}

/** 重建索引的单条结果（逐条回报，单份失败不影响其他资料）。 */
export interface KnowledgeReindexItem {
  source_id: number
  index_status: string
  index_status_label: string
  message: string | null
}

/** POST /api/knowledge/reindex 返回体。 */
export interface KnowledgeReindexResponse {
  items: KnowledgeReindexItem[]
  total: number
}

/**
 * 上传资料入知识库（multipart 字段 file）：走 XHR 以便回报真实上传进度。
 * 支持 TXT / MD / DOCX / PDF / PPTX（与资料分析同一白名单 + 50MB 上限）。
 * 失败语义与 request() 一致：网络失败 → BackendUnavailableError；非 2xx → ApiHttpError。
 */
export function uploadKnowledgeSource(
  file: File,
  onProgress?: (percent: number) => void
): Promise<KnowledgeUploadResponse> {
  return new Promise((resolve, reject) => {
    const body = new FormData()
    body.append('file', file, file.name)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE_URL}/knowledge/sources`)
    xhr.responseType = 'text'
    xhr.upload.onprogress = (event) => {
      if (onProgress && event.lengthComputable) {
        onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)))
      }
    }
    xhr.onerror = () => reject(new BackendUnavailableError())
    xhr.ontimeout = () => reject(new Error('上传超时，请检查后端是否在运行后重试'))
    xhr.onload = () => {
      let payload: unknown = null
      try {
        payload = JSON.parse(xhr.responseText)
      } catch {
        /* 非 JSON 响应体，保持 null */
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload as KnowledgeUploadResponse)
        return
      }
      const detail =
        payload &&
        typeof payload === 'object' &&
        'detail' in payload &&
        typeof (payload as { detail?: unknown }).detail === 'string'
          ? (payload as { detail: string }).detail
          : ''
      reject(new ApiHttpError(xhr.status, xhr.statusText || '', detail))
    }
    xhr.send(body)
  })
}

/** 知识库清单：GET /api/knowledge/sources?limit=&offset=（按 id 倒序）。 */
export function listKnowledgeSources(params: {
  limit?: number
  offset?: number
} = {}): Promise<KnowledgeSourceListResponse> {
  const query = new URLSearchParams()
  if (params.limit != null) query.set('limit', String(params.limit))
  if (params.offset != null) query.set('offset', String(params.offset))
  const qs = query.toString()
  return request<KnowledgeSourceListResponse>(
    qs ? `/knowledge/sources?${qs}` : '/knowledge/sources'
  )
}

/** 删除知识库资料：DELETE /api/knowledge/sources/{id}（连带清掉文档、分块与嵌入）。 */
export function deleteKnowledgeSource(sourceId: number): Promise<KnowledgeDeleteResponse> {
  return request<KnowledgeDeleteResponse>(`/knowledge/sources/${sourceId}`, {
    method: 'DELETE'
  })
}

/**
 * 重建索引：POST /api/knowledge/reindex（不传 source_id 表示全部资料）。
 * 逐条回报状态；单份失败不影响其他资料。
 */
export function reindexKnowledge(sourceId?: number): Promise<KnowledgeReindexResponse> {
  return request<KnowledgeReindexResponse>('/knowledge/reindex', {
    method: 'POST',
    body: JSON.stringify(sourceId != null ? { source_id: sourceId } : {})
  })
}

export default {
  API_BASE_URL,
  checkHealth,
  request,
  createTask,
  listTasks,
  getTask,
  updateTaskModel,
  listProviders,
  createProvider,
  updateProvider,
  deleteProvider,
  setDefaultProvider,
  testProvider,
  startGrillingTask,
  submitAnswers,
  getDialogue,
  advanceGrilling,
  getPlan,
  confirmPlan,
  generateDeliverable,
  listGenerations,
  getTemplates,
  registerTemplate,
  setDefaultTemplate,
  getDeckThemes,
  getDeckThemeDefault,
  setDeckThemeDefault,
  fetchDeliverable,
  fetchDeliverableHtml,
  downloadDeliverable,
  revisePlan,
  listRevisions,
  listOpenItems,
  resolveOpenItem,
  listPlanSections,
  previewFillAllocation,
  previewSectionReferences,
  fillSection,
  listHistory,
  getHistoryDetail,
  getDeletionImpact,
  deleteTask,
  setTaskStatus,
  uploadAnalysisSource,
  createAnalysisUrlSource,
  getAnalysisSource,
  listAnalysisSources,
  analyzeSource,
  getAnalysisSummary,
  createSummaryWord,
  summaryWordDownloadUrl,
  sendToCreation,
  uploadKnowledgeSource,
  listKnowledgeSources,
  deleteKnowledgeSource,
  reindexKnowledge
}
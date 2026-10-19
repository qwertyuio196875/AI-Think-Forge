<template>
  <section class="view" aria-label="设置">
    <header class="view-head">
      <div class="head-row">
        <div class="head-title">
          <h1>设置</h1>
          <p>模型配置 · 默认档位 · 本地与隐私边界</p>
        </div>
        <div class="head-actions">
          <el-button :icon="Refresh" :loading="listState === 'loading'" @click="loadProviders">刷新</el-button>
          <el-button type="primary" :icon="Plus" @click="openAdd">新增模型配置</el-button>
        </div>
      </div>
    </header>

    <div class="view-body">
      <div class="form-wrap">
        <!-- ============ 模型配置 ============ -->
        <section class="sec">
          <header>
            <h3>模型配置</h3>
            <p>业务不绑定厂商：统一走 OpenAI 兼容接口，可新增、编辑、删除、设为默认，并做连接测试</p>
          </header>
          <div class="sec-body">
            <!-- 加载 -->
            <div v-if="listState === 'loading'" class="list-loading">
              <el-skeleton v-for="n in 3" :key="n" :rows="1" animated />
            </div>

            <!-- 错误 -->
            <div v-else-if="listState === 'error'" class="note err" role="alert">
              <el-icon class="ico"><WarningFilled /></el-icon>
              <div class="note-body">
                <b>{{ listError }}</b>
                <span>本地后端未启动或连接失败，暂时读不到模型配置。</span>
                <div><el-button size="small" @click="loadProviders">重新加载</el-button></div>
              </div>
            </div>

            <!-- 空态 -->
            <div v-else-if="providers.length === 0" class="empty">
              <el-icon class="ico-lg"><Cpu /></el-icon>
              <b>还没有模型配置</b>
              <p>新增一条 OpenAI 兼容配置（如 DeepSeek），保存后用「连接测试」验证即可开始使用。</p>
              <el-button type="primary" :icon="Plus" @click="openAdd">新增模型配置</el-button>
            </div>

            <!-- 列表 -->
            <div v-else class="cfg-list">
              <article
                v-for="p in providers"
                :key="p.id"
                class="cfg"
                :class="{ 'is-def': p.is_default }"
              >
                <div class="cfg-info">
                  <b>{{ p.name }}</b>
                  <div class="meta mono">{{ p.base_url }}</div>
                  <div class="meta">
                    模型名 {{ p.model_name }} · 档位 {{ kindLabel(p.kind) }}
                  </div>
                </div>

                <div class="cfg-tags">
                  <el-tag v-if="p.is_default" size="small" effect="dark">默认</el-tag>
                  <el-tag v-else size="small" type="info" effect="plain">{{ kindLabel(p.kind) }}</el-tag>
                  <el-tag
                    size="small"
                    :type="p.has_key ? 'success' : 'warning'"
                    effect="plain"
                  >{{ p.has_key ? '已配密钥' : '未配密钥' }}</el-tag>
                </div>

                <div class="cfg-acts">
                  <el-button size="small" :icon="Connection" :loading="testingMap[p.id]" @click="doTest(p)">
                    连接测试
                  </el-button>
                  <el-button size="small" :icon="EditPen" @click="openEdit(p)">编辑</el-button>
                  <el-button
                    v-if="!p.is_default"
                    size="small"
                    :icon="Star"
                    :disabled="settingDefaultId === p.id"
                    @click="doSetDefault(p)"
                  >
                    设为默认
                  </el-button>
                  <el-button size="small" type="danger" plain :icon="Delete" @click="askDelete(p)">
                    删除
                  </el-button>
                </div>

                <div
                  v-if="testResultMap[p.id]"
                  class="cfg-test note"
                  :class="reportClass(p.id)"
                  role="status"
                >
                  <el-icon class="ico">
                    <CircleCheck v-if="testResultMap[p.id].level === 'ok'" />
                    <WarningFilled v-else />
                  </el-icon>
                  <div class="note-body">
                    <b>{{ testResultMap[p.id].title }}</b>
                    <span>{{ testResultMap[p.id].detail }}</span>
                  </div>
                </div>
              </article>

              <p class="hint">
                「默认」标记的是<strong>全局默认配置</strong>，作用于未单独指定档位的新任务；
                任务级临时覆盖在创作 / 分析任务内进行，不会改变此处默认。每次生成都会记录实际所用配置。
              </p>

              <div class="row-actions">
                <el-button :icon="Plus" @click="openAdd">新增模型配置</el-button>
              </div>
            </div>
          </div>
        </section>

        <!-- ============ 默认档位与额度 ============ -->
        <section class="sec">
          <header>
            <h3>默认档位与额度</h3>
            <p>全局默认来自下方标记为「默认」的配置；额度统计将在后续工单接入</p>
          </header>
          <div class="sec-body">
            <div class="field">
              <label>全局默认配置</label>
              <div v-if="defaultProvider" class="default-line">
                <b>{{ defaultProvider.name }}</b>
                <span class="meta mono">{{ defaultProvider.base_url }} · {{ defaultProvider.model_name }}</span>
              </div>
              <div v-else class="muted small">尚无标记为默认的模型配置，可在上方对任一配置点「设为默认」。</div>
              <p class="hint">
                用列表中的「设为默认」切换全局默认；任务级临时档位选择只影响该次任务，不会改写这里。
              </p>
            </div>

            <ul class="tiers">
              <li v-for="role in roles" :key="role.kind">
                <span class="tier-name">{{ role.label }}</span>
                <span class="tier-val" :class="{ muted: role.providers.length === 0 }">
                  {{ role.providers.length ? role.providers.map((p) => p.name).join('、') : '无此档位配置' }}
                </span>
              </li>
            </ul>

            <div class="note info">
              <el-icon class="ico"><InfoFilled /></el-icon>
              <div class="note-body">
                <span>
                  额度统计（百炼 / DeepSeek 用量）属应用设置，暂无独立读写接口，将在后续工单接入。
                </span>
              </div>
            </div>
          </div>
        </section>

        <!-- ============ 默认模板 ============ -->
        <section class="sec">
          <header>
            <h3>默认模板</h3>
            <p>全局默认模板 + 任务级临时覆盖；每次生成记录实际所用模板。Word 模板由你提供，系统从不联网搜模板</p>
          </header>
          <div class="sec-body">
            <div v-if="tplState === 'loading'" class="list-loading">
              <el-skeleton :rows="2" animated />
            </div>
            <div v-else-if="tplState === 'error'" class="note err" role="alert">
              <el-icon class="ico"><WarningFilled /></el-icon>
              <div class="note-body">
                <b>{{ tplError }}</b>
                <span>暂时读不到模板目录。</span>
                <div><el-button size="small" @click="loadTemplates">重新加载</el-button></div>
              </div>
            </div>

            <template v-else>
              <!-- Word 模板清单 -->
              <div class="sub-label">Word 模板 · 全局默认</div>
              <div v-if="!docxTemplates.length" class="pend-empty">
                模板目录里还没有 .docx。把模板放入 <span class="mono">templates/</span> 后登记，即可选为全局默认；在此之前生成走内置最小默认模板。
              </div>
              <ul v-else class="tpl-list">
                <li v-for="t in docxTemplates" :key="t.name" class="tpl-row" :class="{ sel: t.is_default }">
                  <div class="tpl-main">
                    <b>{{ t.name }}</b>
                    <div class="meta">
                      <span v-if="t.builtin">内置最小默认 · 只保证 标题层级 / 正文 / 列表 / 表格 的基本映射</span>
                      <span v-else-if="t.missing" class="err-t">文件已缺失（登记过，但 templates/ 里已无此文件）</span>
                      <span v-else>用户模板 · {{ t.registered ? '已登记' : '未登记' }}{{ t.usable ? '' : '（不可用）' }}</span>
                    </div>
                  </div>
                  <div class="tpl-acts">
                    <el-tag v-if="t.is_default" size="small" effect="dark">默认</el-tag>
                    <el-button
                      v-else-if="!t.missing && t.usable"
                      size="small"
                      :loading="settingTpl === t.name"
                      @click="doSetDefaultTpl(t.name)"
                    >
                      设为默认
                    </el-button>
                  </div>
                </li>
              </ul>

              <div class="reg-row">
                <el-input
                  v-model="regName"
                  size="small"
                  placeholder="登记已在 templates/ 的 .docx 文件名，例如 公司模板.docx"
                />
                <el-button size="small" :loading="regBusy" :disabled="!regName.trim()" @click="doRegister">
                  登记
                </el-button>
              </div>
              <p class="hint">
                上传文件入口属 TB-7；此处仅登记「已放入 templates/ 目录」的文件名。非 .docx 会被拒绝（400），不会静默接受。
              </p>

              <!-- HTML 默认主题（TB-6） -->
              <div class="sub-label spaced">单文件 HTML 演示 · 默认主题</div>
              <div class="theme-grid">
                <label
                  v-for="th in HTML_THEMES"
                  :key="th.id"
                  class="theme-opt"
                  :class="{ sel: htmlTheme === th.id }"
                >
                  <input v-model="htmlTheme" type="radio" name="htmltheme" :value="th.id" />
                  <span>
                    <b>{{ th.name }}</b>
                    <span class="td">{{ th.desc }}</span>
                    <span class="theme-chips">
                      <i :style="{ background: th.colors[0] }"></i>
                      <i :style="{ background: th.colors[1] }"></i>
                      <i :style="{ background: th.colors[2] }"></i>
                    </span>
                  </span>
                </label>
              </div>
              <p class="hint">
                主题取自 OpenDesign（Apache-2.0）本地资产。单文件 HTML 成品与主题落地属 TB-6；此处选择<strong>不写入后端</strong>（暂无默认主题接口），仅为本页预览。色卡为该主题的示意配色。
              </p>

              <!-- pptx 计划项（不可用） -->
              <div class="tpl-row is-plan">
                <div class="tpl-main">
                  <b>PowerPoint .pptx<el-tag class="mini" size="small" type="info" effect="plain">v1.1 计划</el-tag></b>
                  <div class="meta">v1 不生成 .pptx；汇报演示由单文件 HTML 承担，两条路互不转换。此项仅告知，不提供可用入口。</div>
                </div>
              </div>

              <!-- 最近生成记录 -->
              <div class="sub-label spaced">最近生成记录（实际所用模板）</div>
              <table class="tbl">
                <thead>
                  <tr>
                    <th>任务</th>
                    <th class="col-hide">成品</th>
                    <th>实际所用模板</th>
                    <th class="col-hide">时间</th>
                  </tr>
                </thead>
              </table>
              <div class="pend-empty">暂无跨任务的生成记录汇总接口；单任务的成品见创作页「生成面板」的成品卡。</div>
            </template>
          </div>
        </section>

        <!-- ============ 本地与隐私 ============ -->
        <section class="sec">
          <header>
            <h3>本地与隐私</h3>
            <p>只监听本机回环；文件访问限定白名单；调用云端模型前如实告知数据去向</p>
          </header>
          <div class="sec-body">
            <div class="note warn">
              <el-icon class="ico"><WarningFilled /></el-icon>
              <div class="note-body">
                <b>「本地运行」不等于「数据不出机」</b>
                <span>
                  调用云端模型时，你的提示词与资料片段（含拷问对话、总结输入与方案）都会发送给所配置的服务商。
                  只有配置为本地推理服务时，数据才不出本机。
                </span>
              </div>
            </div>

            <div class="field">
              <label>监听地址</label>
              <el-input class="mono" model-value="http://127.0.0.1:8720" readonly />
              <p class="hint">不可改为局域网或公网地址；同网段他人无法访问。</p>
            </div>

            <ul class="note-list">
              <li>
                <el-icon class="ico"><CircleCheck /></el-icon>
                <span>文件访问限定在工作目录白名单内；上传校验扩展名与大小，路径穿越会被拒绝</span>
              </li>
              <li>
                <el-icon class="ico"><CircleCheck /></el-icon>
                <span>API 密钥存于 Windows 凭据管理器，不进入源码 / Git / 前端持久化 / SQLite / 日志</span>
              </li>
              <li>
                <el-icon class="ico"><CircleCheck /></el-icon>
                <span>日志对失败信息脱敏，不含完整密钥与不必要的敏感内容</span>
              </li>
              <li>
                <el-icon class="ico"><CircleCheck /></el-icon>
                <span>删除模型配置会同时清除其保存在凭据管理器中的密钥</span>
              </li>
            </ul>
          </div>
        </section>
      </div>
    </div>

    <!-- ============ 新增 / 编辑 对话框 ============ -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑模型配置' : '新增模型配置'"
      width="560px"
      :close-on-click-modal="false"
      append-to-body
    >
      <el-form label-position="top" @submit.prevent>
        <p class="hint" style="margin-top: 0">
          保存后，可在列表中对这条配置点「连接测试」验证可用性。
        </p>
        <el-form-item label="服务商名称">
          <el-input v-model="form.name" placeholder="例如 DeepSeek 主流程" maxlength="80" />
        </el-form-item>
        <el-form-item label="API 地址（Base URL）">
          <el-input v-model="form.base_url" spellcheck="false" placeholder="https://api.deepseek.com" />
          <p class="hint">仅允许 http / https。DeepSeek 填 https://api.deepseek.com（客户端会容忍自动补 /v1）。</p>
        </el-form-item>
        <el-form-item label="模型名">
          <el-input v-model="form.model_name" spellcheck="false" placeholder="deepseek-flash" />
          <p class="hint">DeepSeek 当前有效模型：deepseek-flash（轻量主力）、deepseek-v4-pro（旗舰）。</p>
        </el-form-item>
        <el-form-item label="用途档位（角色标签，可空）">
          <el-select v-model="form.kind" placeholder="选择档位" style="width: 100%">
            <el-option label="主流程（拷问与方案生成）" value="plus" />
            <el-option label="总结流程（资料分析）" value="turbo" />
            <el-option label="任务级深问" value="max" />
            <el-option label="不分档" value="" />
          </el-select>
          <p class="hint">档位只是角色标签，供任务级临时选择时参考，不影响「默认」判定。</p>
        </el-form-item>
        <el-form-item label="API 密钥">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            spellcheck="false"
            autocomplete="new-password"
            :placeholder="editingId ? '留空则保留当前密钥' : '填写该服务商的密钥'"
          />
          <p class="hint">
            <el-icon class="ico-sm"><Lock /></el-icon>
            密钥只写入 Windows 凭据管理器，界面只显示「已配 / 未配」状态；不会存入浏览器，不写 SQLite，不进日志。
            {{ editingId ? '留空即保留原密钥，只有填写才会更新。' : '' }}
          </p>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="formSaving" @click="saveProvider">保存配置</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  CircleCheck,
  Connection,
  Cpu,
  Delete,
  EditPen,
  InfoFilled,
  Lock,
  Plus,
  Refresh,
  Star,
  WarningFilled
} from '@element-plus/icons-vue'
import {
  BackendUnavailableError,
  createProvider,
  deleteProvider,
  getTemplates,
  listProviders,
  registerTemplate,
  setDefaultProvider,
  setDefaultTemplate,
  testProvider,
  updateProvider,
  type Provider,
  type ProviderKind,
  type Template
} from '../api/client'
import { describeConnection, kindLabel, type ConnectionReport } from '../utils/providerMeta'

type ListState = 'loading' | 'ready' | 'error'
const providers = ref<Provider[]>([])
const listState = ref<ListState>('loading')
const listError = ref('')

// 默认模板区（TB-5）
const templates = ref<Template[]>([])
const tplState = ref<ListState>('loading')
const tplError = ref('')
const settingTpl = ref<string | null>(null)
const regName = ref('')
const regBusy = ref(false)
const htmlTheme = ref('slate')

// HTML 主题仅为 TB-6 的本地预览（无后端默认主题接口，选择不写库）；色卡是该主题的示意配色。
const HTML_THEMES: Array<{ id: string; name: string; desc: string; colors: [string, string, string] }> = [
  { id: 'slate', name: 'Slate 极简', desc: '无衬线 · 浅色 · 适合技术分享', colors: ['#1c2027', '#f5f7fa', '#2f6bdf'] },
  { id: 'ember', name: 'Ember 暖调', desc: '衬线标题 · 适合观点类讲述', colors: ['#2a2018', '#fbf6ef', '#c4712a'] },
  { id: 'mono', name: 'Mono 等宽', desc: '代码感 · 深色 · 适合工具类教程', colors: ['#0f1115', '#e8edf5', '#3f9d70'] }
]

const docxTemplates = computed(() => templates.value.filter((t) => t.format === 'docx'))

const testingMap = reactive<Record<string, boolean>>({})
const testResultMap = ref<Record<string, ConnectionReport>>({})
const settingDefaultId = ref<string | null>(null)

const defaultProvider = computed(() => providers.value.find((p) => p.is_default) ?? null)

const roles = computed(() => {
  const defs: Array<{ kind: 'plus' | 'turbo' | 'max'; label: string }> = [
    { kind: 'plus', label: '主流程档位（plus）' },
    { kind: 'turbo', label: '总结流程档位（turbo）' },
    { kind: 'max', label: '任务级深问档位（max）' }
  ]
  return defs.map((d) => ({ ...d, providers: providers.value.filter((p) => p.kind === d.kind) }))
})

function reportClass(id: string): string {
  const r = testResultMap.value[id]
  if (!r) return ''
  return r.level === 'ok' ? 'ok' : r.level === 'warn' ? 'warn' : 'err'
}

async function loadProviders(): Promise<void> {
  listState.value = 'loading'
  try {
    const res = await listProviders()
    providers.value = res.items
    listState.value = 'ready'
  } catch (err) {
    providers.value = []
    listState.value = 'error'
    listError.value =
      err instanceof BackendUnavailableError ? '后端未启动，无法读取模型配置' : '模型配置读取失败'
  }
}

async function doTest(p: Provider): Promise<void> {
  testingMap[p.id] = true
  try {
    const r = await testProvider(p.id)
    testResultMap.value = { ...testResultMap.value, [p.id]: describeConnection(r) }
  } catch (err) {
    testResultMap.value = {
      ...testResultMap.value,
      [p.id]:
        err instanceof BackendUnavailableError
          ? { level: 'err', title: '后端未启动，无法完成测试', detail: '请确认本地服务已启动后重试。' }
          : { level: 'err', title: '测试请求未能完成', detail: (err as Error).message }
    }
  } finally {
    testingMap[p.id] = false
  }
}

async function doSetDefault(p: Provider): Promise<void> {
  settingDefaultId.value = p.id
  try {
    await setDefaultProvider(p.id)
    ElMessage.success(`已将「${p.name}」设为全局默认`)
    await loadProviders()
  } catch (err) {
    ElMessage.error(
      err instanceof BackendUnavailableError ? '后端未启动，设置失败' : '设为默认失败'
    )
  } finally {
    settingDefaultId.value = null
  }
}

async function askDelete(p: Provider): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `删除「${p.name}」会同时清除它保存在 Windows 凭据管理器中的密钥，且不可恢复。确认删除吗？`,
      '删除模型配置',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger'
      }
    )
  } catch {
    return // 用户取消
  }
  try {
    await deleteProvider(p.id)
    ElMessage.success('已删除该模型配置')
    delete testingMap[p.id]
    const rest = { ...testResultMap.value }
    delete rest[p.id]
    testResultMap.value = rest
    await loadProviders()
  } catch (err) {
    ElMessage.error(
      err instanceof BackendUnavailableError ? '后端未启动，删除失败' : '删除失败'
    )
  }
}

/* ---------------- 新增 / 编辑表单 ---------------- */
type FormKind = '' | 'turbo' | 'plus' | 'max'
interface FormModel {
  name: string
  base_url: string
  model_name: string
  kind: FormKind
  api_key: string
}
const EMPTY_FORM: FormModel = {
  name: '',
  base_url: 'https://api.deepseek.com',
  model_name: 'deepseek-flash',
  kind: '',
  api_key: ''
}

const dialogVisible = ref(false)
const editingId = ref<string | null>(null)
const formSaving = ref(false)
const form = ref<FormModel>({ ...EMPTY_FORM })

function openAdd(): void {
  editingId.value = null
  // 只预填非敏感的 DeepSeek 默认地址与模型名；服务商名与密钥留待用户填写。
  form.value = { ...EMPTY_FORM }
  dialogVisible.value = true
}

function openEdit(p: Provider): void {
  editingId.value = p.id
  // 绝不回填密钥：编辑态只知 has_key，api_key 输入框一律清空（留空即保留）。
  form.value = {
    name: p.name,
    base_url: p.base_url,
    model_name: p.model_name,
    kind: p.kind ?? '',
    api_key: ''
  }
  dialogVisible.value = true
}

async function saveProvider(): Promise<void> {
  const name = form.value.name.trim()
  const baseUrl = form.value.base_url.trim()
  const modelName = form.value.model_name.trim()
  if (!name) {
    ElMessage.warning('请填写服务商名称')
    return
  }
  if (!/^https?:\/\//i.test(baseUrl)) {
    ElMessage.warning('Base URL 需以 http:// 或 https:// 开头')
    return
  }
  if (!modelName) {
    ElMessage.warning('请填写模型名')
    return
  }

  const input = {
    name,
    base_url: baseUrl,
    model_name: modelName,
    kind: (form.value.kind || undefined) as ProviderKind | undefined,
    // 只写字段：空字符串即不携带（编辑保留原密钥）；提交后不存任何前端持久化。
    api_key: form.value.api_key.length > 0 ? form.value.api_key : undefined
  }

  formSaving.value = true
  try {
    if (editingId.value) {
      await updateProvider(editingId.value, input)
      ElMessage.success('已保存配置')
    } else {
      await createProvider(input)
      ElMessage.success('已新增配置')
    }
    dialogVisible.value = false
    form.value = { ...EMPTY_FORM }
    await loadProviders()
  } catch (err) {
    if (err instanceof BackendUnavailableError) {
      ElMessage.error('后端未启动，保存失败')
    } else if ((err as Error).message.includes('409')) {
      ElMessage.error('已存在同名配置，请换一个名称')
    } else {
      ElMessage.error('保存失败：' + (err as Error).message)
    }
  } finally {
    formSaving.value = false
  }
}

async function loadTemplates(): Promise<void> {
  tplState.value = 'loading'
  try {
    templates.value = (await getTemplates()).items
    tplState.value = 'ready'
  } catch (err) {
    templates.value = []
    tplState.value = 'error'
    tplError.value =
      err instanceof BackendUnavailableError ? '后端未启动，无法读取模板' : '模板读取失败'
  }
}

async function doSetDefaultTpl(name: string): Promise<void> {
  if (settingTpl.value) return
  settingTpl.value = name
  try {
    await setDefaultTemplate(name)
    ElMessage.success(`已将「${name}」设为全局默认模板`)
    await loadTemplates()
  } catch (err) {
    ElMessage.error(describeTplError(err, '设为默认'))
  } finally {
    settingTpl.value = null
  }
}

async function doRegister(): Promise<void> {
  const name = regName.value.trim()
  if (!name || regBusy.value) return
  regBusy.value = true
  try {
    await registerTemplate(name, false)
    ElMessage.success('已登记模板')
    regName.value = ''
    await loadTemplates()
  } catch (err) {
    ElMessage.error(describeTplError(err, '登记'))
  } finally {
    regBusy.value = false
  }
}

function describeTplError(err: unknown, action: string): string {
  if (err instanceof BackendUnavailableError) return `后端未启动，${action}失败`
  const msg = (err as Error).message || ''
  if (msg.includes('404')) return '模板文件不存在：请先把 .docx 放入 templates/ 目录'
  if (msg.includes('400')) return `该文件不可作为模板（只接受 .docx）：${tailDetail(msg)}`
  return `${action}失败：${msg}`
}

/** 从「请求失败：<code> <text> · <detail>」里取可读 detail 部分。 */
function tailDetail(msg: string): string {
  const idx = msg.indexOf('·')
  return idx >= 0 ? msg.slice(idx + 1).trim() : msg
}

onMounted(() => {
  loadProviders()
  loadTemplates()
})
</script>

<style scoped>
.form-wrap {
  width: 100%;
  max-width: 900px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
}

.list-loading {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

/* 配置行（对齐原型 .cfg） */
.cfg-list {
  display: flex;
  flex-direction: column;
}
.cfg {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  border: 1px solid var(--line-1);
  border-radius: var(--r-md);
  margin-bottom: var(--sp-2);
  flex-wrap: wrap;
}
.cfg:hover {
  border-color: var(--line-2);
}
.cfg.is-def {
  border-color: var(--brand-200);
  background: var(--brand-50);
}
.cfg-info {
  flex: 1;
  min-width: 220px;
}
.cfg-info b {
  font-size: var(--fs-md);
  color: var(--text-1);
}
.meta {
  font-size: var(--fs-xs);
  color: var(--text-3);
  margin-top: 2px;
}
.meta.mono {
  font-family: var(--font-mono);
  color: var(--text-2);
  word-break: break-all;
}
.cfg-tags {
  display: flex;
  gap: var(--sp-1);
  align-items: center;
  flex-wrap: wrap;
}
.cfg-acts {
  display: flex;
  gap: var(--sp-1);
  align-items: center;
  flex-wrap: wrap;
  margin-left: auto;
}
.cfg-test {
  width: 100%;
  margin-top: var(--sp-2);
}

.row-actions {
  margin-top: var(--sp-2);
}

/* 表单字段 */
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field > label {
  font-size: var(--fs-xs);
  color: var(--text-3);
  font-weight: 600;
  letter-spacing: 0.3px;
}
.hint {
  font-size: var(--fs-xs);
  color: var(--text-3);
  line-height: 1.55;
  margin: 6px 0 0;
}
.ico-sm {
  font-size: 13px;
  vertical-align: -2px;
}
.mono {
  font-family: var(--font-mono);
}

/* 默认档位 */
.default-line {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.default-line b {
  font-size: var(--fs-md);
  color: var(--text-1);
}
.tiers {
  list-style: none;
  margin: var(--sp-4) 0;
  padding: 0;
}
.tiers li {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3) 0;
  border-bottom: 1px solid var(--line-1);
}
.tiers li:last-child {
  border-bottom: 0;
}
.tier-name {
  font-size: var(--fs-md);
  color: var(--text-1);
  flex: 1;
  min-width: 0;
}
.tier-val {
  font-size: var(--fs-sm);
  color: var(--text-2);
}

/* 隐私清单 */
.note-list {
  list-style: none;
  margin: var(--sp-4) 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.note-list li {
  display: flex;
  gap: var(--sp-2);
  align-items: flex-start;
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.note-list .ico {
  color: var(--ok-fg);
  margin-top: 3px;
  flex: none;
}
.field + .note,
.field {
  margin-top: var(--sp-4);
}
.field:first-child {
  margin-top: 0;
}

/* 默认模板区 */
.sub-label {
  font-size: var(--fs-xs);
  color: var(--text-3);
  font-weight: 600;
  letter-spacing: 0.3px;
  margin-bottom: var(--sp-2);
}
.sub-label.spaced {
  margin-top: var(--sp-5);
}
.pend-empty {
  border: 1px dashed var(--line-3);
  border-radius: var(--r-sm);
  background: var(--bg-sunken);
  padding: var(--sp-3) var(--sp-4);
  font-size: var(--fs-sm);
  color: var(--text-3);
  text-align: center;
  line-height: 1.6;
}
.tpl-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.tpl-row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  border: 1px solid var(--line-1);
  border-radius: var(--r-md);
  margin-bottom: var(--sp-2);
  flex-wrap: wrap;
}
.tpl-row:hover {
  border-color: var(--line-2);
}
.tpl-row.sel {
  border-color: var(--brand-200);
  background: var(--brand-50);
}
.tpl-main {
  flex: 1;
  min-width: 200px;
}
.tpl-main b {
  font-size: var(--fs-md);
  color: var(--text-1);
}
.tpl-acts {
  margin-left: auto;
  display: flex;
  gap: var(--sp-1);
  align-items: center;
}
.err-t {
  color: var(--err-fg);
}
.mini {
  margin-left: 6px;
  vertical-align: 1px;
}
.reg-row {
  display: flex;
  gap: var(--sp-2);
  align-items: center;
  margin-top: var(--sp-3);
}
.reg-row .el-input {
  flex: 1;
  min-width: 0;
}
.theme-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: var(--sp-3);
}
.theme-opt {
  display: flex;
  gap: var(--sp-3);
  align-items: flex-start;
  border: 1px solid var(--line-1);
  border-radius: var(--r-md);
  padding: var(--sp-3);
  cursor: pointer;
  background: var(--bg-surface);
}
.theme-opt:hover {
  border-color: var(--brand-200);
}
.theme-opt input {
  margin-top: 3px;
  accent-color: var(--brand-500);
  flex: none;
}
.theme-opt > span {
  min-width: 0;
}
.theme-opt b {
  display: block;
  font-size: var(--fs-sm);
}
.theme-opt .td {
  display: block;
  font-size: var(--fs-xs);
  color: var(--text-3);
}
.theme-opt.sel {
  border-color: var(--brand-500);
  background: var(--brand-50);
  box-shadow: 0 0 0 2px var(--brand-50);
}
.theme-chips {
  display: flex;
  gap: 3px;
  margin-top: 6px;
}
.theme-chips i {
  width: 14px;
  height: 14px;
  border-radius: 3px;
  display: block;
  border: 1px solid rgba(0, 0, 0, 0.08);
}

@media (max-width: 820px) {
  .col-hide {
    display: none;
  }
}
</style>

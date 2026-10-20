<template>
  <div
    v-if="open"
    class="deck"
    role="dialog"
    aria-modal="true"
    aria-label="单文件 HTML 演示"
    tabindex="-1"
  >
    <!-- 顶栏：文件名 / 主题 / 单文件声明 / 页码 / 退出 -->
    <div class="deck-bar">
      <b>{{ filename || '演示' }}</b>
      <span class="tag" v-if="themeName">{{ themeName }}</span>
      <span class="tag">单文件 · 双击即可打开 · 无外部依赖</span>
      <span class="tag" v-if="total > 0">第 {{ current }} / {{ total }} 页</span>
      <span class="sp"></span>
      <button class="dk-btn" type="button" @click="close">
        <el-icon class="ico"><Close /></el-icon>退出（Esc）
      </button>
    </div>

    <!-- 舞台：iframe 渲染自包含产物；降级态给真实路径 -->
    <div class="deck-stage">
      <!--
        沙箱取舍（本组件唯一的成型决策）：`allow-same-origin` 是必需的——
        产物没有 postMessage 接口，父级要驱动翻页（向同源 document 合成按键）并读取页码，
        就必须同源；去掉它，底栏的上一页/下一页与页码同步会一起失效。
        这样做是安全的，因为产物里**不可能存在非我们自己的脚本**：
        产物由本机后端生成，所有模型派生的文本（标题/正文/列表/表格/讲者备注）
        都经 `backend/app/generation/deck.py::_escape` 转义，产物内的脚本只有自写的翻页运行时，
        且生成时的完整性检查断言外部网络引用为 0。也就是说——**转义才是安全边界，沙箱只是外层包装**。
      -->
      <iframe
        v-if="hasHtml"
        ref="frame"
        class="deck-frame"
        title="单文件 HTML 演示预览"
        :srcdoc="html"
        sandbox="allow-scripts allow-same-origin"
        @load="onFrameLoad"
      ></iframe>
      <div v-else class="deck-fallback">
        <el-icon class="ico"><Film /></el-icon>
        <b>应用内预览暂不可用</b>
        <p>
          演示由 `GET /api/deliverables/{id}` 投递；当前没取到内容——通常是后端未启动，
          或该产物文件已被移动/删除。这是<b>如实降级</b>，不伪造预览。
        </p>
        <p class="fp mono" v-if="filePath">{{ filePath }}</p>
        <p class="muted">可在文件管理器中定位上面路径后双击，离线 `file://` 直接打开，键盘翻页与演讲者模式（S）可用。</p>
      </div>
    </div>

    <!-- 底部翻页栏：页码圆点 + 上一页 / 下一页 + 按键提示 -->
    <div class="deck-foot-bar">
      <button class="dk-btn" type="button" :disabled="current <= 1 || !hasHtml" @click="turn(-1)">
        <el-icon class="ico"><ArrowLeft /></el-icon>上一页
      </button>
      <div class="dk-dots" aria-hidden="true">
        <i v-for="n in dotCount" :key="n" :class="{ on: n === current }"></i>
      </div>
      <span class="xs">← / → · PageUp / PageDown · 空格 · Home / End 翻页 · S 演讲者模式</span>
      <span class="sp"></span>
      <button class="dk-btn" type="button" :disabled="!hasHtml || (total > 0 && current >= total)" @click="turn(1)">
        下一页<el-icon class="ico"><ArrowRight /></el-icon>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowLeft, ArrowRight, Close, Film } from '@element-plus/icons-vue'

const props = defineProps<{
  open: boolean
  html: string
  filename: string
  themeName: string
  slides: number
  filePath: string
}>()
const emit = defineEmits<{ (e: 'close'): void }>()

const frame = ref<HTMLIFrameElement | null>(null)
const current = ref(1)
const total = ref(0)
let observer: MutationObserver | null = null
let poll: ReturnType<typeof setInterval> | null = null

const hasHtml = computed(() => props.html.trim().length > 0)
const dotCount = computed(() => Math.max(0, Math.min(total.value || props.slides || 0, 40)))

function frameDoc(): Document | null {
  try {
    return frame.value?.contentDocument ?? null
  } catch {
    return null // 跨源读不到（不应发生：产物为同源 blob / srcdoc）
  }
}

function syncFromFrame(): void {
  const doc = frameDoc()
  if (!doc) return
  const c = doc.getElementById('current')?.textContent?.trim()
  const t = doc.getElementById('total')?.textContent?.trim()
  if (c && Number.isFinite(Number(c))) current.value = Number(c)
  if (t && Number.isFinite(Number(t))) total.value = Number(t)
}

function onFrameLoad(): void {
  total.value = props.slides || 0
  syncFromFrame()
  cleanupObservers()
  const doc = frameDoc()
  if (doc) {
    observer = new MutationObserver(() => syncFromFrame())
    observer.observe(doc.body || doc.documentElement, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true
    })
  }
  poll = setInterval(syncFromFrame, 500)
}

/** 通过向同源 iframe 的 document 合成按键，驱动产物自带的翻页运行时（保持产物未被修改）。 */
function turn(delta: number): void {
  const doc = frameDoc()
  const key = delta > 0 ? 'ArrowRight' : 'ArrowLeft'
  if (doc) {
    doc.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
  }
}

function close(): void {
  emit('close')
}

function onKey(e: KeyboardEvent): void {
  if (!props.open) return
  // 焦点在 iframe 内时，←/→/空格 等由产物自身处理；此处兜底：焦点在弹层外时也支持翻页与 Esc 退出。
  if (e.key === 'Escape') {
    close()
  } else if (e.key === 'ArrowRight' || e.key === 'PageDown') {
    turn(1)
  } else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
    turn(-1)
  }
}

function cleanupObservers(): void {
  if (observer) {
    observer.disconnect()
    observer = null
  }
  if (poll) {
    clearInterval(poll)
    poll = null
  }
}

watch(
  () => props.open,
  (o) => {
    if (o) {
      current.value = 1
      total.value = props.slides || 0
      document.addEventListener('keydown', onKey)
      void nextTick(() => frame.value?.focus?.())
    } else {
      document.removeEventListener('keydown', onKey)
      cleanupObservers()
    }
  }
)

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey)
  cleanupObservers()
})
</script>

<style scoped>
.deck {
  position: fixed;
  inset: 0;
  z-index: 70;
  display: flex;
  flex-direction: column;
  background: #12151b;
  color: #e8edf5;
}
.deck-bar,
.deck-foot-bar {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
  padding: var(--sp-3) var(--sp-5);
}
.deck-bar {
  border-bottom: 1px solid rgba(255, 255, 255, 0.09);
}
.deck-foot-bar {
  border-top: 1px solid rgba(255, 255, 255, 0.09);
}
.deck-bar b {
  font-size: var(--fs-sm);
  font-family: var(--font-mono);
}
.deck-bar .sp,
.deck-foot-bar .sp {
  margin-left: auto;
}
.deck-bar .xs {
  color: rgba(232, 237, 245, 0.62);
}
.tag {
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #e8edf5;
  border-radius: var(--r-pill);
  padding: 2px 9px;
  font-size: var(--fs-xs);
  white-space: nowrap;
}
.deck-stage {
  flex: 1;
  min-height: 0;
  display: grid;
  place-items: center;
  padding: var(--sp-3);
  overflow: hidden;
}
.deck-frame {
  width: 100%;
  height: 100%;
  max-width: min(1160px, 96vw);
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: var(--r-md);
  background: #fff;
  box-shadow: 0 30px 70px rgba(0, 0, 0, 0.5);
}
.deck-fallback {
  max-width: 560px;
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  align-items: center;
  color: rgba(232, 237, 245, 0.82);
}
.deck-fallback .ico {
  font-size: 30px;
  color: rgba(232, 237, 245, 0.55);
}
.deck-fallback b {
  font-size: var(--fs-md);
  color: #e8edf5;
}
.deck-fallback p {
  margin: 0;
  font-size: var(--fs-sm);
  line-height: 1.6;
}
.deck-fallback .fp {
  word-break: break-all;
  color: #e8edf5;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: var(--r-sm);
  padding: var(--sp-2) var(--sp-3);
  font-size: var(--fs-xs);
}
.dk-btn {
  height: 30px;
  padding: 0 var(--sp-3);
  border-radius: var(--r-sm);
  border: 1px solid rgba(255, 255, 255, 0.24);
  background: rgba(255, 255, 255, 0.07);
  color: #e8edf5;
  font-size: var(--fs-sm);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}
.dk-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.16);
}
.dk-btn:disabled {
  opacity: 0.38;
  cursor: not-allowed;
}
.dk-btn:focus-visible {
  outline: 2px solid #fff;
  outline-offset: 2px;
}
.dk-btn .ico {
  vertical-align: -2px;
}
.dk-dots {
  display: flex;
  gap: 5px;
  align-items: center;
}
.dk-dots i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.26);
}
.dk-dots i.on {
  background: #fff;
}
.xs {
  font-size: var(--fs-xs);
  color: rgba(232, 237, 245, 0.6);
}
.mono {
  font-family: var(--font-mono);
}
</style>

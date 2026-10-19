<template>
  <el-container class="workbench">
    <!-- 左侧栏：导航 + 任务历史列表占位 -->
    <el-aside width="260px" class="sidebar">
      <div class="brand">
        <el-icon class="brand-icon"><Compass /></el-icon>
        <span class="brand-text">ThinkForge</span>
      </div>

      <el-menu :default-active="activeRoute" router class="nav-menu">
        <el-menu-item index="/creation">
          <el-icon><EditPen /></el-icon>
          <span>主题创作</span>
        </el-menu-item>
        <el-menu-item index="/analysis">
          <el-icon><Document /></el-icon>
          <span>资料分析</span>
        </el-menu-item>
        <el-menu-item index="/history">
          <el-icon><Clock /></el-icon>
          <span>任务历史</span>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <span>设置</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-section">
        <div class="sidebar-section-title">最近任务</div>
        <div class="sidebar-placeholder">
          任务历史列表占位<br />
          （工单 05：任务历史与续作）
        </div>
      </div>
    </el-aside>

    <!-- 中部内容区 + 底部输入胶囊区 -->
    <el-container class="main-column">
      <el-main class="content-area">
        <router-view />
      </el-main>

      <div class="composer-area">
        <div class="composer">
          <el-input
            v-model="composerText"
            class="composer-input"
            placeholder="输入消息，与工作台对话（占位，尚未接入后端）"
            :disabled="true"
            @keyup.enter="onSend"
          >
            <template #suffix>
              <el-button type="primary" circle :icon="Promotion" @click="onSend" />
            </template>
          </el-input>
        </div>
      </div>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Promotion } from '@element-plus/icons-vue'

const route = useRoute()

// 侧栏高亮跟随当前路由（/creation、/analysis、/history、/settings）。
const activeRoute = computed(() => route.path)

const composerText = ref('')

// 输入区为骨架占位，交互逻辑在后续工单接入。
function onSend(): void {
  // TODO(工单 04)：对接拷问闭环后端。
  composerText.value = ''
}
</script>

<style scoped>
.workbench {
  height: 100vh;
}

/* 左侧栏 */
.sidebar {
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--el-border-color-light);
  background-color: var(--el-bg-color-page);
  overflow: hidden;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 18px 20px;
  font-size: 18px;
  font-weight: 600;
  color: var(--el-color-primary);
}

.brand-icon {
  font-size: 22px;
}

.nav-menu {
  border-right: none;
  background-color: transparent;
}

.sidebar-section {
  flex: 1;
  padding: 12px 16px;
  overflow: auto;
}

.sidebar-section-title {
  margin-bottom: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.sidebar-placeholder {
  padding: 12px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-placeholder);
  background-color: var(--el-fill-color-light);
  border-radius: 6px;
}

/* 右侧主列 */
.main-column {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.content-area {
  flex: 1;
  overflow: auto;
  padding: 24px;
}

/* 底部输入胶囊区 */
.composer-area {
  padding: 12px 24px 20px;
  border-top: 1px solid var(--el-border-color-light);
  background-color: var(--el-bg-color);
}

.composer {
  max-width: 860px;
  margin: 0 auto;
}

.composer :deep(.el-input__wrapper) {
  border-radius: 999px;
  padding-left: 18px;
}
</style>
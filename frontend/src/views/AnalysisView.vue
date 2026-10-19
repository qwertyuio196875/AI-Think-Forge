<template>
  <section class="view" aria-label="资料分析">
    <header class="view-head">
      <div class="head-row">
        <div class="head-title">
          <h1>资料分析</h1>
          <p>单份资料的「解析 → 总结」快捷流程，默认不进入拷问；总结可直接送入主题创作</p>
        </div>
        <div class="head-actions">
          <el-tag type="info" effect="plain" size="small">总结默认 ≤500 字</el-tag>
        </div>
      </div>
    </header>

    <div class="view-body">
      <div class="split">
        <!-- 左：发起分析（结构骨架） -->
        <div class="panel">
          <div class="panel-head">
            <h3>发起分析</h3>
            <span class="right xs muted">DOCX / PDF / TXT / MD / PPTX / 网页 URL</span>
          </div>
          <div class="panel-body">
            <div class="drop" aria-hidden="true">
              <el-icon class="ico"><Upload /></el-icon>
              <b>拖拽文件到此处，或点击选择文件</b>
              <span>单文件不超过 50 MB · 类型与大小先校验再解析</span>
            </div>

            <div class="url-field">
              <el-input disabled placeholder="粘贴公开网页 URL，抓取并解析（将在 TB-7 接入）">
                <template #prepend>URL</template>
              </el-input>
            </div>

            <div class="note info" style="margin-top: var(--sp-4)">
              <el-icon class="ico"><InfoFilled /></el-icon>
              <div class="note-body">
                <span>本单为结构骨架：文件上传、本地分块解析、URL 抓取与安全校验将在 TB-7 接入。</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 右：总结结果（空态） -->
        <div class="panel">
          <div class="panel-head">
            <h3>总结结果</h3>
            <span class="right xs muted">主题 / 核心观点 / 关键内容 / 重要数据 / 结论</span>
          </div>
          <div class="panel-body">
            <div class="empty">
              <el-icon class="ico-lg"><Document /></el-icon>
              <b>暂无分析结果</b>
              <p>选中或上传一份资料后，这里显示忠实原文的总结；总结可一键送入主题创作继续拷问。</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { Document, InfoFilled, Upload } from '@element-plus/icons-vue'
</script>

<style scoped>
.split {
  display: grid;
  grid-template-columns: minmax(340px, 440px) minmax(0, 1fr);
  gap: var(--sp-6);
  align-content: start;
  width: 100%;
  max-width: 1180px;
  margin: 0 auto;
}
.url-field {
  margin-top: var(--sp-4);
}
@media (max-width: 1100px) {
  .split {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--sp-5);
  }
}
</style>

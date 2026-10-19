<template>
  <section class="view" aria-label="任务历史">
    <header class="view-head">
      <div class="head-row">
        <div class="head-title">
          <h1>任务历史</h1>
          <p>任务、对话、方案与成品全程持久化；关闭工作台不等于从头再来</p>
        </div>
      </div>
    </header>

    <div class="view-body">
      <div class="wrap wrap--wide">
        <!-- 工具条：筛选标签 + 搜索（本单为骨架，过滤与检索属 TB-10） -->
        <div class="toolbar">
          <div class="tabs" role="tablist" aria-label="任务筛选">
            <button class="tab is-active" type="button" role="tab" aria-selected="true" disabled>全部任务</button>
            <button class="tab" type="button" role="tab" aria-selected="false" disabled>主题创作</button>
            <button class="tab" type="button" role="tab" aria-selected="false" disabled>资料分析</button>
            <button class="tab" type="button" role="tab" aria-selected="false" disabled>回收站</button>
          </div>
          <el-input class="search" disabled placeholder="搜索任务名称或关键词">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <span class="small muted">显示 — 条</span>
        </div>

        <table class="tbl">
          <thead>
            <tr>
              <th style="width: 40%">任务</th>
              <th>类型</th>
              <th style="width: 18%">状态</th>
              <th>更新</th>
              <th class="num">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td colspan="5" class="cell-empty">
                <div class="empty">
                  <el-icon class="ico-lg"><Clock /></el-icon>
                  <b>暂无任务记录</b>
                  <p>任务列表、状态与续作入口将在 TB-10 接入。可先到「主题创作」新建一条任务。</p>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { Clock, Search } from '@element-plus/icons-vue'
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  margin-bottom: var(--sp-4);
  flex-wrap: wrap;
}
.tabs {
  display: flex;
  gap: var(--sp-1);
  padding: var(--sp-1);
  background: var(--bg-sunken);
  border-radius: var(--r-sm);
  width: max-content;
}
.tab {
  border: 0;
  background: none;
  padding: 5px var(--sp-3);
  border-radius: var(--r-xs);
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.tab.is-active {
  background: var(--bg-surface);
  color: var(--text-1);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(20, 28, 46, 0.08);
}
.tab:disabled {
  cursor: default;
}
.search {
  flex: 1;
  min-width: 180px;
  max-width: 320px;
}
.num {
  text-align: right;
}
.cell-empty {
  padding: 0;
  border-bottom: 0;
}
</style>

<template>
  <section class="view" aria-label="设置">
    <header class="view-head">
      <div class="head-row">
        <div class="head-title">
          <h1>设置</h1>
          <p>模型配置 · 默认档位 · 本地与隐私边界</p>
        </div>
        <div class="head-actions">
          <el-tag type="info" effect="plain" size="small">配置管理将在 TB-1 接入</el-tag>
        </div>
      </div>
    </header>

    <div class="view-body">
      <div class="form-wrap">
        <!-- 模型配置 -->
        <section class="sec">
          <header>
            <h3>模型配置</h3>
            <p>业务不绑定厂商：统一走 OpenAI 兼容接口，可新增、编辑、删除、设为默认，并做连接测试</p>
          </header>
          <div class="sec-body">
            <div class="note info">
              <el-icon class="ico"><InfoFilled /></el-icon>
              <div class="note-body">
                <b>还没有模型配置</b>
                <span>新增配置、设为默认、连接测试与密钥保存将在 TB-1 接入。</span>
              </div>
            </div>
            <div class="row-actions">
              <el-button type="primary" disabled>
                <el-icon class="ico"><Plus /></el-icon>
                <span>新增模型配置</span>
              </el-button>
            </div>
          </div>
        </section>

        <!-- 默认档位与额度 -->
        <section class="sec">
          <header>
            <h3>默认档位与额度</h3>
            <p>主流程 / 总结 / 任务级深问的默认档位，以及百炼额度统计</p>
          </header>
          <div class="sec-body">
            <ul class="tiers">
              <li>
                <span class="tier-name">主流程档位</span>
                <span class="tier-val muted">未配置</span>
              </li>
              <li>
                <span class="tier-name">总结流程档位</span>
                <span class="tier-val muted">未配置</span>
              </li>
              <li>
                <span class="tier-name">任务级深问档位</span>
                <span class="tier-val muted">未配置</span>
              </li>
              <li>
                <span class="tier-name">百炼额度</span>
                <span class="tier-val muted">统计将在 TB-1 接入</span>
              </li>
            </ul>
          </div>
        </section>

        <!-- 本地与隐私 -->
        <section class="sec">
          <header>
            <h3>本地与隐私</h3>
            <p>系统运行的安全边界，始终生效</p>
          </header>
          <div class="sec-body">
            <ul class="note-list">
              <li>
                <el-icon class="ico"><Select /></el-icon>
                <span>仅监听本机回环（127.0.0.1），同网段他人无法访问</span>
              </li>
              <li>
                <el-icon class="ico"><Select /></el-icon>
                <span>文件访问限定在工作目录白名单内；上传校验扩展名与大小</span>
              </li>
              <li>
                <el-icon class="ico"><Select /></el-icon>
                <span>密钥存于 Windows 凭据管理器，不进入源码 / Git / 前端 / SQLite / 日志</span>
              </li>
              <li>
                <el-icon class="ico"><Select /></el-icon>
                <span>调用云端模型前会告知：提示词与资料片段可能发送给所配置的服务商</span>
              </li>
            </ul>
          </div>
        </section>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { InfoFilled, Plus, Select } from '@element-plus/icons-vue'
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
.row-actions {
  margin-top: var(--sp-4);
}
.tiers {
  list-style: none;
  margin: 0;
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
}
.note-list {
  list-style: none;
  margin: 0;
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
</style>

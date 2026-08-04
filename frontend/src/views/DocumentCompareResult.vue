<template>
  <div class="result-page">
    <!-- 结果头部 -->
    <div class="result-header">
      <div class="result-header-left">
        <h1 class="page-title">文档比对结果</h1>
      </div>
      <div class="result-header-right">
        <div class="legend">
          <div class="legend-item">
            <div class="legend-color" style="background: rgba(239, 68, 68, 0.5);"></div>
            <span>删除的内容</span>
          </div>
          <div class="legend-item">
            <div class="legend-color" style="background: rgba(16, 185, 129, 0.5);"></div>
            <span>新增的内容</span>
          </div>
          <div class="legend-item">
            <div class="legend-color" style="background: rgba(245, 158, 11, 0.5);"></div>
            <span>修改的内容</span>
          </div>
        </div>
        <div class="similarity-badge">
          <span class="similarity-label">文本相似度</span>
          <span class="similarity-value">{{ similarity2 }}</span>
        </div>
      </div>
    </div>

    <!-- 双栏预览 -->
    <div class="result-content">
      <el-row :gutter="16">
        <el-col :span="12">
          <iframe
            :src="benchmark_file_url"
            width="100%"
            class="result-iframe"
          ></iframe>
        </el-col>
        <el-col :span="12">
          <iframe
            :src="compare_file_url"
            width="100%"
            class="result-iframe"
          ></iframe>
        </el-col>
      </el-row>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import config from "/config"
const route = useRoute()
const { benchmark_file, compare_file, similarity } = route.query

const similarityNum = Number(similarity);
const similarity2 = similarityNum.toFixed(2);

const base_url = config.docCompare + '/static/'
const benchmark_file_url = ref(
  base_url + benchmark_file
)
const compare_file_url = ref(
  base_url + compare_file
)

const iframeHeight = ref(0)

const updateHeight = () => {
  iframeHeight.value = window.innerHeight - 140
}

onMounted(() => {
  updateHeight()
  window.addEventListener('resize', updateHeight)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateHeight)
})
</script>

<style scoped>
.result-page {
  padding: var(--space-lg);
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-md);
  flex-shrink: 0;
}

.result-header-right {
  display: flex;
  align-items: center;
  gap: 24px;
}

.legend {
  display: flex;
  gap: 16px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--slate);
}

.legend-color {
  width: 20px;
  height: 8px;
  border-radius: 2px;
}

.similarity-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: var(--accent-soft);
  border-radius: var(--radius-sm);
}

.similarity-label {
  font-size: 13px;
  color: var(--slate);
}

.similarity-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--accent);
}

.result-content {
  flex: 1;
  overflow: hidden;
}

.result-iframe {
  height: calc(100vh - 140px);
  border: 1px solid var(--mist);
  border-radius: var(--radius-md);
  display: block;
}
</style>

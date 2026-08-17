<template>
  <div class="page-container">
    <div class="retrieval-page">
      <header class="retrieval-header">
        <h1 class="page-title"><span class="title-accent" />文本搜语音</h1>
      </header>

      <section class="retrieval-controls card">
        <div class="control-row">
          <div class="control-field">
            <span class="control-label">索引库</span>
            <el-select v-model="indexName" placeholder="选择索引" :disabled="loading">
              <el-option
                v-for="item in indexLibrary"
                :key="item.value"
                :label="item.label"
                :value="item.label"
              />
            </el-select>
          </div>
          <div class="control-field">
            <span class="control-label">返回数量</span>
            <el-input-number v-model="topK" :step="1" :min="1" :max="50" :disabled="loading" />
          </div>
        </div>
        <div class="search-row">
          <el-input
            v-model="text"
            placeholder="例如：合同金额、重要讲话…"
            :disabled="loading"
            @keydown.enter.prevent="submitSearch"
          />
          <div class="retrieval-actions">
            <el-button type="primary" :loading="loading" @click="submitSearch">开始检索</el-button>
            <el-button :disabled="loading" @click="reset">重置</el-button>
          </div>
        </div>
      </section>

      <section class="retrieval-results">
        <!-- 初始 -->
        <div v-if="!loading && count === null && !error" class="retrieval-state card">
          <div class="state-icon">🔊</div>
          <div class="state-title">输入关键词开始检索</div>
          <div class="state-hint">将返回语义最匹配的 {{ topK }} 段音频，可在播放器中定位命中片段。</div>
        </div>
        <!-- 加载 -->
        <div v-else-if="loading" class="retrieval-state retrieval-loading card">
          <div class="spinner" />
          <div class="state-title">检索中…</div>
          <div class="state-hint">正在比对音频文本特征，请稍候。</div>
        </div>
        <!-- 错误 -->
        <div v-else-if="error" class="retrieval-state is-error card">
          <div class="state-icon">⚠</div>
          <div class="state-title">检索失败</div>
          <div class="state-hint">{{ error }}</div>
        </div>
        <!-- 空 -->
        <div v-else-if="count === 0" class="retrieval-state card">
          <div class="state-icon">🔇</div>
          <div class="state-title">未找到匹配音频</div>
          <div class="state-hint">换个关键词试试。</div>
        </div>
        <!-- 结果 -->
        <template v-else>
          <RetrievalGallery :items="galleryItems" />
        </template>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import request from '@/utils/request'
import { ElMessage } from 'element-plus'
import config from '/config'
import RetrievalGallery from '@/components/RetrievalGallery.vue'

const BASE = config.multimodel

const indexLibrary = ref([])
const indexName = ref('base')
const topK = ref(5)
const text = ref('')
const matched = ref([])
const count = ref(null)
const loading = ref(false)
const error = ref('')

const init = () => {
  request
    .get('/get_audios_dir/?include_files=true', { serverName: 'multimodel' })
    .then((res) => {
      if (res.status === 200) {
        indexLibrary.value = (res.data.indices || []).map((i) => {
          const name = (i.name || '').replace(/\.index$/, '')
          return { label: name, value: name }
        })
      }
    })
    .catch(() => {})
}
init()

// 检索结果映射为画廊 items：用浏览器 URL（rel_path）；兼容旧版返回绝对路径的情况
const galleryItems = computed(() =>
  matched.value.map((it) => {
    const rel =
      it.rel_path ||
      (it.audio_path || '').split('/audios/').pop() ||
      ''
    return {
      kind: 'audio',
      url: `${BASE}/audios/${rel}`,
      start: Number(it.start ?? 0),
      end: Number(it.end ?? 0),
      text: it.text || '',
      score: Number(it.score ?? 0).toFixed(4),
    }
  }),
)

const submitSearch = () => {
  if (!text.value.trim()) {
    ElMessage.warning('请先输入检索文本')
    return
  }
  loading.value = true
  error.value = ''
  request
    .post(
      '/text_search_audios/',
      { text: text.value },
      {
        params: {
          index_name: indexName.value,
          value: topK.value,
          return_audio: false,
          return_clip: false,
        },
        serverName: 'multimodel',
        timeout: 120000,
      },
    )
    .then((res) => {
      matched.value = res.data.matches || []
      count.value = res.data.count ?? matched.value.length
    })
    .catch((err) => {
      error.value = err?.response?.data?.detail || err.message || '请求失败，请稍后重试'
    })
    .finally(() => {
      loading.value = false
    })
}

const reset = () => {
  text.value = ''
  indexName.value = 'base'
  topK.value = 5
  matched.value = []
  count.value = null
  error.value = ''
}
</script>

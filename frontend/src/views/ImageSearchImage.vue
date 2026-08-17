<template>
  <div class="page-container">
    <div class="retrieval-page">
      <header class="retrieval-header">
        <h1 class="page-title"><span class="title-accent" />图搜图</h1>
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
          <div class="upload-zone">
            <label class="upload-trigger">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              选择图片
              <input
                ref="fileInput"
                type="file"
                multiple
                accept="image/*"
                hidden
                :disabled="loading"
                @change="onFilesChange"
              />
            </label>
            <div v-if="files.length" class="file-chips">
              <span v-for="(f, i) in files" :key="i" class="file-chip">
                <span class="chip-name" :title="f.name">{{ f.name }}</span>
                <span class="chip-remove" @click="removeFile(i)">×</span>
              </span>
            </div>
            <span v-else class="upload-hint">支持多选，仅图片</span>
          </div>
          <div class="retrieval-actions">
            <el-button type="primary" :loading="loading" @click="submitSearch">开始检索</el-button>
            <el-button :disabled="loading" @click="reset">重置</el-button>
          </div>
        </div>
      </section>

      <section class="retrieval-results">
        <!-- 初始 -->
        <div v-if="!loading && count === null && !error" class="retrieval-state card">
          <div class="state-icon">🖼</div>
          <div class="state-title">上传图片开始检索</div>
          <div class="state-hint">选择一张图片，将返回视觉最相似的 {{ topK }} 张结果。</div>
        </div>
        <!-- 加载 -->
        <div v-else-if="loading" class="retrieval-state retrieval-loading card">
          <div class="spinner" />
          <div class="state-title">检索中…</div>
          <div class="state-hint">正在比对图像特征，请稍候。</div>
        </div>
        <!-- 错误 -->
        <div v-else-if="error" class="retrieval-state is-error card">
          <div class="state-icon">⚠</div>
          <div class="state-title">检索失败</div>
          <div class="state-hint">{{ error }}</div>
        </div>
        <!-- 空 -->
        <div v-else-if="count === 0" class="retrieval-state card">
          <div class="state-icon">🖼</div>
          <div class="state-title">未找到相似图片</div>
          <div class="state-hint">换一张图片或选择其他索引库试试。</div>
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
const indexName = ref('global')
const topK = ref(5)
const files = ref([])
const fileInput = ref(null)
const matched = ref([])
const count = ref(null)
const loading = ref(false)
const error = ref('')

const init = () => {
  request
    .get('/get_images_dir/?include_files=true', { serverName: 'multimodel' })
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

const onFilesChange = (e) => {
  files.value = Array.from(e.target.files || [])
}
const removeFile = (i) => {
  files.value.splice(i, 1)
  if (fileInput.value) fileInput.value.value = ''
}

const galleryItems = computed(() =>
  matched.value.map((it) => ({
    kind: 'image',
    path: it.path,
    thumb_url: `${BASE}/thumbnails/${it.path}`,
    url: `${BASE}/images/${it.path}`,
    score: Number(it.score ?? 0).toFixed(4),
  })),
)

const submitSearch = () => {
  if (!files.value.length) {
    ElMessage.warning('请先选择图片')
    return
  }
  const form = new FormData()
  files.value.forEach((f) => form.append('images', f, f.name))
  loading.value = true
  error.value = ''
  request
    .post(
      '/images_search_images/',
      form,
      {
        params: {
          index_name: indexName.value,
          value: topK.value,
          return_original: false,
          return_thumbnail: false,
        },
        serverName: 'multimodel',
        timeout: 60000,
      },
    )
    .then((res) => {
      matched.value = res.data.matched_images || []
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
  indexName.value = 'global'
  topK.value = 5
  files.value = []
  matched.value = []
  count.value = null
  error.value = ''
  if (fileInput.value) fileInput.value.value = ''
}
</script>

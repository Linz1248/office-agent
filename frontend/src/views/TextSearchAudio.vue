<template>
    <div class="page-container">
        <h1 class="page-title">文本搜音频</h1>
        <div class="search-content">
            <div class="search-controls card">
                <el-form :inline="true">
                    <el-form-item label="索引库">
                        <el-select v-model="indexName" placeholder="选择" style="width: 150px">
                            <el-option
                                v-for="item in indexLibary"
                                :key="item.value"
                                :label="item.label"
                                :value="item.label"
                            />
                        </el-select>
                    </el-form-item>

                    <el-form-item label="Top-K">
                        <el-input-number v-model="top_k" :step="1" :min="0"></el-input-number>
                    </el-form-item>

                    <el-form-item>
                        <el-checkbox v-model="return_audio">返回原始音频</el-checkbox>
                        <el-checkbox v-model="return_clip">返回截取音频</el-checkbox>
                    </el-form-item>
                </el-form>

                <div class="search-bar">
                    <span class="search-label">检索文本</span>
                    <el-input v-model="text" style="flex:1; max-width:400px" placeholder="请输入文本" />
                    <el-button type="primary" @click="submitSearch">开始检索</el-button>
                    <el-button type="info" plain @click="reset">重置</el-button>
                </div>
            </div>

            <el-divider />

            <div v-if="count !== null" class="results-section">
                <p class="results-count">共找到 {{ count }} 条匹配音频</p>

                <el-row :gutter="16">
                    <el-col v-for="(it, idx) in matched" :key="idx" :span="6" style="margin-bottom:16px">
                        <el-card class="result-card">
                            <div class="result-audio">
                                <audio
                                    v-if="it.audio_base64"
                                    :src="toDataUrl(it.audio_base64, 'mp3')"
                                    controls
                                    style="width:100%"
                                />
                                <audio
                                    v-else-if="it.clip_base64"
                                    :src="toDataUrl(it.clip_base64, 'wav')"
                                    controls
                                    style="width:100%"
                                />
                                <div v-else class="no-audio">不可试听</div>
                            </div>

                            <div class="result-info">
                                <div><strong>路径:</strong> {{ it.audio_path }}</div>
                                <div><strong>文本:</strong> {{ it.text }}</div>
                                <div><strong>起止:</strong> {{ it.start.toFixed(2) }}s ~ {{ it.end.toFixed(2) }}s</div>
                                <div><strong>置信度:</strong> {{ it.score.toFixed(4) }}</div>
                                <div v-if="it.error" style="color:var(--danger)">{{ it.error }}</div>
                            </div>
                        </el-card>
                    </el-col>
                </el-row>
            </div>
        </div>
    </div>
</template>

<script setup>
import { ref } from 'vue'
import request from '@/utils/request'
import { ElMessage, ElLoading } from 'element-plus'

const indexLibary = ref([])
const init = () => {
    request.get('/', { serverName: 'docExtract' })
    .then(res => {
      if (res.status != 200)
        return
    })
    request.get('/get_audios_dir/?include_files=true', { serverName: 'multimodel' }).then(res => {
        if (res.status === 200) {
            indexLibary.value = res.data.indices.map(item => ({
                label: item.name.replace(/\.index$/, ''),
                value: item.name.replace(/\.index$/, '')
            }))
        } else {
            ElMessage.error('初始化失败')
        }
    })
}
init()

const text = ref('')
const indexName = ref('base')
const top_k = ref(5)
const return_audio = ref(false)
const return_clip = ref(true)

const matched = ref([])
const count = ref(null)
const message = ref('')
let loadingInstance = null

const toDataUrl = (base64Str, ext = 'wav') => {
    return `data:audio/${ext};base64,${base64Str}`
}

const submitSearch = () => {
    if (!text.value.trim()) {
        ElMessage.error('请先输入文本')
        return
    }

    loadingInstance = ElLoading.service({
        lock: true,
        text: '检索中，请稍候…',
        background: 'rgba(0, 0, 0, 0.5)'
    })

    request.post('/text_search_audios/',{ text: text.value },
        {
            params: {
                index_name: indexName.value,
                value: top_k.value,
                return_audio: return_audio.value,
                return_clip: return_clip.value
            },
            serverName: 'multimodel',
            timeout: 1200000
        }
    ).then(res => {
        if (res.status === 200) {
            matched.value = res.data.matches
            count.value = res.data.count
            message.value = res.data.message
            ElMessage.success('检索成功')
        } else {
            ElMessage.error('检索失败')
        }
    }).catch(err => {
        const detail = err?.response?.data?.detail || err.message || '请求失败'
        ElMessage.error('请求失败: ' + detail)
    }).finally(() => {
        loadingInstance && loadingInstance.close()
    })
}

const reset = () => {
    text.value = ''
    indexName.value = 'base'
    top_k.value = 5
    return_audio.value = false
    return_clip.value = true
    matched.value = []
    count.value = null
}
</script>

<style scoped>
.search-content {
  max-width: 1100px;
}

.search-controls {
  padding: var(--space-md) var(--space-lg);
  margin-bottom: var(--space-md);
}

.search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.search-label {
  font-size: 14px;
  color: var(--slate);
  white-space: nowrap;
}

.results-count {
  font-size: 14px;
  color: var(--slate);
  margin: 0 0 var(--space-md) 0;
}

.result-card {
  border-radius: var(--radius-md);
}

.result-audio {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.no-audio {
  color: var(--slate-light);
  font-size: 14px;
}

.result-info {
  margin-top: 8px;
  word-break: break-all;
  font-size: 13px;
  color: var(--slate);
  line-height: 1.6;
}
</style>

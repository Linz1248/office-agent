<template>
    <div class="page-container">
        <h1 class="page-title">文搜图</h1>
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
                        <el-input-number v-model="top_k" :step="1" :min="0.0"></el-input-number>
                    </el-form-item>
                    <el-form-item>
                        <el-checkbox v-model="returnOriginal">返回原图</el-checkbox>
                        <el-checkbox v-model="returnThumbnail">返回缩略图</el-checkbox>
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
                <p class="results-count">共找到 {{ count }} 张匹配图片</p>
                <el-row :gutter="16">
                    <el-col v-for="(it, idx) in matched" :key="idx" :span="6" style="margin-bottom:16px">
                        <el-card class="result-card">
                            <div class="result-image">
                                <img v-if="it.thumbnail_base64" :src="toDataUrl(it.thumbnail_base64)" />
                                <img v-else-if="it.original_base64" :src="toDataUrl(it.original_base64)" />
                                <div v-else class="no-image">无图</div>
                            </div>
                            <div class="result-info">
                                <div><strong>路径:</strong> {{ it.path }}</div>
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
import request from "@/utils/request";
import { ElMessage } from 'element-plus'


const indexLibary = ref([])
const init = () => {
  request.get('/', { serverName: 'docExtract' })
    .then(res => {
      if (res.status != 200)
        return
    })
    request.get('/get_images_dir/?include_files=true', {serverName: 'multimodel'}).then(res => {
        if (res.status === 200){
            const indices = res.data.indices
            for (let i = 0; i < indices.length; i++) {
                const indice_name = indices[i].name
                const indice_split = indice_name.split('.')[0]
                indexLibary.value.push({label: indice_split, value: indice_split})
            }
        } else {
            ElMessage.error('初始化失败')
        }
    })
}
init()

const text = ref('')
const matched = ref([])
const count = ref(null)
const message = ref('')
const indexName = ref('global')
const top_k = ref(5)
const returnOriginal = ref(false)
const returnThumbnail = ref(true)


const toDataUrl = (base64Str) => {
    return 'data:image/jpeg;base64,' + base64Str
}

const submitSearch = () => {
    if (!text.value.length) {
        ElMessage.error('请先输入文本')
        return
    }

    try {
        request.post(
            '/text_search_images/',
            {
                text: text.value
            },
            {
                params: {
                index_name: indexName.value,
                value: top_k.value,
                return_original: returnOriginal.value,
                return_thumbnail: returnThumbnail.value
                },
                serverName: 'multimodel',
                timeout: 60000
            }
        ).then(res => {
            if (res.status === 200){
                matched.value = res.data.results
                count.value = res.data.count
                message.value = res.data.message
                ElMessage.success('检索成功')
            } else {
                ElMessage.error('检索失败')
            }
        })
    } catch (err) {
        console.error(err)
        const detail = err?.response?.data?.detail || err.message || '请求失败'
        ElMessage.error('请求失败: ' + detail)
    }
}

const reset = () => {
    indexName.value = "global"
    top_k.value = 5
    returnOriginal.value = false
    returnThumbnail.value = true
    matched.value = []
    count.value = null
    if (text.value)
        text.value = ''
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

.result-image {
  height: 140px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.result-image img {
  max-width: 100%;
  max-height: 130px;
  border-radius: var(--radius-sm);
}

.no-image {
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

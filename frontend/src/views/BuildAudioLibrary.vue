<template>
    <div class="page-container">
        <h1 class="page-title">构建音频索引库</h1>
        <div class="library-content">
            <el-row :gutter="24">
                <el-col :span="5">
                    <div class="index-list-card">
                        <div class="section-title">现有索引库</div>
                        <div class="index-list">
                            <div v-for="item in indexLibary" :key="item" class="index-item">
                                <span class="index-dot"></span>
                                {{ item }}
                            </div>
                            <div v-if="indexLibary.length === 0" class="index-empty">暂无索引库</div>
                        </div>
                    </div>
                </el-col>

                <el-col :span="19">
                    <div class="build-card">
                        <div class="section-title">上传音频并构建索引库</div>
                        <el-form :model="form" label-width="100px" class="build-form">
                            <el-form-item label="文件夹名称" required>
                                <el-input v-model="form.folderName" placeholder="只能字母、数字、下划线" />
                            </el-form-item>

                            <el-form-item label="选择音频">
                                <el-upload
                                    ref="uploadRef"
                                    drag
                                    multiple
                                    accept="audio/wav,audio/mp3"
                                    :auto-upload="false"
                                    :file-list="fileList"
                                    :on-change="handleChange"
                                    :on-remove="handleRemove"
                                >
                                    <i class="el-icon-upload" />
                                    <div class="el-upload__text">
                                        将文件拖到此处，或 <em>点击选择</em>
                                    </div>
                                </el-upload>
                            </el-form-item>

                            <el-form-item>
                                <el-button type="primary" :loading="uploading" @click="submit">
                                    上传并构建
                                </el-button>
                            </el-form-item>
                        </el-form>
                    </div>
                </el-col>
            </el-row>
        </div>
    </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage, ElLoading } from 'element-plus'
import request from "@/utils/request";


const indexLibary = ref([])
const init = () => {
  request.get('/', { serverName: 'docExtract' })
    .then(res => {
      if (res.status != 200)
        return
    })
  indexLibary.value = []
    request.get('/get_audios_dir/?include_files=true', {serverName: 'multimodel'}).then(res => {
        if (res.status === 200){
            const indices = res.data.indices
            for (let i = 0; i < indices.length; i++) {
                const indice_name = indices[i].name
                const indice_split = indice_name.split('.')[0]
                indexLibary.value.push(indice_split)
            }
        } else {
            ElMessage.error('初始化失败')
        }
    })
}
init()


const form = reactive({
  folderName: ''
})

const fileList = ref([])
const uploadRef = ref(null)
const uploading = ref(false)
let loadingInstance = null

const handleChange = (uploadFile, uploadFiles) => {
  fileList.value = uploadFiles
}
const handleRemove = (uploadFile, uploadFiles) => {
  fileList.value = uploadFiles
}

const submit = async () => {
  if (!form.folderName.trim()) {
    ElMessage.error('请输入文件夹名称')
    return
  }
  if (fileList.value.length === 0) {
    ElMessage.error('请至少选择一个音频')
    return
  }

  const formData = new FormData()
  formData.append('folder_name', form.folderName.trim())

  fileList.value.forEach(({ raw }) => {
    if (raw) formData.append('files', raw)
  })

  uploading.value = true

  const loadingInstance = ElLoading.service({
    lock: true,
    text: '构建中，请稍候…',
    background: 'rgba(0, 0, 0, 0.5)'
  })

  try {
    const uploadRes = await request.post('/upload_audios/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      serverName: 'multimodel'
    })

    if (uploadRes.status === 200) {
      const params = new URLSearchParams()
      params.append('folder_names', [form.folderName.trim()])
      params.append('index_name', form.folderName.trim())

      const buildRes = await request.post(`/build_audios_index/?${params.toString()}`, null, {
        serverName: 'multimodel'
      })

      if (buildRes.status === 200) {
        init()
        form.folderName = ''
        uploadRef.value.clearFiles()
        ElMessage.success('构建成功')
      }
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message || '上传或构建失败')
  } finally {
    uploading.value = false
    loadingInstance.close()
  }
}
</script>

<style scoped>
.library-content {
  max-width: 1100px;
}

.index-list-card {
  background: var(--surface);
  border-radius: var(--radius-lg);
  border: 1px solid var(--mist);
  padding: var(--space-md);
  box-shadow: var(--shadow-xs);
}

.index-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: var(--space-sm);
}

.index-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--mist-light);
  border-radius: var(--radius-sm);
  font-size: 14px;
  color: var(--slate);
}

.index-dot {
  flex-shrink: 0;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
}

.index-empty {
  font-size: 13px;
  color: var(--slate-light);
  padding: 8px 12px;
}

.build-card {
  background: var(--surface);
  border-radius: var(--radius-lg);
  border: 1px solid var(--mist);
  padding: var(--space-lg);
  box-shadow: var(--shadow-xs);
}

.build-form {
  margin-top: var(--space-md);
}
</style>

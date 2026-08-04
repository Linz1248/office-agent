<template>
  <div class="page">
    <div class="workspace">
      <!-- 左侧：上传 + 表单 + 结果 -->
      <section class="panel left-panel">
        <el-upload
            ref="upload"
            class="upload-demo"
            accept="pdf"
            :action="url"
            :headers="state.headers"
            :on-remove="handleRemove"
            :limit="1"
            :on-exceed="handleExceed"
            :on-success="handleSuccess"
            :before-upload="beforeUpload"
            :on-preview="handlePreview"
        >
          <el-button type="primary">上传文件</el-button>
          <template #tip>
            <div class="el-upload__tip">
              只接受 PDF 文件
            </div>
          </template>
        </el-upload>
        <div class="form-scroll-area">
          <el-form :model="form" :rules="rules" ref="formRef" label-width="0" @keyup.enter="submit">
          <!-- 固定字段 -->
            <el-form-item prop="field0">
              <div class="scroll-row">
                <el-input
                  v-model="form.field0"
                  :style="{ width: state.enhance ? '27%' : '100%' }"
                  placeholder="请输入抽取字段"
                />
                <el-input
                  v-if="state.enhance"
                  v-model="form.field0_enhance"
                  style="width: calc(70% - 8px)"
                  placeholder="请输入字段示例，多个示例用;分隔"
                />
                <el-switch
                  size="large"
                  v-model="state.enhance"
                  inline-prompt
                  active-text="开启增强"
                  inactive-text="关闭增强"
                  @change="checkAnyEnhance"
                />
              </div>
            </el-form-item>
          <!-- 动态字段 -->
            <el-form-item
                v-for="(item, index) in dynamicFields"
                :key="item.key"
                :prop="'dynamic.' + item.key"
            >
              <div class="scroll-row">
                <el-input
                    v-model="form.dynamic[item.key]"
                    :style="{ width: item.enhance ? '30%' : '100%' }"
                    placeholder="请输入抽取字段"
                />
                <el-input
                    v-if="item.enhance"
                    v-model="form.dynamicEnhance[item.key]"
                    style="width: calc(70% - 8px)"
                    placeholder="请输入字段示例，多个示例用;分隔"
                />
                <el-switch
                    size="large"
                    v-model="item.enhance"
                    inline-prompt
                    active-text="开启增强"
                    inactive-text="关闭增强"
                    @change="checkAnyEnhance"
                />
                <el-button type="danger" @click="removeInput(index)">删除</el-button>
              </div>
            </el-form-item>

            <el-form-item>
              <div class="btn-row">
                <el-button type="primary" plain @click="addInput">添加字段</el-button>
                <el-button type="primary" @click="submit">发起抽取</el-button>
              </div>
            </el-form-item>
          </el-form>
        </div>

        <div class="fixed-bottom-area">
          <div class="left-tips">
            <div class="tips-title">温馨提示</div>
            <div>(1) 启用文档增强抽取需要进行额外的处理，可能导致较长的时间开销，建议在抽取结果不理想的情况下才开启增强抽取。</div>
            <div style="margin-bottom: 4px;">(2) 启用文档增强抽取时，每个字段建议输入2个以上的示例。</div>
          </div>

        <div class="result-scroll-area">
          <div class="section-title">抽取结果</div>
          <div v-if="Object.keys(extract_res).length" class="result-list">
            <div
              v-for="(value, key) in extract_res"
              :key="key"
              class="result-item"
            >
              <span class="result-key">{{ key }}</span>
              <span class="result-value">{{ value }}</span>
            </div>
          </div>
          <div v-else class="result-empty">暂无结果</div>
        </div>
        </div>
      </section>

      <!-- 右侧：文件预览 -->
      <section class="panel right-panel">
        <div class="preview-header">
          <span class="preview-title">文件预览</span>
          <span v-if="uploadedFileName" class="preview-filename">
            <svg viewBox="0 0 16 16" fill="none" class="file-icon-sm">
              <path d="M4 1.5h5L13 5.5v9a1 1 0 01-1 1H4a1 1 0 01-1-1v-12a1 1 0 011-1z" stroke="currentColor" stroke-width="1.2"/>
              <path d="M9 1.5V5.5h4" stroke="currentColor" stroke-width="1.2"/>
            </svg>
            {{ uploadedFileName }}
          </span>
        </div>
        <div class="preview-body">
          <PDFPreview v-if="localPdfUrl" :src="localPdfUrl" />
          <div v-else class="preview-empty">
            <svg viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg" class="empty-icon">
              <rect x="20" y="12" width="40" height="56" rx="5" stroke="#CBD5E1" stroke-width="2.5"/>
              <path d="M30 12V22H20" stroke="#CBD5E1" stroke-width="2.5" stroke-linejoin="round"/>
              <line x1="28" y1="34" x2="52" y2="34" stroke="#CBD5E1" stroke-width="2.5" stroke-linecap="round"/>
              <line x1="28" y1="44" x2="52" y2="44" stroke="#CBD5E1" stroke-width="2.5" stroke-linecap="round"/>
              <line x1="28" y1="54" x2="44" y2="54" stroke="#CBD5E1" stroke-width="2.5" stroke-linecap="round"/>
            </svg>
            <p class="empty-text">上传 PDF 文件后在此预览</p>
            <p class="empty-hint">支持拖拽或点击左侧按钮上传</p>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import config from "../../config";
import {useUserStore} from "@/stores/user";
import request from "@/utils/request";
import { ElLoading } from 'element-plus'
import PDFPreview from '@/components/PDFPreview.vue'

const load_init = () => {
  request.get('/', { serverName: 'docExtract' })
    .then(res => {
    })
}
load_init()

const localPdfUrl = ref(null)
const uploadedFileName = ref('')
let loadingInstance = null
const store = useUserStore();
const url = ref(config.docExtract + "/doc_upload")
const form = reactive({
  field0: '',
  field0_enhance: '',
  dynamic: {},
  dynamicEnhance: {}
})
const dynamicFields = ref([])
const upload = ref(null)
let fieldIndex = 1
let state = reactive({
  saved_name: "",
  enhance: false,
  hasEnhance: false,
  headers: {
    Authorization: store.getBearerToken
  }
})
const extract_res = ref({})
const formRef = ref(null)
const rules = reactive({
  field0: [{ required: true, message: '请输入抽取字段', trigger: 'blur' }],
  dynamic: {}
})


const checkAnyEnhance = () => {
  const fixedOpen   = state.enhance
  const dynamicOpen = dynamicFields.value.some(f => f.enhance)
  state.hasEnhance  = fixedOpen || dynamicOpen
}

const addInput = () => {
  const key = `dynamic_${fieldIndex++}`
  dynamicFields.value.push({ key, enhance: false })
  form.dynamic[key] = ''
  form.dynamicEnhance[key] = ''
  rules.dynamic[key] = [{ required: true, message: '请输入抽取字段', trigger: 'blur' }]
}


const removeInput = (index) => {
  const { key } = dynamicFields.value[index]
  dynamicFields.value.splice(index, 1)
  delete form.dynamic[key]
  delete form.dynamicEnhance[key]
  delete rules.dynamic[key]
}

const submit = () => {
  formRef.value.validate((valid) => {
    if (!valid) return

    loadingInstance = ElLoading.service({
      lock: true,
      text: '正在抽取中，请稍候...',
      background: 'rgba(0, 0, 0, 0.5)'
    })

    const fields_enhance = []
    const enhanceMap    = {}

    if (state.enhance && form.field0.trim()) {
      fields_enhance.push(form.field0.trim())
      enhanceMap[form.field0.trim()] = form.field0_enhance.trim()
    }

    dynamicFields.value.forEach(({ key, enhance }) => {
      const fieldName = form.dynamic[key].trim()
      if (!fieldName) return
      if (enhance) {
        fields_enhance.push(fieldName)
        enhanceMap[fieldName] = form.dynamicEnhance[key].trim()
      }
    })

    const allFields = [form.field0.trim(), ...Object.values(form.dynamic).map(v => v.trim())]
    request.post('/doc_extract', {
      filename: state.saved_name,
      fields: allFields,
      enhance: state.hasEnhance,
      fields_enhance: fields_enhance,
      fields_template: enhanceMap
    }, {serverName: 'docExtract'}).then(res => {
      if (res.status === 200) {
        extract_res.value = res.data.results
        ElMessage.success('抽取成功')
      } else {
        ElMessage.error('抽取失败')
      }
    }).catch(err => {
      console.error(err)
      ElMessage.error(err.response.data.detail)
    }).finally(() => {
      if (loadingInstance) {
        loadingInstance.close()
        loadingInstance = null
      }
    })
  })
}

const handleSuccess = (res, file) => {
  if (res.status_code === 200) {
    ElMessage.success('上传成功！')
    state.saved_name = res.saved_name
    uploadedFileName.value = file.name
    localPdfUrl.value = URL.createObjectURL(file.raw)
  } else {
    ElMessage.error('上传失败！')
  }
}

const handleExceed = (files) => {
  if (state.saved_name) {
    request.delete('/doc_delete/' + state.saved_name, {serverName: 'docExtract'}).then(res => {
      if (res.status !== 200) {
        ElMessage.error("旧文件删除失败！")
        return
      }
      upload.value.clearFiles()
      upload.value.handleStart(files[0])
      upload.value.submit()
    }).catch(() => {
      ElMessage.error("旧文件删除异常！")
    })
  } else {
    upload.value.handleStart(files[0])
    upload.value.submit()
  }
}

const handleRemove = () => {
  request.delete('/doc_delete/' + state.saved_name, {serverName: 'docExtract'}).then(res => {
    if (res.status !== 200) {
      ElMessage.error("删除失败！")
    } else {
      state.saved_name = ""
      uploadedFileName.value = ""
      if (localPdfUrl.value) {
        localPdfUrl.value = null
      }
    }
  })
}

const handlePreview = (file) => {
  const fileURL = URL.createObjectURL(file.raw)
  window.open(fileURL, '_blank')
}

const beforeUpload = (file) => {
  const isPDF = file.type === 'application/pdf'
  if (!isPDF) {
    ElMessage.error('只能上传 PDF 文件！')
  }
  return isPDF
}
</script>

<style scoped>
.page {
  height: 100vh;
  overflow: hidden;
  padding: var(--space-lg);
  box-sizing: border-box;
}

/* --- 两栏工作区 --- */
.workspace {
  height: 100%;
  display: flex;
  gap: var(--space-md);
}

/* --- 面板基础 --- */
.panel {
  flex: 1;
  min-width: 0;
  height: 100%;
  box-sizing: border-box;
  padding: var(--space-lg);
  background: var(--surface);
  border-radius: var(--radius-lg);
  border: 1px solid var(--mist);
  box-shadow: var(--shadow-xs);
}

.left-panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.right-panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

@media (max-width: 768px) {
  .workspace {
    flex-direction: column;
  }

  .left-panel {
    height: auto;
    max-height: none;
  }

  .right-panel {
    display: none;
  }
}

/* --- 表单区域 --- */
.form-scroll-area {
  flex-shrink: 0;
  max-height: 30vh;
  overflow-y: auto;
  margin-top: var(--space-md);
}

.scroll-row {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
  overflow-x: auto;
  width: 100%;
  padding-bottom: 2px;
}

.scroll-row .el-switch {
  flex-shrink: 0;
}

.btn-row {
  width: 100%;
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.btn-row .el-button {
  flex: 1;
  max-width: 48%;
}

/* --- 底部固定区 --- */
.fixed-bottom-area {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
  min-height: 200px;
  margin-top: var(--space-sm);
}

.left-tips {
  color: var(--slate);
  font-size: 13px;
  background: var(--warning-soft);
  border: 1px solid #FAEBC8;
  border-radius: var(--radius-sm);
  padding: 10px 14px;
  line-height: 1.7;
}

.tips-title {
  font-weight: 600;
  color: var(--warning);
  margin-bottom: 4px;
}

.result-scroll-area {
  flex-grow: 1;
  min-height: 120px;
  overflow-y: auto;
  border-top: 1px solid var(--mist);
  padding-top: var(--space-md);
  margin-top: var(--space-sm);
}

.result-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.result-item {
  display: flex;
  gap: 8px;
  padding: 8px 12px;
  background: var(--mist-light);
  border-radius: var(--radius-sm);
  font-size: 14px;
}

.result-key {
  font-weight: 600;
  color: var(--ink);
  flex-shrink: 0;
}

.result-value {
  color: var(--slate);
  word-break: break-all;
}

.result-empty {
  color: var(--slate-light);
  font-size: 14px;
}

/* --- 预览区 --- */
.preview-header {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  margin-bottom: var(--space-md);
  flex-shrink: 0;
}

.preview-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--ink);
}

.preview-filename {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: var(--slate);
  background: var(--mist-light);
  padding: 3px 10px;
  border-radius: 20px;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-icon-sm {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  color: var(--accent);
}

.preview-body {
  flex: 1;
  min-height: 0;
  position: relative;
  border: 1px solid var(--mist);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--mist-light);
}

.preview-empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--slate-light);
}

.empty-icon {
  width: 80px;
  height: 80px;
  margin-bottom: 16px;
}

.empty-text {
  font-size: 15px;
  color: var(--slate);
  margin: 0 0 4px 0;
}

.empty-hint {
  font-size: 13px;
  margin: 0;
}
</style>

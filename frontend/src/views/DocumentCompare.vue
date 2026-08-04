<template>
    <div class="page-container">
        <h1 class="page-title">文档比对</h1>
        <div class="compare-content">
            <!-- 上传区 -->
            <div class="upload-row">
                <!-- 基准文档 -->
                <div class="upload-zone" :class="{ 'is-uploaded': !!state.benchmark_file }">
                    <div class="zone-header">
                        <span class="zone-tag tag-benchmark">A</span>
                        <span class="zone-title">基准文档</span>
                    </div>
                    <el-upload
                        class="custom-upload"
                        drag
                        accept="pdf"
                        :action="url"
                        :limit="1"
                        :show-file-list="false"
                        :on-success="handleSuccessBenchmark"
                        :before-upload="(file) => beforeUpload(file, 'benchmark')"
                    >
                        <!-- 已上传态 -->
                        <div v-if="state.benchmark_file" class="file-done">
                            <div class="file-icon">
                                <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <rect x="10" y="6" width="28" height="36" rx="3" fill="#EFF6FF" stroke="#2563EB" stroke-width="2"/>
                                    <path d="M20 6V14H12" stroke="#2563EB" stroke-width="2" stroke-linejoin="round"/>
                                    <line x1="16" y1="22" x2="32" y2="22" stroke="#2563EB" stroke-width="1.5" stroke-linecap="round"/>
                                    <line x1="16" y1="28" x2="32" y2="28" stroke="#2563EB" stroke-width="1.5" stroke-linecap="round"/>
                                    <line x1="16" y1="34" x2="26" y2="34" stroke="#2563EB" stroke-width="1.5" stroke-linecap="round"/>
                                </svg>
                            </div>
                            <div class="file-info">
                                <span class="file-name">{{ state.benchmark_file }}</span>
                                <span class="file-status">
                                    <svg viewBox="0 0 20 20" fill="currentColor"><path d="M16.7 5.3a1 1 0 0 1 0 1.4l-7.5 7.5a1 1 0 0 1-1.4 0L3.3 10.7a1 1 0 1 1 1.4-1.4l3.3 3.3 6.8-6.8a1 1 0 0 1 1.4 0Z"/></svg>
                                    已上传
                                </span>
                            </div>
                            <span class="file-replace-hint">点击替换</span>
                        </div>

                        <!-- 空态 -->
                        <div v-else class="file-empty">
                            <div class="empty-icon">
                                <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <rect x="10" y="6" width="28" height="36" rx="3" fill="#F1F5F9" stroke="#94A3B8" stroke-width="2" stroke-dasharray="3 3"/>
                                    <path d="M24 18v10M19 23l5-5 5 5" stroke="#64748B" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                            </div>
                            <p class="empty-title">拖放 PDF 或点击上传</p>
                            <p class="empty-hint">仅支持 PDF 格式</p>
                        </div>
                    </el-upload>
                </div>

                <!-- VS 连接器 -->
                <div class="vs-connector">
                    <div class="vs-line"></div>
                    <div class="vs-badge">VS</div>
                    <div class="vs-line"></div>
                </div>

                <!-- 比对文档 -->
                <div class="upload-zone" :class="{ 'is-uploaded': !!state.compare_file }">
                    <div class="zone-header">
                        <span class="zone-tag tag-compare">B</span>
                        <span class="zone-title">比对文档</span>
                    </div>
                    <el-upload
                        class="custom-upload"
                        drag
                        accept="pdf"
                        :action="url"
                        :limit="1"
                        :show-file-list="false"
                        :on-success="handleSuccessCompare"
                        :before-upload="(file) => beforeUpload(file, 'compare')"
                    >
                        <!-- 已上传态 -->
                        <div v-if="state.compare_file" class="file-done">
                            <div class="file-icon">
                                <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <rect x="10" y="6" width="28" height="36" rx="3" fill="#FEF2F2" stroke="#EF4444" stroke-width="2"/>
                                    <path d="M20 6V14H12" stroke="#EF4444" stroke-width="2" stroke-linejoin="round"/>
                                    <line x1="16" y1="22" x2="32" y2="22" stroke="#EF4444" stroke-width="1.5" stroke-linecap="round"/>
                                    <line x1="16" y1="28" x2="32" y2="28" stroke="#EF4444" stroke-width="1.5" stroke-linecap="round"/>
                                    <line x1="16" y1="34" x2="26" y2="34" stroke="#EF4444" stroke-width="1.5" stroke-linecap="round"/>
                                </svg>
                            </div>
                            <div class="file-info">
                                <span class="file-name">{{ state.compare_file }}</span>
                                <span class="file-status file-status--danger">
                                    <svg viewBox="0 0 20 20" fill="currentColor"><path d="M16.7 5.3a1 1 0 0 1 0 1.4l-7.5 7.5a1 1 0 0 1-1.4 0L3.3 10.7a1 1 0 1 1 1.4-1.4l3.3 3.3 6.8-6.8a1 1 0 0 1 1.4 0Z"/></svg>
                                    已上传
                                </span>
                            </div>
                            <span class="file-replace-hint">点击替换</span>
                        </div>

                        <!-- 空态 -->
                        <div v-else class="file-empty">
                            <div class="empty-icon">
                                <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <rect x="10" y="6" width="28" height="36" rx="3" fill="#F1F5F9" stroke="#94A3B8" stroke-width="2" stroke-dasharray="3 3"/>
                                    <path d="M24 18v10M19 23l5-5 5 5" stroke="#64748B" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                            </div>
                            <p class="empty-title">拖放 PDF 或点击上传</p>
                            <p class="empty-hint">仅支持 PDF 格式</p>
                        </div>
                    </el-upload>
                </div>
            </div>

            <!-- 选项区 -->
            <div class="compare-options">
                <div class="options-row">
                    <el-checkbox v-model="ignore_seal">忽略印章</el-checkbox>
                    <div class="option-item">
                        <span class="option-label">页眉高度</span>
                        <el-select v-model="header_h" placeholder="0" style="width: 90px;">
                            <el-option
                            v-for="item in options"
                            :key="item.value"
                            :label="item.label"
                            :value="item.value"
                            />
                        </el-select>
                    </div>
                    <div class="option-item">
                        <span class="option-label">页脚高度</span>
                        <el-select v-model="footer_h" placeholder="0" style="width: 90px;">
                            <el-option
                                v-for="item in options"
                                :key="item.value"
                                :label="item.label"
                                :value="item.value"
                            />
                        </el-select>
                    </div>
                </div>
            </div>

            <!-- 操作区 -->
            <div class="compare-action">
                <el-button
                    type="primary"
                    size="large"
                    :disabled="!state.benchmark_file || !state.compare_file"
                    @click="do_comapre"
                >
                    开始比对
                </el-button>
                <span v-if="!state.benchmark_file || !state.compare_file" class="action-hint">
                    请上传两份文档后再比对
                </span>
            </div>
        </div>
    </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import config from "../../config";
import { ElMessage, ElLoading } from 'element-plus'
import request from "@/utils/request";
import router from "../router"

const ignore_seal = ref(true)
const header_h = ref('0')
const footer_h = ref('0')
const url = ref(config.docCompare + "/upload")
let loadingInstance = null

const options = [];
for (let i = 0; i < 101; i++) {
  options.push({
    value: String(i),
    label: String(i),
  });
}
let state = reactive({
  benchmark_file: "",
  compare_file: ""
})

const init = () => {
    request.get('/', { serverName: 'docExtract' })
    .then(res => {
    })
}
init()

const beforeUpload = (file) => {
    const isPDF = file.type === 'application/pdf'
    if (!isPDF) {
        ElMessage.error('只能上传 PDF 文件！')
    }
    return isPDF
}

const handleSuccessBenchmark = (res) => {
    if (res.status_code === 200) {
        ElMessage.success('基准文档上传成功')
        state.benchmark_file = res.saved_name
    } else {
        ElMessage.error('上传失败！')
    }
}

const handleSuccessCompare = (res) => {
    if (res.status_code === 200) {
        ElMessage.success('比对文档上传成功')
        state.compare_file = res.saved_name
    } else {
        ElMessage.error('上传失败！')
    }
}

const do_comapre = () => {
    loadingInstance = ElLoading.service({
        lock: true,
        text: '文件比对中，请稍候…',
        background: 'rgba(0, 0, 0, 0.5)'
    })

    request.post('/compare', {
        benchmark_file: state.benchmark_file,
        compare_file: state.compare_file,
        use_seal: ignore_seal.value == false ? true : false,
        header_h: header_h.value,
        footer_h: footer_h.value
    }, {serverName: 'docCompare'}).then(res => {
        if (res.status == 200){
            router.push({
                path: '/document_compare_result',
                query: {
                    benchmark_file: res.data.benchmark_file,
                    compare_file: res.data.compare_file,
                    similarity: res.data.similarity
                }
            })
        } else {
            ElMessage.error('比对失败')
        }
    }).catch(() => {
      ElMessage.error('比对失败')
    })
    .finally(() => {
      loadingInstance && loadingInstance.close()
    })
}
</script>

<style scoped>
.compare-content {
  max-width: 900px;
}

/* --- 上传行 --- */
.upload-row {
  display: flex;
  align-items: stretch;
  gap: 0;
}

.upload-zone {
  flex: 1;
  background: var(--surface);
  border: 2px solid var(--mist);
  border-radius: var(--radius-lg);
  padding: var(--space-lg);
  transition: border-color var(--transition), box-shadow var(--transition);
  display: flex;
  flex-direction: column;
}

.upload-zone:hover {
  border-color: var(--slate-light);
}

.upload-zone.is-uploaded {
  border-color: var(--accent);
}

/* 区域头 */
.zone-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: var(--space-md);
}

.zone-tag {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-weight: 700;
  color: #fff;
}

.tag-benchmark {
  background: var(--accent);
}

.tag-compare {
  background: #EF4444;
}

.zone-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--ink);
}

/* 自定义 upload 样式 */
.custom-upload :deep(.el-upload) {
  width: 100%;
}

.custom-upload :deep(.el-upload-dragger) {
  width: 100%;
  height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px dashed var(--mist);
  border-radius: var(--radius-md);
  background: var(--paper);
  padding: var(--space-md);
  transition: all var(--transition);
}

.custom-upload :deep(.el-upload-dragger:hover) {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.is-uploaded .custom-upload :deep(.el-upload-dragger) {
  border-style: solid;
  border-color: var(--mist);
  background: var(--surface);
}

.is-uploaded .custom-upload :deep(.el-upload-dragger:hover) {
  border-color: var(--accent);
}

/* 空态 */
.file-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.empty-icon {
  width: 48px;
  height: 48px;
  opacity: 0.7;
}

.empty-icon svg {
  width: 100%;
  height: 100%;
}

.empty-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--slate);
  margin: 4px 0 0;
}

.empty-hint {
  font-size: 12px;
  color: var(--slate-light);
  margin: 0;
}

/* 已上传态 */
.file-done {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.file-icon {
  width: 48px;
  height: 48px;
}

.file-icon svg {
  width: 100%;
  height: 100%;
}

.file-info {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.file-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--ink);
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-status {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--success);
}

.file-status svg {
  width: 14px;
  height: 14px;
}

.file-status--danger {
  color: #EF4444;
}

.file-replace-hint {
  font-size: 12px;
  color: var(--slate-light);
}

/* VS 连接器 */
.vs-connector {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 48px;
  flex-shrink: 0;
}

.vs-line {
  width: 2px;
  flex: 1;
  background: var(--mist);
}

.vs-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--surface);
  border: 2px solid var(--mist);
  font-size: 12px;
  font-weight: 700;
  color: var(--slate);
  margin: 8px 0;
  flex-shrink: 0;
}

/* --- 选项区 --- */
.compare-options {
  margin-top: var(--space-lg);
  background: var(--surface);
  border-radius: var(--radius-lg);
  border: 1px solid var(--mist);
  padding: var(--space-md) var(--space-lg);
}

.options-row {
  display: flex;
  align-items: center;
  gap: 32px;
  flex-wrap: wrap;
}

.option-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.option-label {
  font-size: 14px;
  color: var(--slate);
  white-space: nowrap;
}

/* --- 操作区 --- */
.compare-action {
  margin-top: var(--space-lg);
  display: flex;
  align-items: center;
  gap: 16px;
}

.action-hint {
  font-size: 13px;
  color: var(--slate-light);
}

/* --- 响应式 --- */
@media (max-width: 700px) {
  .upload-row {
    flex-direction: column;
  }

  .vs-connector {
    width: 100%;
    height: 48px;
    flex-direction: row;
  }

  .vs-line {
    width: auto;
    height: 2px;
    flex: 1;
  }

  .vs-badge {
    margin: 0 8px;
  }
}
</style>

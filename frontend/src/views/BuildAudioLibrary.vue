<template>
  <div class="page-container">
    <div class="retrieval-page">
      <header class="retrieval-header">
        <h1 class="page-title"><span class="title-accent" />音频库</h1>
      </header>

      <div v-if="error" class="retrieval-state is-error card">
        <div class="state-icon">⚠</div>
        <div class="state-title">加载失败</div>
        <div class="state-hint">{{ error }}</div>
      </div>

      <div v-else-if="loading" class="retrieval-state retrieval-loading card">
        <div class="spinner" />
        <div class="state-title">加载库目录…</div>
      </div>

      <div v-else class="library-layout">
        <aside class="lib-sidebar">
          <div class="card" style="padding: var(--space-md)">
            <div class="lib-section">
              <div class="lib-section-head">
                <div class="lib-section-title">目录</div>
                <button class="lib-add-btn" :disabled="busy" @click="promptCreate">+ 新建</button>
              </div>
              <div v-if="!folders.length" class="text-muted" style="font-size: 12px">暂无文件夹</div>
              <div class="lib-folder-list">
                <div
                  v-for="f in folders"
                  :key="f.name"
                  class="lib-folder-item"
                  :class="{ active: f.name === selectedFolder }"
                  @click="selectFolder(f.name)"
                >
                  <span>{{ f.name }}</span>
                  <span class="fc">{{ f.count }} 段</span>
                </div>
              </div>
            </div>
          </div>

        </aside>

        <section class="lib-main card" style="padding: var(--space-lg)">
          <div class="build-status">
            <template v-if="progress.active">
              <span class="sync-label">正在重建「{{ progress.index_name }}」索引 · 提取文本特征…</span>
              <el-progress class="sync-progress" :indeterminate="true" :stroke-width="8" :show-text="false" />
            </template>
            <span v-else class="sync-ok">✓ 索引已同步</span>
          </div>

          <div class="lib-toolbar">
            <span class="control-label">上传到</span>
            <el-input v-model="uploadFolder" class="folder-input" placeholder="文件夹名" :disabled="busy" />
            <label class="upload-trigger">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              选择音频
              <input ref="fileInput" type="file" multiple accept=".mp3,.wav,.m4a" hidden :disabled="busy" @change="onPick" />
            </label>
            <div v-if="pendingUpload.length" class="file-chips">
              <span v-for="(f, i) in pendingUpload" :key="i" class="file-chip">
                <span class="chip-name" :title="f.name">{{ f.name }}</span>
                <span class="chip-remove" @click="removePending(i)">×</span>
              </span>
            </div>
            <el-button type="primary" :disabled="busy || !pendingUpload.length" @click="doUpload">上传</el-button>
            <el-popconfirm
              :title="`确认删除选中的 ${selectedFiles.size} 个音频？`"
              :disabled="!selectedFiles.size || busy"
              @confirm="deleteSelected"
            >
              <template #reference>
                <el-button type="danger" plain :disabled="!selectedFiles.size || busy">删除选中 ({{ selectedFiles.size }})</el-button>
              </template>
            </el-popconfirm>
          </div>

          <div v-if="busy" class="retrieval-state retrieval-loading" style="padding: var(--space-xl)">
            <div class="spinner" />
            <div class="state-title">{{ busyText }}</div>
            <div class="state-hint">大音频转写较慢，请耐心等待。</div>
          </div>
          <div v-else-if="!selectedFolder" class="retrieval-state" style="padding: var(--space-xl)">
            <div class="state-icon">📁</div>
            <div class="state-title">选择左侧文件夹查看内容</div>
            <div class="state-hint">或「+ 新建」目录，直接上传音频也会自动创建。</div>
          </div>
          <div v-else-if="!currentFiles.length" class="retrieval-state" style="padding: var(--space-xl)">
            <div class="state-icon">🔊</div>
            <div class="state-title">该文件夹为空</div>
            <div class="state-hint">上传音频后会自动转写并重建索引。</div>
          </div>
          <div v-else>
            <div
              v-for="f in currentFiles"
              :key="f.path"
              class="audio-row"
              :class="{ selected: selectedFiles.has(f.path) }"
            >
              <input
                class="row-check"
                type="checkbox"
                :checked="selectedFiles.has(f.path)"
                @change="toggleSelect(f.path)"
              />
              <audio :src="f.url" controls preload="none" />
              <span class="audio-name" :title="f.name">{{ f.name }}</span>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import request from '@/utils/request'
import { ElMessage, ElMessageBox } from 'element-plus'
import config from '/config'

const BASE = config.multimodel

const folders = ref([])
const selectedFolder = ref('')
const selectedFiles = ref(new Set())
const uploadFolder = ref('')
const pendingUpload = ref([])
const fileInput = ref(null)
const loading = ref(true)
const error = ref('')
const busy = ref(false)
const busyText = ref('处理中…')
const progress = ref({ active: false, index_name: '' })

const countFiles = (node) => {
  if (!node) return 0
  if (node.type === 'file') return 1
  return (node.children || []).reduce((s, c) => s + countFiles(c), 0)
}
const flattenFiles = (node, folder) => {
  const out = []
  if (!node) return out
  for (const c of node.children || []) {
    if (c.type === 'file') {
      out.push({ name: c.name, path: `${folder}/${c.name}` })
    } else if (c.type === 'dir') {
      out.push(...flattenFiles(c, `${folder}/${c.name}`))
    }
  }
  return out
}

const currentFiles = computed(() => {
  const f = folders.value.find((x) => x.name === selectedFolder.value)
  if (!f) return []
  return f.files.map((x) => ({ ...x, url: `${BASE}/audios/${x.path}` }))
})

const init = () => {
  loading.value = true
  error.value = ''
  request
    .get('/get_audios_dir/?include_files=true', { serverName: 'multimodel' })
    .then((res) => {
      const tree = res.data.repositories || []
      folders.value = tree.map((node) => ({
        name: node.name,
        count: countFiles(node),
        files: flattenFiles(node, node.name),
      }))
      if (!selectedFolder.value && folders.value.length) {
        selectFolder(folders.value[0].name)
      }
    })
    .catch((err) => {
      error.value = err?.response?.data?.detail || err.message || '请求失败'
    })
    .finally(() => {
      loading.value = false
    })
}
init()

let pollTimer = null
let wasActive = false
const pollProgress = () => {
  request
    .get('/build_progress/?kind=audio', { serverName: 'multimodel' })
    .then((res) => {
      progress.value = res.data || {}
      const active = !!(res.data && res.data.active)
      if (!active && wasActive) init()
      wasActive = active
    })
    .catch(() => {})
}
const startPolling = () => {
  pollTimer = setInterval(pollProgress, 1000)
}
const stopPolling = () => {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}
onMounted(startPolling)
onUnmounted(stopPolling)

const selectFolder = (name) => {
  selectedFolder.value = name
  uploadFolder.value = name
  selectedFiles.value = new Set()
}

const toggleSelect = (path) => {
  const s = new Set(selectedFiles.value)
  if (s.has(path)) s.delete(path)
  else s.add(path)
  selectedFiles.value = s
}

const onPick = (e) => {
  pendingUpload.value = Array.from(e.target.files || [])
}
const removePending = (i) => {
  pendingUpload.value.splice(i, 1)
  if (fileInput.value) fileInput.value.value = ''
}

const promptCreate = () => {
  ElMessageBox.prompt('请输入文件夹名', '新建目录', {
    confirmButtonText: '创建',
    cancelButtonText: '取消',
    inputPattern: /^[^/\\]+$/,
    inputErrorMessage: '名称不能包含 / 或 \\',
  })
    .then(({ value }) => createFolder(value.trim()))
    .catch(() => {})
}

const createFolder = (name) => {
  busy.value = true
  request
    .post(`/create_folder/?kind=audio&folder_name=${encodeURIComponent(name)}`, null, {
      serverName: 'multimodel',
    })
    .then(() => {
      ElMessage.success(`已创建目录 ${name}`)
      selectedFolder.value = name
      init()
    })
    .catch((err) => {
      ElMessage.error(err?.response?.data?.detail || '创建失败')
    })
    .finally(() => {
      busy.value = false
    })
}

const doUpload = () => {
  const folder = (uploadFolder.value || '').trim()
  if (!folder) {
    ElMessage.warning('请输入目标文件夹名')
    return
  }
  if (!pendingUpload.value.length) return
  busy.value = true
  busyText.value = '上传并转写中…'
  const form = new FormData()
  form.append('folder_name', folder)
  pendingUpload.value.forEach((f) => form.append('files', f, f.name))
  request
    .post('/upload_audios/', form, { serverName: 'multimodel', timeout: 1200000 })
    .then(() => {
      ElMessage.success(`已上传 ${pendingUpload.value.length} 个音频并转写`)
      pendingUpload.value = []
      if (fileInput.value) fileInput.value.value = ''
      if (!folders.value.find((x) => x.name === folder)) selectedFolder.value = folder
      init()
    })
    .catch((err) => {
      ElMessage.error(err?.response?.data?.detail || '上传失败')
    })
    .finally(() => {
      busy.value = false
    })
}

const deleteSelected = () => {
  if (!selectedFiles.value.size) return
  busy.value = true
  busyText.value = '删除中…'
  const qs = [...selectedFiles.value].map((p) => `name=${encodeURIComponent(p)}`).join('&')
  request
    .post(`/delete_audios/?target=repo&${qs}`, null, { serverName: 'multimodel', timeout: 120000 })
    .then(() => {
      ElMessage.success('已删除选中音频')
      selectedFiles.value = new Set()
      init()
    })
    .catch((err) => {
      ElMessage.error(err?.response?.data?.detail || '删除失败')
    })
    .finally(() => {
      busy.value = false
    })
}
</script>

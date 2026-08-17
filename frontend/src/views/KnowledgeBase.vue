<template>
  <div class="page-container">
    <div class="retrieval-page">
      <header class="retrieval-header">
        <h1 class="page-title"><span class="title-accent" />个人知识库</h1>
        <p class="kb-subtitle">上传文档构建专属知识库，开启 RAG 检索增强；可将文档公开，供他人检索复用。</p>
      </header>

      <!-- 未就绪提示 -->
      <div v-if="!ready && readyChecked" class="retrieval-state is-error card">
        <div class="state-icon">⚠</div>
        <div class="state-title">知识库功能未就绪</div>
        <div class="state-hint">需本地 Ollama 嵌入模型，请在后端执行 <code>ollama pull {{ embeddingModel }}</code> 后重启服务。</div>
      </div>

      <template v-else>
        <!-- 统计 -->
        <div class="kb-stats">
          <div class="kb-stat card">
            <div class="kb-stat-num">{{ documents.length }}</div>
            <div class="kb-stat-label">文档总数</div>
          </div>
          <div class="kb-stat card">
            <div class="kb-stat-num">{{ sharedCount }}</div>
            <div class="kb-stat-label">已公开文档</div>
          </div>
          <div class="kb-stat card">
            <div class="kb-stat-num">{{ totalChunks }}</div>
            <div class="kb-stat-label">索引片段</div>
          </div>
          <div class="kb-stat card">
            <div class="kb-stat-num">{{ formatChars(totalChars) }}</div>
            <div class="kb-stat-label">总字符数</div>
          </div>
        </div>

        <!-- 标签切换 -->
        <div class="kb-tabs card">
          <button class="kb-tab" :class="{ active: tab === 'docs' }" @click="tab = 'docs'">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            我的文档
          </button>
          <button class="kb-tab" :class="{ active: tab === 'search' }" @click="tab = 'search'">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
            知识检索
          </button>
        </div>

        <!-- 我的文档 -->
        <section v-if="tab === 'docs'" class="kb-panel">
          <!-- 上传区 -->
          <div class="kb-upload card" :class="{ dragging }" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="onDrop">
            <input ref="fileInput" type="file" multiple :accept="acceptTypes" hidden @change="onPick" />
            <div class="kb-upload-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
            </div>
            <div class="kb-upload-text">
              <div class="kb-upload-title">拖拽文件到此处，或<span class="kb-upload-link" @click="fileInput?.click()">点击选择</span></div>
              <div class="kb-upload-hint">支持 PDF / Word / Excel / 图片 / TXT / MD / CSV，可多选。上传后自动抽取全文并建立向量索引。</div>
            </div>
            <el-button v-if="pendingUpload.length" type="primary" :loading="uploading" @click.stop="doUpload">上传 {{ pendingUpload.length }} 个文件</el-button>
          </div>
          <div v-if="pendingUpload.length" class="kb-pending">
            <span v-for="(f, i) in pendingUpload" :key="i" class="file-chip">
              <span class="chip-name" :title="f.name">{{ f.name }}</span>
              <span class="chip-remove" @click="removePending(i)">×</span>
            </span>
          </div>

          <!-- 文档列表 -->
          <div v-if="loading && !documents.length" class="retrieval-state retrieval-loading card">
            <div class="spinner" /><div class="state-title">加载文档列表…</div>
          </div>
          <div v-else-if="!documents.length" class="retrieval-state card">
            <div class="state-icon">📚</div>
            <div class="state-title">知识库还是空的</div>
            <div class="state-hint">上传第一份文档，开始构建你的个人知识库。</div>
          </div>
          <div v-else class="kb-doc-list">
            <div
              v-for="d in documents"
              :key="d.doc_id"
              class="kb-doc card"
              :class="`is-${d.status}`"
            >
              <div class="kb-doc-icon">{{ docIcon(d.file_ext) }}</div>
              <div class="kb-doc-main">
                <div class="kb-doc-name" :title="d.filename">{{ d.filename }}</div>
                <!-- 就绪文档：显示片段与字符数 -->
                <div v-if="d.status === 'ready'" class="kb-doc-meta">
                  <span class="kb-chip">📄 {{ d.chunk_count }} 片段</span>
                  <span class="kb-chip">{{ formatChars(d.chars) }} 字</span>
                  <span class="kb-date">{{ formatDate(d.created_at) }}</span>
                </div>
                <!-- 索引中：显示进度条 -->
                <div v-else-if="d.status === 'pending' || d.status === 'processing'" class="kb-doc-progress">
                  <div class="progress-track">
                    <div class="progress-fill" :class="`is-${d.status}`">
                      <span class="progress-shimmer" />
                    </div>
                  </div>
                  <span class="progress-label">{{ statusText(d.status) }}…</span>
                </div>
                <!-- 失败：显示错误 -->
                <div v-else-if="d.status === 'failed'" class="kb-doc-error">
                  <span class="kb-error-text">❗ {{ d.error || '索引失败' }}</span>
                </div>
              </div>
              <div class="kb-doc-side">
                <!-- 启用检索开关 -->
                <div class="kb-toggle-group">
                  <div class="kb-toggle" :title="d.enabled ? '参与检索' : '已禁用检索'">
                    <span class="kb-toggle-label">{{ d.enabled ? '检索' : '禁用' }}</span>
                    <el-switch
                      :model-value="d.enabled"
                      :loading="togglingEnabled === d.doc_id"
                      :disabled="d.status !== 'ready'"
                      @change="(v) => toggleEnabled(d, v)"
                    />
                  </div>
                  <div class="kb-toggle" :title="d.shared ? '已公开，他人可检索' : '仅自己可见'">
                    <span class="kb-toggle-label">{{ d.shared ? '公开' : '私有' }}</span>
                    <el-switch
                      :model-value="d.shared"
                      :loading="toggling === d.doc_id"
                      :disabled="d.status !== 'ready'"
                      @change="(v) => toggleShare(d, v)"
                    />
                  </div>
                </div>
              </div>
              <div class="kb-doc-actions">
                <el-button text :disabled="d.status !== 'ready'" @click="viewDoc(d)">查看全文</el-button>
                <el-popconfirm
                  title="确认删除该文档？删除后不可恢复。"
                  confirm-button-text="删除"
                  cancel-button-text="取消"
                  width="240"
                  @confirm="removeDoc(d)"
                >
                  <template #reference><el-button text type="danger">删除</el-button></template>
                </el-popconfirm>
              </div>
            </div>
          </div>
        </section>

        <!-- 知识检索 -->
        <section v-else class="kb-panel">
          <div class="kb-searchbar card">
            <el-input v-model="query" placeholder="用自然语言提问，检索本人文档与全平台公开文档…" :disabled="searching" @keydown.enter.prevent="doSearch">
              <template #prefix><svg class="kb-search-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg></template>
            </el-input>
            <div class="control-field">
              <span class="control-label">返回数量</span>
              <el-input-number v-model="topK" :min="1" :max="20" :disabled="searching" />
            </div>
            <el-button type="primary" :loading="searching" @click="doSearch">检索</el-button>
          </div>

          <div v-if="searching" class="retrieval-state retrieval-loading card"><div class="spinner" /><div class="state-title">语义检索中…</div></div>
          <div v-else-if="searchError" class="retrieval-state is-error card"><div class="state-icon">⚠</div><div class="state-title">检索失败</div><div class="state-hint">{{ searchError }}</div></div>
          <div v-else-if="!searched" class="retrieval-state card"><div class="state-icon">🔎</div><div class="state-title">输入问题开始检索</div><div class="state-hint">将返回语义最相关的 {{ topK }} 个文档片段，并标注出处与相似度。</div></div>
          <div v-else-if="!results.length" class="retrieval-state card"><div class="state-icon">🗂</div><div class="state-title">未找到相关内容</div><div class="state-hint">换个问法，或先上传更多文档。</div></div>
          <div v-else class="kb-results">
            <div class="results-bar"><span class="count">命中 {{ results.length }} 个片段</span></div>
            <div v-for="(r, i) in results" :key="i" class="kb-result card">
              <div class="kb-result-head">
                <span class="kb-result-rank">#{{ i + 1 }}</span>
                <span class="kb-result-file" :title="r.filename">📄 {{ r.filename || '未命名' }}</span>
                <span v-if="r.shared" class="kb-tag is-shared">公开</span>
                <span v-else class="kb-tag is-private">私有</span>
                <span v-if="r.owner && r.owner !== currentUserId" class="kb-tag is-owner">来自：{{ r.owner }}</span>
                <span class="kb-result-score">相似度 {{ r.score }}</span>
              </div>
              <div class="kb-result-text">{{ r.content }}</div>
            </div>
          </div>
        </section>
      </template>
    </div>

    <!-- 全文抽屉 -->
    <el-drawer v-model="viewer.visible" :title="viewer.title" size="50%" direction="rtl">
      <div v-if="viewer.loading" class="retrieval-state retrieval-loading"><div class="spinner" /><div class="state-title">读取全文…</div></div>
      <div v-else-if="viewer.error" class="retrieval-state is-error"><div class="state-icon">⚠</div><div class="state-hint">{{ viewer.error }}</div></div>
      <pre v-else class="kb-fulltext">{{ viewer.text }}</pre>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import request from '@/utils/request'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import config from '/config'

const store = useUserStore()
const currentUserId = computed(() => store.getUser?.username || '')

const ready = ref(false)
const readyChecked = ref(false)
const tab = ref('docs')
const embeddingModel = ref('qwen3-embedding:8b')

// ── 文档列表 ──
const documents = ref([])
const loading = ref(false)
const toggling = ref('')
const togglingEnabled = ref('')
let pollTimer = null

const sharedCount = computed(() => documents.value.filter((d) => d.shared).length)
const totalChunks = computed(() => documents.value.reduce((s, d) => s + (d.chunk_count || 0), 0))
const totalChars = computed(() => documents.value.reduce((s, d) => s + (d.chars || 0), 0))

const acceptTypes = '.pdf,.docx,.doc,.xlsx,.xls,.jpg,.jpeg,.png,.bmp,.webp,.txt,.md,.csv'
const ext2icon = { pdf: '📕', docx: '📘', doc: '📘', xlsx: '📗', xls: '📗', jpg: '🖼', jpeg: '🖼', png: '🖼', bmp: '🖼', webp: '🖼', txt: '📄', md: '📄', csv: '📄' }
const docIcon = (ext) => ext2icon[(ext || '').toLowerCase()] || '📄'
const statusText = (s) => ({ pending: '排队中', processing: '索引中', ready: '就绪', failed: '失败' }[s] || s)
const formatDate = (ms) => ms ? new Date(ms).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''
const formatChars = (n) => {
  if (!n) return '0'
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return String(n)
}

const fetchDocs = async () => {
  loading.value = true
  try {
    const res = await request.get('/kb/documents', { serverName: 'agent' })
    if (res.status === 200) documents.value = res.data.documents || []
  } catch (e) {
    // 503 → 未就绪（init 时已探测，这里静默）
  } finally {
    loading.value = false
  }
}

const hasPending = computed(() => documents.value.some((d) => d.status === 'pending' || d.status === 'processing'))
const startPolling = () => {
  stopPolling()
  pollTimer = setInterval(() => { if (hasPending.value) fetchDocs(); else stopPolling() }, 3000)
}
const stopPolling = () => { if (pollTimer) { clearInterval(pollTimer); pollTimer = null } }

// ── 上传 ──
const fileInput = ref(null)
const pendingUpload = ref([])
const uploading = ref(false)
const dragging = ref(false)

const onPick = (e) => { pendingUpload.value.push(...Array.from(e.target.files || [])); e.target.value = '' }
const onDrop = (e) => { dragging.value = false; pendingUpload.value.push(...Array.from(e.dataTransfer?.files || [])) }
const removePending = (i) => pendingUpload.value.splice(i, 1)

const doUpload = async () => {
  if (!pendingUpload.value.length) return
  uploading.value = true
  let ok = 0
  for (const f of pendingUpload.value) {
    const fd = new FormData()
    fd.append('file', f)
    try {
      // 走原生 fetch（不设 Content-Type，由浏览器自动带 multipart boundary），
      // 避开 request 拦截器对非 multimodel 服务强制 JSON Content-Type 导致的 422。
      const resp = await fetch(`${config.agent}/kb/documents`, {
        method: 'POST',
        headers: { Authorization: store.getBearerToken },
        body: fd,
      })
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}))
        throw new Error(errData.detail || `上传失败 (${resp.status})`)
      }
      ok++
    } catch (e) {
      ElMessage.error(`${f.name}：${e.message || '上传失败'}`)
    }
  }
  uploading.value = false
  pendingUpload.value = []
  if (ok) { ElMessage.success(`已提交 ${ok} 个文档，正在后台索引`); fetchDocs().then(startPolling) }
}

// ── 共享切换 ──
const toggleShare = async (d, v) => {
  toggling.value = d.doc_id
  try {
    await request.patch(`/kb/documents/${d.doc_id}`, { shared: v }, { serverName: 'agent' })
    d.shared = v
    ElMessage.success(v ? '已公开，他人可检索此文档' : '已设为私有')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '切换失败')
  } finally {
    toggling.value = ''
  }
}

// ── 启用/禁用检索 ──
const toggleEnabled = async (d, v) => {
  togglingEnabled.value = d.doc_id
  try {
    await request.patch(`/kb/documents/${d.doc_id}/enabled`, { enabled: v }, { serverName: 'agent' })
    d.enabled = v
    ElMessage.success(v ? '已启用检索' : '已禁用检索')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '切换失败')
  } finally {
    togglingEnabled.value = ''
  }
}

// ── 删除 ──
const removeDoc = async (d) => {
  try {
    await request.delete(`/kb/documents/${d.doc_id}`, { serverName: 'agent' })
    documents.value = documents.value.filter((x) => x.doc_id !== d.doc_id)
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

// ── 全文查看 ──
const viewer = ref({ visible: false, title: '', text: '', loading: false, error: '' })
const viewDoc = async (d) => {
  viewer.value = { visible: true, title: d.filename, text: '', loading: true, error: '' }
  try {
    const res = await request.get(`/kb/documents/${d.doc_id}`, { serverName: 'agent' })
    if (res.status === 200) viewer.value.text = res.data.text || '（全文为空）'
  } catch (e) {
    viewer.value.error = e?.response?.data?.detail || '读取失败'
  } finally {
    viewer.value.loading = false
  }
}

// ── 检索 ──
const query = ref('')
const topK = ref(5)
const results = ref([])
const searched = ref(false)
const searching = ref(false)
const searchError = ref('')

const doSearch = async () => {
  if (!query.value.trim()) { ElMessage.warning('请输入检索问题'); return }
  searching.value = true; searchError.value = ''; searched.value = true; results.value = []
  try {
    const res = await request.post('/kb/search', { query: query.value, top_k: topK.value }, { serverName: 'agent', timeout: 120000 })
    if (res.status === 200) results.value = res.data.items || []
  } catch (e) {
    searchError.value = e?.response?.data?.detail || '检索失败'
  } finally {
    searching.value = false
  }
}

// ── 就绪探测 ──
const checkReady = async () => {
  try {
    const res = await request.get('/health', { serverName: 'agent' })
    ready.value = !!res.data?.kb_ready
  } catch { ready.value = false }
  readyChecked.value = true
  if (ready.value) { await fetchDocs(); startPolling() }
}

onMounted(checkReady)
onUnmounted(stopPolling)
</script>

<style scoped>
.kb-subtitle {
  margin: -4px 0 0;
  color: var(--slate);
  font-size: 13px;
}

/* 统计 */
.kb-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-md);
  margin-bottom: var(--space-md);
}
.kb-stat { padding: var(--space-md) var(--space-lg); text-align: center; }
.kb-stat-num { font-size: 26px; font-weight: 700; color: var(--accent); }
.kb-stat-label { font-size: 12px; color: var(--slate); margin-top: 2px; }

/* 标签 */
.kb-tabs { display: flex; gap: 4px; padding: 6px; margin-bottom: var(--space-md); }
.kb-tab {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 8px 16px; border: none; background: transparent;
  border-radius: var(--radius-sm); color: var(--slate);
  font-size: 14px; cursor: pointer; transition: all var(--transition);
}
.kb-tab svg { width: 16px; height: 16px; }
.kb-tab:hover { background: var(--mist-light); color: var(--ink); }
.kb-tab.active { background: var(--accent-soft); color: var(--accent); font-weight: 600; }

/* 上传区 */
.kb-upload {
  display: flex; align-items: center; gap: var(--space-md);
  padding: var(--space-lg); border: 2px dashed var(--mist);
  transition: all var(--transition); cursor: pointer;
}
.kb-upload.dragging { border-color: var(--accent); background: var(--accent-soft); }
.kb-upload-icon { flex-shrink: 0; width: 44px; height: 44px; border-radius: 50%; background: var(--accent-soft); color: var(--accent); display: flex; align-items: center; justify-content: center; }
.kb-upload-icon svg { width: 22px; height: 22px; }
.kb-upload-text { flex: 1; }
.kb-upload-title { font-size: 14px; font-weight: 600; color: var(--ink); }
.kb-upload-link { color: var(--accent); cursor: pointer; }
.kb-upload-link:hover { text-decoration: underline; }
.kb-upload-hint { font-size: 12px; color: var(--slate); margin-top: 4px; }
.kb-pending { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.file-chip { display: inline-flex; align-items: center; gap: 6px; background: var(--mist-light); border-radius: 20px; padding: 4px 10px; font-size: 12px; }
.chip-name { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chip-remove { cursor: pointer; color: var(--slate); }
.chip-remove:hover { color: var(--danger); }

/* 文档列表 */
.kb-doc-list { display: flex; flex-direction: column; gap: 10px; margin-top: var(--space-md); }
.kb-doc {
  display: flex; align-items: center; gap: var(--space-md);
  padding: var(--space-md) var(--space-lg);
  transition: box-shadow var(--transition);
}
.kb-doc.is-pending, .kb-doc.is-processing {
  border-left: 3px solid var(--warning);
  background: linear-gradient(90deg, var(--surface), var(--warning-soft) 40%);
}
.kb-doc.is-failed {
  border-left: 3px solid var(--danger);
}
.kb-doc.is-ready:hover { box-shadow: var(--shadow-md); }
.kb-doc-icon { font-size: 24px; flex-shrink: 0; }
.kb-doc-main { flex: 1; min-width: 0; }
.kb-doc-name { font-size: 14px; font-weight: 600; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kb-doc-meta { display: flex; gap: 8px; margin-top: 4px; font-size: 12px; color: var(--slate); align-items: center; }
.kb-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 8px; border-radius: 10px;
  background: var(--mist-light); color: var(--slate);
}
.kb-date { color: var(--slate-light); }

/* 索引进度条 */
.kb-doc-progress {
  display: flex; align-items: center; gap: 10px;
  margin-top: 8px;
}
.progress-track {
  flex: 1; max-width: 280px;
  height: 6px; border-radius: 3px;
  background: var(--mist); overflow: hidden;
}
.progress-fill {
  height: 100%; border-radius: 3px;
  position: relative; overflow: hidden;
}
.progress-fill.is-pending {
  width: 30%;
  background: var(--slate-light);
}
.progress-fill.is-processing {
  width: 65%;
  background: var(--warning);
}
.progress-shimmer {
  position: absolute; top: 0; left: 0; bottom: 0; right: 0;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.5) 50%,
    transparent 100%
  );
  background-size: 200% 100%;
  animation: kb-shimmer 1.5s ease-in-out infinite;
}
@keyframes kb-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
@media (prefers-reduced-motion: reduce) {
  .progress-shimmer { animation: none; }
}
.progress-label {
  font-size: 12px; color: var(--warning);
  font-weight: 600; white-space: nowrap;
}

/* 失败状态 */
.kb-doc-error { margin-top: 4px; }
.kb-error-text { font-size: 12px; color: var(--danger); }

.kb-doc-side { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; flex-shrink: 0; }
.kb-toggle-group {
  display: flex; flex-direction: column; gap: 8px; align-items: flex-end;
}
.kb-toggle {
  display: flex; align-items: center; gap: 8px;
}
.kb-toggle-label {
  font-size: 12px; color: var(--slate); min-width: 28px; text-align: right;
}
.kb-doc-actions { display: flex; gap: 4px; flex-shrink: 0; }

/* 检索栏 */
.kb-searchbar { display: flex; align-items: center; gap: var(--space-md); padding: var(--space-md) var(--space-lg); margin-bottom: var(--space-md); }
.kb-searchbar .el-input { flex: 1; }
.kb-search-ico { width: 16px; height: 16px; color: var(--slate); }
.control-field { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.control-label { font-size: 12px; color: var(--slate); white-space: nowrap; }

/* 检索结果 */
.kb-results { display: flex; flex-direction: column; gap: 10px; }
.kb-result { padding: var(--space-md) var(--space-lg); }
.kb-result-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
.kb-result-rank { font-size: 12px; font-weight: 700; color: var(--accent); background: var(--accent-soft); border-radius: 6px; padding: 2px 8px; }
.kb-result-file { font-size: 13px; font-weight: 600; color: var(--ink); max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kb-tag { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.kb-tag.is-shared { color: var(--success); background: var(--success-soft); }
.kb-tag.is-private { color: var(--slate); background: var(--mist-light); }
.kb-tag.is-owner { color: var(--accent); background: var(--accent-soft); }
.kb-result-score { margin-left: auto; font-size: 12px; color: var(--slate); }
.kb-result-text { font-size: 13px; line-height: 1.7; color: var(--ink-soft); white-space: pre-wrap; word-break: break-word; max-height: 240px; overflow-y: auto; }

.kb-fulltext { white-space: pre-wrap; word-break: break-word; font-family: var(--font-sans); font-size: 13px; line-height: 1.7; color: var(--ink-soft); margin: 0; }

@media (max-width: 960px) {
  .kb-stats { grid-template-columns: repeat(2, 1fr); }
  .kb-searchbar { flex-wrap: wrap; }
}
</style>

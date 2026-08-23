<template>
  <div class="chat-page">
    <!-- 会话侧边栏 -->
    <aside class="chat-sidebar">
      <button class="new-chat-btn" @click="startNewChat">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round">
          <line x1="12" y1="5" x2="12" y2="19"/>
          <line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
        新建会话
      </button>
      <div class="chat-history">
        <div v-if="sessions.length === 0" class="history-empty">暂无历史会话</div>
        <div
          v-for="session in sessions"
          :key="session.id"
          class="history-item"
          :class="{ active: session.id === currentSessionId }"
          @click="loadSession(session.id)"
        >
          <svg class="history-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
            stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          <div class="history-content">
            <span class="history-title">{{ session.title }}</span>
            <span class="history-time">{{ formatTime(session.updatedAt) }}</span>
          </div>
          <button class="history-delete" @click.stop="deleteSession(session.id)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
              stroke-linecap="round" stroke-linejoin="round">
              <polyline points="3 6 5 6 21 6"/>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
            </svg>
          </button>
        </div>
      </div>
    </aside>

    <!-- 聊天区域 -->
    <div class="chat-main">
      <!-- 消息列表 -->
      <div class="chat-messages" ref="messagesContainer">
        <!-- 欢迎消息 -->
        <div v-if="messages.length === 0" class="chat-welcome">
          <div class="welcome-icon">
            <BrandLogo :size="64" />
          </div>
          <h2>你好，我是慧办 AI 办公搭子</h2>
          <p class="welcome-subtitle">智能办公助手 · 支持文档问答、知识检索与办公工具调用</p>
          <div class="welcome-suggestions">
            <button v-for="s in suggestions" :key="s" class="suggestion-chip" @click="useSuggestion(s)">
              {{ s }}
            </button>
          </div>
        </div>

        <!-- 对话消息 -->
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="message-row"
          :class="msg.role"
        >
          <div class="message-avatar" :class="msg.role">
            <span v-if="msg.role === 'user'">{{ userInitial }}</span>
            <svg v-else viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect x="4" y="7" width="16" height="12" rx="3" stroke="currentColor" stroke-width="1.5"/>
              <circle cx="9" cy="13" r="1.5" fill="currentColor"/>
              <circle cx="15" cy="13" r="1.5" fill="currentColor"/>
              <path d="M12 4v3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
              <circle cx="12" cy="3" r="1.2" fill="currentColor"/>
              <path d="M9.5 16.5h5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
          </div>
          <div class="message-body">

            <!-- 思考过程（推理中展开，完成后收起） -->
            <div
              v-if="msg.role === 'assistant' && (msg.thinking || msg.hint || (msg.toolCalls && msg.toolCalls.length))"
              class="thinking-section"
            >
              <div class="thinking-header" @click="msg.thinkingExpanded = !msg.thinkingExpanded">
                <svg
                  class="chevron"
                  :class="{ expanded: msg.thinkingExpanded }"
                  viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                  stroke-linecap="round" stroke-linejoin="round"
                >
                  <polyline points="9 18 15 12 9 6"/>
                </svg>
                <span class="thinking-label">思考过程</span>
                <span v-if="msg.loading" class="thinking-badge">进行中</span>
              </div>
              <div v-show="msg.thinkingExpanded" class="thinking-content">
                <div v-if="msg.hint" class="hint-text">{{ msg.hint }}</div>
                <div v-if="msg.thinking" class="thinking-text">{{ msg.thinking }}</div>
                <div
                  v-for="tool in msg.toolCalls"
                  :key="tool.id"
                  class="tool-item"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                    stroke-linecap="round" stroke-linejoin="round" class="tool-icon"
                  >
                    <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
                  </svg>
                  <span class="tool-name">{{ tool.name }}</span>
                  <span class="tool-status">{{ tool.done ? '完成' : '调用中' }}</span>
                  <div v-if="tool.args" class="tool-detail">{{ tool.args }}</div>
                  <div v-if="tool.result" class="tool-detail">{{ tool.result }}</div>
                </div>
              </div>
            </div>

            <!-- 消息气泡 -->
            <div class="message-bubble" :class="msg.role">
              <template v-if="msg.role === 'assistant' && msg.loading && !msg.thinking && !msg.toolCalls.length && !msg.clarify">
                <span class="typing-dots">
                  <span></span><span></span><span></span>
                </span>
              </template>
              <template v-else-if="msg.role === 'assistant' && msg.content">
                <MarkdownBody :content="msg.content" :streaming="msg.loading" />
              </template>
              <template v-else-if="msg.content || (msg.attachments && msg.attachments.length)">
                <div v-if="msg.attachments && msg.attachments.length" class="msg-attachments">
                  <div v-for="(att, idx) in msg.attachments" :key="idx" class="msg-attachment-item">
                    <svg class="attachment-file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                      stroke-linecap="round" stroke-linejoin="round">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                      <polyline points="14 2 14 8 20 8"/>
                    </svg>
                    <span>{{ att.original_name }}</span>
                  </div>
                </div>
                <div v-if="msg.content" class="message-text">{{ msg.content }}</div>
              </template>

              <!-- human-in-loop 追问块（agent 调 ask_user 暂停时出现） -->
              <div v-if="msg.clarify && !msg.clarify.answered" class="clarify-block">
                <div class="clarify-question">{{ msg.clarify.question }}</div>
                <div v-if="msg.clarify.options && msg.clarify.options.length" class="clarify-chips">
                  <button
                    v-for="opt in msg.clarify.options"
                    :key="opt"
                    class="suggestion-chip"
                    @click="submitClarify(msg, opt)"
                  >{{ opt }}</button>
                </div>
                <div class="clarify-input-row">
                  <input
                    class="clarify-input"
                    v-model="msg.clarify.draft"
                    placeholder="或输入你的回答…"
                    @keydown.enter.prevent="submitClarify(msg, msg.clarify.draft)"
                  />
                  <button
                    class="clarify-send"
                    :disabled="!(msg.clarify.draft || '').trim()"
                    @click="submitClarify(msg, msg.clarify.draft)"
                  >发送</button>
                </div>
                <div v-if="msg.clarify.error" class="clarify-error">{{ msg.clarify.error }}</div>
              </div>
              <!-- 已作答：折叠为单行摘要，收起交互块 -->
              <div v-else-if="msg.clarify && msg.clarify.answered" class="clarify-answered-line">
                <span class="clarify-answered-icon">✓</span>
                <span class="clarify-answered-q">{{ msg.clarify.question }}</span>
                <span class="clarify-answered-arrow">→</span>
                <span class="clarify-answered-a">{{ msg.clarify.answer }}</span>
              </div>

              <!-- 检索结果画廊（图片缩略图/音频播放器，折叠避免占满窗口） -->
              <RetrievalGallery
                v-if="msg.role === 'assistant' && msg.results && msg.results.length"
                :items="msg.results"
              />
            </div>

            <!-- 复制按钮：有内容且非流式输出时显示 -->
            <button
              v-if="msg.content && !msg.loading"
              class="copy-btn"
              :class="msg.role"
              @click="copyMessage(msg.content)"
              title="复制"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
              </svg>
            </button>
          </div>
        </div>
      </div>

      <!-- 输入区域 -->
      <footer class="chat-input-area">
        <!-- 附件预览列表 -->
        <div v-if="attachedFiles.length" class="attachment-list">
          <div
            v-for="(att, idx) in attachedFiles"
            :key="idx"
            class="attachment-chip"
          >
            <svg class="attachment-file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
              stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
            </svg>
            <span class="attachment-name" :title="att.original_name">{{ att.original_name }}</span>
            <span v-if="att.uploading" class="attachment-status">上传中…</span>
            <span v-if="att.error" class="attachment-status error">{{ att.error }}</span>
            <button
              v-if="!att.uploading"
              class="attachment-remove"
              @click="removeAttachment(idx)"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>
        </div>
        <div class="chat-input-wrapper">
          <input
            ref="fileInput"
            type="file"
            accept=".pdf,.docx,.doc,.xlsx,.xls,.jpg,.jpeg,.png,.bmp,.webp"
            style="display: none"
            @change="handleFileSelect"
          />
          <el-popover
            v-model:visible="plusMenuVisible"
            placement="top-start"
            :width="280"
            trigger="click"
            popper-class="kb-plus-popover"
            :show-arrow="false"
          >
            <template #reference>
              <button
                class="plus-btn"
                :class="{ active: plusMenuVisible }"
                :disabled="isWaiting"
                title="功能菜单 · 上传文件 / 知识库检索 / 会议检索"
                type="button"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                  stroke-linecap="round" stroke-linejoin="round">
                  <line x1="12" y1="5" x2="12" y2="19"/>
                  <line x1="5" y1="12" x2="19" y2="12"/>
                </svg>
                <span v-if="useKB || useMeetingKB" class="plus-btn-badge" title="检索开关已开启"></span>
              </button>
            </template>
            <div class="plus-menu">
              <button class="plus-menu-item" type="button" @click="onMenuUpload">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
                  stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="17 8 12 3 7 8"/>
                  <line x1="12" y1="3" x2="12" y2="15"/>
                </svg>
                <span class="plus-menu-text">
                  <span class="plus-menu-title">上传文件</span>
                </span>
              </button>
              <button
                class="plus-menu-item kb-menu-item"
                :class="{ on: useKB }"
                type="button"
                @click="useKB = !useKB"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
                  stroke-linecap="round" stroke-linejoin="round">
                  <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
                  <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
                </svg>
                <span class="plus-menu-text">
                  <span class="plus-menu-title">知识库检索</span>
                </span>
                <span class="kb-mini-switch" :class="{ on: useKB }"><span class="kb-mini-thumb"></span></span>
              </button>
              <button
                class="plus-menu-item kb-menu-item"
                :class="{ on: useMeetingKB }"
                type="button"
                @click="useMeetingKB = !useMeetingKB"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
                  stroke-linecap="round" stroke-linejoin="round">
                  <path d="m16 13 5.2-3.1a2 2 0 0 1 3 1.7v6.8a2 2 0 0 1-3 1.7L16 17"/>
                  <rect x="2" y="6" width="14" height="12" rx="2"/>
                </svg>
                <span class="plus-menu-text">
                  <span class="plus-menu-title">会议检索</span>
                </span>
                <span class="kb-mini-switch" :class="{ on: useMeetingKB }"><span class="kb-mini-thumb"></span></span>
              </button>
            </div>
          </el-popover>
          <el-input
            v-model="inputText"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 4 }"
            placeholder="输入你的问题…"
            resize="none"
            @keydown.enter.exact.prevent="sendMessage"
          />
          <button
            v-if="isWaiting"
            class="stop-btn"
            @click="stopGeneration"
          >
            <svg viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="6" width="12" height="12" rx="2"/>
            </svg>
          </button>
          <button
            v-else
            class="send-btn"
            :disabled="!inputText.trim() && !attachedFiles.some(f => !f.uploading && !f.error)"
            @click="sendMessage"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="22" y1="2" x2="11" y2="13"/>
              <polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
          </button>
        </div>
        <div class="chat-input-meta">
          <p class="chat-input-hint">按 Enter 发送 · Shift + Enter 换行</p>
        </div>
      </footer>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, nextTick, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import config from '/config'
import RetrievalGallery from '@/components/RetrievalGallery.vue'
import BrandLogo from '@/components/BrandLogo.vue'
import MarkdownBody from '@/components/MarkdownBody.vue'

const store = useUserStore()
const userInitial = computed(() => {
  const name = store.loginInfo.user?.username || 'U'
  return name.charAt(0).toUpperCase()
})

// ── 会话管理（后端为唯一真源） ──
const sessions = ref([])
const currentSessionId = ref(null)
const messages = ref([])
const inputText = ref('')
const isWaiting = ref(false)
const messagesContainer = ref(null)
const attachedFiles = ref([])
const fileInput = ref(null)
// 知识库检索开关：开启时本次对话启用 RAG（后端按 use_kb 激活 search_knowledge 工具）；
// 持久化到 localStorage，默认开启。
const useKB = ref(localStorage.getItem('kb_retrieval_enabled') !== 'false')
const onKBToggle = (v) => localStorage.setItem('kb_retrieval_enabled', v ? 'true' : 'false')
watch(useKB, onKBToggle)
// 会议检索开关：开启后智能体可检索我的会议知识库（独立于个人知识库）；默认关闭。
const useMeetingKB = ref(localStorage.getItem('meeting_kb_enabled') === 'true')
const onMeetingKBToggle = (v) => localStorage.setItem('meeting_kb_enabled', v ? 'true' : 'false')
watch(useMeetingKB, onMeetingKBToggle)
// 「+」功能菜单（上传文件 / 知识库检索）展开状态
const plusMenuVisible = ref(false)

const suggestions = [
  '列出可用的图像库索引',
  '搜索包含"起重机"的图片',
  '搜索包含"诗歌朗诵"的音频',
]

// 本地消息 id 计数器：仅用于在内存数组中唯一标识消息，不参与持久化
let msgId = 0
const genId = () => ++msgId

// 生成会话 id：优先用 crypto.randomUUID（安全上下文下可用），否则回退到
// Math.random 构造的 v4 形态。UUID4 使多用户同一毫秒各发首条消息也不会撞库，
// 且不可枚举（后端 offload/会话已按 user_id 隔离，此处为纵深防御）。
const newSessionId = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

const authHeaders = () => ({ 'Authorization': store.getBearerToken })

const loadSessions = async () => {
  try {
    const resp = await fetch(`${config.agent}/sessions`, { headers: authHeaders() })
    if (!resp.ok) throw new Error(`加载会话列表失败 (${resp.status})`)
    const data = await resp.json()
    sessions.value = data.sessions || []
  } catch (e) {
    console.warn('加载会话列表失败:', e)
    sessions.value = []
  }
}

const startNewChat = () => {
  currentSessionId.value = null
  messages.value = []
}

const loadSession = async (id) => {
  try {
    const resp = await fetch(`${config.agent}/sessions/${id}/messages`, { headers: authHeaders() })
    if (!resp.ok) throw new Error(`加载会话失败 (${resp.status})`)
    const data = await resp.json()
    currentSessionId.value = id
    messages.value = (data.messages || []).map(m => ({
      ...m,
      loading: false,
      thinkingExpanded: false,
      // 检索画廊 + human-in-loop 追问随会话持久化恢复（旧消息无这些字段时归一化）
      results: Array.isArray(m.results) ? m.results : [],
      clarify: m.clarify
        ? { ...m.clarify, draft: m.clarify.draft || '', error: '' }
        : null,
    }))
    // 同步本地计数器，避免新消息 id 与历史消息冲突
    msgId = Math.max(0, ...messages.value.map(m => Number(m.id) || 0))
    scrollToBottom()
  } catch (e) {
    console.warn('加载会话失败:', e)
  }
}

const deleteSession = async (id) => {
  try {
    await fetch(`${config.agent}/sessions/${id}`, {
      method: 'DELETE',
      headers: authHeaders(),
    })
  } catch (e) {
    console.warn('清理后端会话状态失败:', e)
  }
  sessions.value = sessions.value.filter(s => s.id !== id)
  if (currentSessionId.value === id) {
    currentSessionId.value = null
    messages.value = []
  }
}

const formatTime = (timestamp) => {
  const ts = Number(timestamp) || 0
  const diff = Date.now() - ts
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 8640000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes}分钟前`
  if (hours < 24) return `${hours}小时前`
  if (days < 7) return `${days}天前`
  return new Date(ts).toLocaleDateString()
}

onMounted(() => {
  loadSessions()
})

const scrollToBottom = () => {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

const useSuggestion = (text) => {
  inputText.value = text
  sendMessage()
}

const copyMessage = async (text) => {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本')
  }
}

// ── 文件上传 ──
const triggerFileUpload = () => {
  fileInput.value?.click()
}
// 「+」菜单：选择上传文件 → 关闭菜单并唤起文件选择
const onMenuUpload = () => {
  plusMenuVisible.value = false
  triggerFileUpload()
}

const handleFileSelect = async (event) => {
  const files = event.target.files
  if (!files || !files.length) return

  const allowedExts = ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.jpg', '.jpeg', '.png', '.bmp', '.webp']

  for (const file of files) {
    const ext = '.' + file.name.toLowerCase().split('.').pop()
    if (!allowedExts.includes(ext)) continue

    const att = reactive({
      original_name: file.name,
      file_type: '',
      extract_filename: '',
      compare_filename: '',
      file_path: '',
      uploading: true,
      error: '',
    })
    attachedFiles.value.push(att)

    try {
      const formData = new FormData()
      formData.append('file', file)
      const resp = await fetch(`${config.agent}/upload`, {
        method: 'POST',
        headers: { 'Authorization': store.getBearerToken },
        body: formData,
      })
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}))
        throw new Error(errData.detail || `上传失败 (${resp.status})`)
      }
      const data = await resp.json()
      att.file_type = data.file_type
      if (data.file_type === 'image') {
        att.file_path = data.file_path
        if (data.extract_filename) att.extract_filename = data.extract_filename
      } else {
        att.extract_filename = data.extract_filename
        att.compare_filename = data.compare_filename
      }
      att.uploading = false
    } catch (err) {
      att.uploading = false
      att.error = err.message
    }
  }

  // 重置 input，使同一文件可再次选择
  event.target.value = ''
}

const removeAttachment = (idx) => {
  attachedFiles.value.splice(idx, 1)
}

const stopGeneration = async () => {
  if (!currentSessionId.value) return
  try {
    await fetch(`${config.agent}/chat/stop`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': store.getBearerToken,
      },
      body: JSON.stringify({ session_id: currentSessionId.value }),
    })
  } catch (e) {
    console.warn('停止请求失败:', e)
  }
}

// human-in-loop：提交追问作答，恢复被暂停的回复流
const submitClarify = async (msg, answer) => {
  const a = (answer || '').trim()
  if (!a || msg.clarify.answered) return
  try {
    const resp = await fetch(`${config.agent}/chat/answer`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': store.getBearerToken,
      },
      body: JSON.stringify({ reply_id: msg.clarify.reply_id, answer: a }),
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}))
      msg.clarify.error = err.detail || '追问已过期，请重新提问'
      return
    }
    msg.clarify.answered = true
    msg.clarify.answer = a
    msg.clarify.draft = ''
    msg.clarify.error = ''
  } catch (e) {
    msg.clarify.error = '提交失败，请重试'
  }
}

const sendMessage = async () => {
  const text = inputText.value.trim()
  const readyAttachments = attachedFiles.value.filter(f => !f.uploading && !f.error)
  if ((!text && !readyAttachments.length) || isWaiting.value) return

  // 首条消息时创建新会话（本地占位，后端在 /chat 落盘）
  if (!currentSessionId.value) {
    currentSessionId.value = newSessionId()
    sessions.value.unshift({
      id: currentSessionId.value,
      title: (text || `上传了 ${readyAttachments.length} 个文件`).slice(0, 30),
      updatedAt: Date.now(),
    })
  }

  // 添加用户消息
  messages.value.push({
    id: genId(),
    role: 'user',
    content: text,
    attachments: readyAttachments.map(f => ({ original_name: f.original_name })),
  })
  inputText.value = ''
  attachedFiles.value = []
  scrollToBottom()

  // 添加助手消息（等待响应）
  isWaiting.value = true
  const loadingId = genId()
  messages.value.push({
    id: loadingId,
    role: 'assistant',
    content: '',
    loading: true,
    thinking: '',
    hint: '',
    toolCalls: [],
    thinkingExpanded: true,
    clarify: null,   // human-in-loop 追问 {reply_id, question, options, answered, answer, draft}
    results: [],     // 检索画廊 items（图片/音频）
  })
  scrollToBottom()

  // 通过 SSE 流式获取 Agent 响应
  try {
    const resp = await fetch(`${config.agent}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': store.getBearerToken,
      },
      body: JSON.stringify({
        message: text,
        session_id: currentSessionId.value,
        use_kb: useKB.value,
        use_meeting_kb: useMeetingKB.value,
        attachments: readyAttachments.length
          ? readyAttachments.map(f => ({
              original_name: f.original_name,
              file_type: f.file_type,
              extract_filename: f.extract_filename || undefined,
              compare_filename: f.compare_filename || undefined,
              file_path: f.file_path || undefined,
            }))
          : undefined,
      }),
    })

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}))
      throw new Error(errData.detail || `请求失败 (${resp.status})`)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop()

      for (const part of parts) {
        const line = part.trim()
        if (!line.startsWith('data: ')) continue

        const data = JSON.parse(line.slice(6))
        const target = messages.value.find(m => m.id === loadingId)
        if (!target) break

        if (data.type === 'thinking') {
          target.thinking += data.content
        } else if (data.type === 'tool_call') {
          target.toolCalls.push({ id: data.id, name: data.name, args: '', result: '', done: false })
        } else if (data.type === 'tool_args') {
          const tool = target.toolCalls.find(t => t.id === data.id)
          if (tool) tool.args += data.content
        } else if (data.type === 'tool_result_delta') {
          const tool = target.toolCalls.find(t => t.id === data.id)
          if (tool) tool.result += data.content
        } else if (data.type === 'tool_result_data') {
          const tool = target.toolCalls.find(t => t.id === data.id)
          if (tool && data.url) tool.result += `[文件] ${data.url}\n`
        } else if (data.type === 'clarify') {
          // human-in-loop：agent 调 ask_user 暂停，前端弹追问块，用户作答后续流
          target.clarify = {
            reply_id: data.reply_id,
            tool_call_id: data.tool_call_id,
            question: data.question,
            options: data.options || [],
            answered: false,
            answer: '',
            draft: '',
            error: '',
          }
        } else if (data.type === 'retrieval') {
          // 检索工具结构化结果 → 画廊
          target.results.push(...(data.items || []))
        } else if (data.type === 'tool_result') {
          const tool = target.toolCalls.find(t => t.id === data.id)
          if (tool) tool.done = true
        } else if (data.type === 'hint') {
          target.hint += data.content
        } else if (data.type === 'token') {
          target.content += data.content
        } else if (data.type === 'done') {
          target.loading = false
          target.thinkingExpanded = false
          if (!target.content) {
            target.content = '（空响应）'
          }
        } else if (data.type === 'stopped') {
          target.loading = false
          target.thinkingExpanded = false
          if (!target.content) {
            target.content = '（已停止生成）'
          }
        } else if (data.type === 'error') {
          target.loading = false
          target.thinkingExpanded = false
          target.content = `处理出错：${data.content}`
        }
      }
      scrollToBottom()
    }

    // 流结束时确保 loading 状态关闭
    const target = messages.value.find(m => m.id === loadingId)
    if (target && target.loading) {
      target.loading = false
      target.thinkingExpanded = false
      if (!target.content) {
        target.content = '（连接已断开）'
      }
    }
  } catch (err) {
    const target = messages.value.find(m => m.id === loadingId)
    if (target) {
      target.loading = false
      target.thinkingExpanded = false
      target.content = `处理请求时出错：${err.message}\n\n请确认后端服务已启动（Agent Service 和 MCP Server）。`
    }
  } finally {
    isWaiting.value = false
    scrollToBottom()
    // 同步本地会话列表的时间戳（消息与标题已由后端持久化）
    const session = sessions.value.find(s => s.id === currentSessionId.value)
    if (session) session.updatedAt = Date.now()
  }
}
</script>

<style scoped>
.chat-page {
  display: flex;
  height: 100vh;
  background: var(--paper);
}

/* --- 会话侧边栏 --- */
.chat-sidebar {
  flex-shrink: 0;
  width: 260px;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border-right: 1px solid var(--mist);
}

.new-chat-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 16px;
  padding: 10px 16px;
  border: 1px solid var(--mist);
  border-radius: var(--radius-md);
  background: var(--paper);
  color: var(--ink);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition);
}

.new-chat-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-soft);
}

.new-chat-btn svg {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.chat-history {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px 8px;
}

.chat-history::-webkit-scrollbar {
  width: 3px;
}

.chat-history::-webkit-scrollbar-thumb {
  background: var(--mist);
  border-radius: 2px;
}

.history-empty {
  text-align: center;
  color: var(--slate-light);
  font-size: 13px;
  padding: 24px 0;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--transition);
  position: relative;
}

.history-item:hover {
  background: var(--paper);
}

.history-item.active {
  background: var(--accent-soft);
}

.history-icon {
  width: 16px;
  height: 16px;
  color: var(--slate-light);
  flex-shrink: 0;
}

.history-item.active .history-icon {
  color: var(--accent);
}

.history-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.history-title {
  font-size: 13px;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.history-item.active .history-title {
  color: var(--accent);
  font-weight: 500;
}

.history-time {
  font-size: 11px;
  color: var(--slate-light);
}

.history-delete {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--slate-light);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: all var(--transition);
}

.history-item:hover .history-delete {
  opacity: 1;
}

.history-delete:hover {
  background: #fee2e2;
  color: #ef4444;
}

.history-delete svg {
  width: 14px;
  height: 14px;
}

/* --- 聊天区域 --- */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

/* --- 消息列表 --- */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

/* AI 回复紧接用户输入时，额外加大两者的间隔 */
.message-row.user + .message-row.assistant,
.message-row.assistant + .message-row.user {
  margin-top: 10px;
}

/* 欢迎屏 */
.chat-welcome {
  margin: auto;
  text-align: center;
  max-width: 480px;
}

.welcome-icon {
  width: 64px;
  height: 64px;
  margin: 0 auto 20px;
}

.welcome-icon svg {
  width: 100%;
  height: 100%;
}

.chat-welcome h2 {
  font-size: 22px;
  font-weight: 700;
  color: var(--ink);
  margin: 0 0 8px;
}

.chat-welcome p {
  font-size: 14px;
  color: var(--slate);
  margin: 0 0 4px;
  line-height: 1.6;
}

.welcome-subtitle {
  font-size: 14px;
  color: var(--slate);
  margin: 4px 0 0;
  line-height: 1.6;
}

/* 欢迎屏建议 */
.welcome-suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 24px;
}

.suggestion-chip {
  padding: 8px 16px;
  border: 1px solid var(--mist);
  border-radius: 20px;
  background: var(--surface);
  color: var(--slate);
  font-size: 13px;
  cursor: pointer;
  transition: all var(--transition);
}

.suggestion-chip:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-soft);
}

/* ── human-in-loop 追问块 ── */
.clarify-block {
  margin-top: var(--space-md);
  padding: var(--space-md);
  border: 1px solid var(--accent);
  border-radius: var(--radius-md);
  background: var(--accent-soft);
}
.clarify-question {
  font-size: 14px;
  color: var(--ink);
  margin-bottom: var(--space-sm);
  line-height: 1.5;
}
.clarify-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  margin-bottom: var(--space-sm);
}
.clarify-chips .suggestion-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.clarify-input-row {
  display: flex;
  gap: var(--space-sm);
  margin-top: var(--space-xs);
}
.clarify-input {
  flex: 1;
  padding: 6px 12px;
  border: 1px solid var(--mist);
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--ink);
  background: var(--surface);
  outline: none;
  transition: border-color var(--transition);
}
.clarify-input:focus { border-color: var(--accent); }
.clarify-input:disabled { opacity: 0.6; }
.clarify-send {
  padding: 6px 16px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
  transition: background var(--transition);
}
.clarify-send:hover:not(:disabled) { background: var(--accent-hover); }
.clarify-send:disabled { opacity: 0.5; cursor: not-allowed; }
.clarify-error {
  margin-top: var(--space-xs);
  font-size: 12px;
  color: var(--danger);
}
/* 已作答：折叠为单行摘要，收起交互块 */
.clarify-answered-line {
  margin-top: var(--space-md);
  padding: var(--space-xs) var(--space-sm);
  border-radius: var(--radius-sm);
  background: var(--success-soft, #ECFDF5);
  font-size: 12px;
  color: var(--slate);
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  flex-wrap: wrap;
}
.clarify-answered-icon {
  color: var(--success, #10B981);
  font-weight: 700;
}
.clarify-answered-q {
  color: var(--slate, #64748B);
  max-width: 60%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.clarify-answered-arrow { color: var(--slate-light, #9CA3AF); }
.clarify-answered-a {
  color: var(--ink-soft, #334155);
  font-weight: 500;
}

/* 消息行 */
.message-row {
  display: flex;
  gap: 12px;
  max-width: 760px;
  width: 100%;
  margin: 0 auto;
}

.message-row.user {
  flex-direction: row-reverse;
}

.message-avatar {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
}

.message-avatar.user {
  background: var(--accent);
  color: #fff;
}

.message-avatar.assistant {
  background: var(--accent-soft);
  color: var(--accent);
}

.message-avatar.assistant svg {
  width: 22px;
  height: 22px;
}

.message-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.message-row.user .message-body {
  align-items: flex-end;
}

.message-bubble {
  padding: 10px 14px;
  border-radius: var(--radius-md);
  font-size: 14px;
  line-height: 1.7;
  letter-spacing: 0.01em;
  word-break: break-word;
  -webkit-font-smoothing: antialiased;
}

.message-bubble.user {
  background: var(--accent);
  color: #fff;
  border-bottom-right-radius: 4px;
  font-weight: 400;
}

.message-bubble.assistant {
  background: var(--surface);
  color: var(--ink);
  border: 1px solid var(--mist);
  border-bottom-left-radius: 4px;
  font-weight: 400;
}

.message-bubble.assistant .message-text {
  font-size: 14px;
  line-height: 1.75;
  color: var(--ink-soft);
}

.message-bubble.user .message-text {
  font-size: 14px;
  line-height: 1.7;
  color: #fff;
}

.message-text {
  white-space: pre-wrap;
}

/* 复制按钮：hover 气泡时淡入 */
.copy-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  margin-top: 4px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--slate-light);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s ease, background 0.15s ease, color 0.15s ease;
  align-self: flex-start;
}

/* 用户消息在右侧，复制按钮靠右 */
.copy-btn.user {
  align-self: flex-end;
}

.copy-btn svg {
  width: 15px;
  height: 15px;
}

.copy-btn:hover {
  background: var(--mist-light);
  color: var(--ink-soft);
}

.copy-btn:active {
  transform: scale(0.94);
}

.message-row:hover .copy-btn {
  opacity: 1;
}

/* 打字动画 */
.typing-dots {
  display: inline-flex;
  gap: 4px;
  padding: 4px 0;
}

.typing-dots span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--slate-light);
  animation: typing-bounce 1.4s infinite ease-in-out;
}

.typing-dots span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-dots span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes typing-bounce {
  0%, 60%, 100% {
    transform: translateY(0);
    opacity: 0.4;
  }
  30% {
    transform: translateY(-6px);
    opacity: 1;
  }
}

/* --- 输入区 --- */
.chat-input-area {
  flex-shrink: 0;
  padding: 12px 24px 20px;
  background: var(--surface);
  border-top: 1px solid var(--mist);
}

.chat-input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  max-width: 760px;
  margin: 0 auto;
  background: var(--paper);
  border: 1px solid var(--mist);
  border-radius: var(--radius-md);
  padding: 8px 8px 8px 16px;
  transition: border-color var(--transition);
}

.chat-input-wrapper:focus-within {
  border-color: var(--accent);
}

.chat-input-wrapper :deep(.el-textarea__inner) {
  border: none !important;
  box-shadow: none !important;
  background: transparent !important;
  padding: 6px 0 !important;
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.6;
}

/* 附件预览列表 */
.attachment-list {
  max-width: 760px;
  margin: 0 auto 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.attachment-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  background: var(--accent-soft);
  border: 1px solid var(--mist);
  font-size: 12px;
  color: var(--slate);
  max-width: 240px;
}

.attachment-file-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  color: var(--accent);
}

.attachment-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 140px;
}

.attachment-status {
  font-size: 11px;
  color: var(--slate-light);
  flex-shrink: 0;
}

.attachment-status.error {
  color: #ef4444;
}

.attachment-remove {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--slate-light);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
}

.attachment-remove:hover {
  background: #fee2e2;
  color: #ef4444;
}

.attachment-remove svg {
  width: 10px;
  height: 10px;
}

/* 「+」功能按钮 */
.plus-btn {
  position: relative;
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--slate-light);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition);
}

.plus-btn:hover:not(:disabled) {
  color: var(--accent);
  background: var(--accent-soft);
}

/* 激活态：浅蓝实底 + 白色图标，图标旋转 45°（+ 转 ×）暗示可收起 */
.plus-btn.active {
  color: #FFFFFF;
  background: #60A5FA;
  box-shadow: 0 2px 8px rgba(96, 165, 250, 0.45);
}

.plus-btn.active:hover:not(:disabled) {
  background: #93C5FD;
}

.plus-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.plus-btn svg {
  width: 20px;
  height: 20px;
  transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.plus-btn.active svg {
  transform: rotate(45deg);
}

/* RAG 启用时的状态徽标（绿点） */
.plus-btn-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--success);
  border: 2px solid var(--paper);
}

/* 消息内附件显示 */
.msg-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
}

.msg-attachment-item {
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.2);
  font-size: 12px;
}

.message-bubble.user .msg-attachment-item {
  background: rgba(255, 255, 255, 0.2);
}

.message-bubble.assistant .msg-attachment-item {
  background: var(--mist);
}

.msg-attachment-item .attachment-file-icon {
  width: 12px;
  height: 12px;
}

.send-btn {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background var(--transition);
}

.send-btn:hover:not(:disabled) {
  background: var(--accent-hover);
}

.send-btn:disabled {
  background: var(--mist);
  color: var(--slate-light);
  cursor: not-allowed;
}

.stop-btn {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: var(--radius-sm);
  background: #ef4444;
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background var(--transition);
}

.stop-btn:hover {
  background: #dc2626;
}

.stop-btn svg {
  width: 16px;
  height: 16px;
}

.send-btn svg {
  width: 18px;
  height: 18px;
}

.chat-input-hint {
  text-align: center;
  font-size: 12px;
  color: var(--slate-light);
  margin: 8px 0 0;
}

/* 底部提示行（上传 / 知识库检索已并入「+」菜单） */
.chat-input-meta {
  max-width: 760px;
  margin: 8px auto 0;
}

.chat-input-meta .chat-input-hint {
  margin: 0;
  text-align: center;
}

/* 思考过程（可折叠） */
.thinking-section {
  margin-bottom: 6px;
}

.thinking-header {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  color: var(--slate);
}

.chevron {
  width: 14px;
  height: 14px;
  transition: transform 0.2s;
  transform: rotate(0deg);
  flex-shrink: 0;
}

.chevron.expanded {
  transform: rotate(90deg);
}

.thinking-label {
  font-weight: 500;
}

.thinking-badge {
  padding: 1px 8px;
  border-radius: 10px;
  background: #dbeafe;
  color: #2563eb;
  font-size: 11px;
}

.thinking-content {
  padding-top: 4px;
}

.hint-text {
  font-size: 12px;
  line-height: 1.5;
  color: var(--slate);
  background: var(--mist);
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 8px;
  white-space: pre-wrap;
  word-break: break-word;
}

.thinking-text {
  font-size: 13px;
  line-height: 1.6;
  color: var(--slate);
  white-space: pre-wrap;
  word-break: break-word;
}

.tool-item {
  padding: 4px 0;
  font-size: 13px;
  display: flex;
  align-items: flex-start;
  gap: 6px;
  flex-wrap: wrap;
}

.tool-icon {
  width: 14px;
  height: 14px;
  color: var(--slate-light);
  flex-shrink: 0;
  margin-top: 2px;
}

.tool-name {
  color: var(--ink);
  font-weight: 500;
}

.tool-status {
  font-size: 11px;
  color: var(--slate-light);
}

.tool-detail {
  width: 100%;
  font-size: 12px;
  color: var(--slate);
  white-space: pre-wrap;
  word-break: break-all;
  padding-left: 20px;
}

/* Markdown 渲染样式已迁移至 global.css（全局样式可作用于 v-html 注入的元素） */

/* --- 响应式 --- */
@media (max-width: 768px) {
  .chat-sidebar {
    width: 200px;
  }
}

@media (max-width: 640px) {
  .chat-sidebar {
    display: none;
  }

  .chat-messages {
    padding: 16px;
  }

  .chat-input-area {
    padding: 12px 16px 16px;
  }

  .message-row {
    gap: 8px;
  }

  .message-avatar {
    width: 30px;
    height: 30px;
    font-size: 12px;
  }
}
</style>

<!-- 非 scoped：el-popover 内容被 teleport 到 body，需全局样式 -->
<style>
.kb-plus-popover.el-popover {
  padding: 8px;
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  border: 1px solid var(--mist);
}

.kb-plus-popover .plus-menu {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.kb-plus-popover .plus-menu-item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 10px 12px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  cursor: pointer;
  text-align: left;
  font-family: var(--font-sans);
  transition: background var(--transition);
}

.kb-plus-popover .plus-menu-item:hover {
  background: var(--mist-light);
}

.kb-plus-popover .plus-menu-item.kb-menu-item.on {
  background: var(--accent-soft);
}

.kb-plus-popover .plus-menu-item svg {
  width: 18px;
  height: 18px;
  color: var(--accent);
  flex-shrink: 0;
}

.kb-plus-popover .plus-menu-text {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  line-height: 1.3;
}

.kb-plus-popover .plus-menu-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
}

/* 菜单内迷你开关 */
.kb-plus-popover .kb-mini-switch {
  position: relative;
  width: 32px;
  height: 18px;
  border-radius: 9px;
  background: var(--slate-light);
  flex-shrink: 0;
  transition: background var(--transition);
}

.kb-plus-popover .kb-mini-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 2px rgba(30, 41, 59, 0.25);
  transition: transform var(--transition);
}

.kb-plus-popover .kb-mini-switch.on {
  background: var(--accent);
}

.kb-plus-popover .kb-mini-switch.on .kb-mini-thumb {
  transform: translateX(14px);
}
</style>

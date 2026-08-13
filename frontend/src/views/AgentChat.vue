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
            <svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect width="64" height="64" rx="16" fill="#2563EB"/>
              <path d="M20 17C20 15.34 21.34 14 22.5 14H36l8 8v25c0 1.66-1.34 3-3 3H22.5c-1.16 0-2.5-1.34-2.5-3V17Z" fill="white" fill-opacity="0.9"/>
              <path d="M36 14v8h8" stroke="#2563EB" stroke-width="2.5" stroke-linejoin="round" fill="white"/>
              <line x1="25" y1="30" x2="37" y2="30" stroke="#93C5FD" stroke-width="2.5" stroke-linecap="round"/>
              <line x1="25" y1="36" x2="34" y2="36" stroke="#93C5FD" stroke-width="2.5" stroke-linecap="round"/>
              <path d="M45 13l1.6 4.4L51 19l-4.4 1.6L45 25l-1.6-4.4L39 19l4.4-1.6L45 13Z" fill="#FDE047"/>
            </svg>
          </div>
          <h2>你好，我是专属的 AI 办公搭子</h2>
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
              <template v-if="msg.role === 'assistant' && msg.loading && !msg.thinking && !msg.toolCalls.length">
                <span class="typing-dots">
                  <span></span><span></span><span></span>
                </span>
              </template>
              <template v-else-if="msg.role === 'assistant' && msg.content">
                <div class="markdown-body" v-html="renderMarkdown(msg.content)"></div>
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
            </div>
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
          <button class="upload-btn" @click="triggerFileUpload" :disabled="isWaiting" title="上传 PDF/Word/Excel 文件">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
              stroke-linecap="round" stroke-linejoin="round">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
            </svg>
          </button>
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
        <p class="chat-input-hint">按 Enter 发送 · Shift + Enter 换行 · 点击回形针上传 PDF、Word、Excel 或图片</p>
      </footer>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, nextTick, computed, onMounted } from 'vue'
import { useUserStore } from '@/stores/user'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import config from '/config'

marked.setOptions({ breaks: true, gfm: true })

const renderMarkdown = (text) => {
  if (!text) return ''
  return DOMPurify.sanitize(marked.parse(text))
}

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

const suggestions = [
  '列出可用的图像库索引',
  '搜索包含"起重机"的图片',
  '搜索包含"诗歌朗诵"的音频',
]

// 本地消息 id 计数器：仅用于在内存数组中唯一标识消息，不参与持久化
let msgId = 0
const genId = () => ++msgId

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

// ── 文件上传 ──
const triggerFileUpload = () => {
  fileInput.value?.click()
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

const sendMessage = async () => {
  const text = inputText.value.trim()
  const readyAttachments = attachedFiles.value.filter(f => !f.uploading && !f.error)
  if ((!text && !readyAttachments.length) || isWaiting.value) return

  // 首条消息时创建新会话（本地占位，后端在 /chat 落盘）
  if (!currentSessionId.value) {
    currentSessionId.value = String(Date.now())
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
  line-height: 1.6;
  word-break: break-word;
}

.message-bubble.user {
  background: var(--accent);
  color: #fff;
  border-bottom-right-radius: 4px;
}

.message-bubble.assistant {
  background: var(--surface);
  color: var(--ink);
  border: 1px solid var(--mist);
  border-bottom-left-radius: 4px;
}

.message-text {
  white-space: pre-wrap;
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

/* 上传按钮 */
.upload-btn {
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

.upload-btn:hover:not(:disabled) {
  color: var(--accent);
  background: var(--accent-soft);
}

.upload-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.upload-btn svg {
  width: 18px;
  height: 18px;
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

/* Markdown 渲染 */
.markdown-body {
  font-size: 14px;
  line-height: 1.6;
}

.markdown-body p {
  margin: 0 0 8px;
}

.markdown-body p:last-child {
  margin-bottom: 0;
}

.markdown-body h1,
.markdown-body h2,
.markdown-body h3 {
  margin: 12px 0 6px;
  font-weight: 600;
}

.markdown-body h1 { font-size: 18px; }
.markdown-body h2 { font-size: 16px; }
.markdown-body h3 { font-size: 15px; }

.markdown-body ul,
.markdown-body ol {
  margin: 0 0 8px;
  padding-left: 20px;
}

.markdown-body li {
  margin: 2px 0;
}

.markdown-body code {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--mist);
  font-size: 13px;
  font-family: 'SF Mono', 'Fira Code', monospace;
}

.markdown-body pre {
  margin: 0 0 8px;
  padding: 12px;
  border-radius: var(--radius-sm);
  background: #1e293b;
  overflow-x: auto;
}

.markdown-body pre code {
  padding: 0;
  background: none;
  color: #e2e8f0;
  font-size: 13px;
}

.markdown-body blockquote {
  margin: 0 0 8px;
  padding: 4px 12px;
  border-left: 3px solid var(--accent);
  background: var(--accent-soft);
  color: var(--slate);
}

.markdown-body table {
  border-collapse: collapse;
  margin: 0 0 8px;
  width: 100%;
}

.markdown-body th,
.markdown-body td {
  border: 1px solid var(--mist);
  padding: 6px 10px;
  text-align: left;
}

.markdown-body th {
  background: var(--paper);
  font-weight: 600;
}

.markdown-body a {
  color: var(--accent);
  text-decoration: none;
}

.markdown-body a:hover {
  text-decoration: underline;
}

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

<template>
  <div class="page-container">
    <div class="retrieval-page">
      <header class="retrieval-header">
        <h1 class="page-title"><span class="title-accent" />我的会议</h1>
      </header>

      <!-- 加载中 -->
      <div v-if="!accountChecked" class="retrieval-state retrieval-loading card">
        <div class="spinner" /><div class="state-title">加载中…</div>
      </div>

      <template v-else>
        <!-- 统计 -->
        <div class="mt-stats">
          <div class="mt-stat card">
            <div class="mt-stat-num">{{ meetings.length }}</div>
            <div class="mt-stat-label">已接收会议</div>
          </div>
          <div class="mt-stat card">
            <div class="mt-stat-num">{{ activeTodos }}</div>
            <div class="mt-stat-label">我的待办</div>
          </div>
          <div class="mt-stat card">
            <div class="mt-stat-num">{{ pendingTodos }}</div>
            <div class="mt-stat-label">待我确认</div>
          </div>
        </div>

        <!-- 标签切换 -->
        <div class="mt-tabs card">
          <button class="mt-tab" :class="{ active: tab === 'meetings' }" @click="tab = 'meetings'">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m16 13 5.2-3.1a2 2 0 0 1 3 1.7v6.8a2 2 0 0 1-3 1.7L16 17"/><rect x="2" y="6" width="14" height="12" rx="2"/></svg>
            会议列表
          </button>
          <button class="mt-tab" :class="{ active: tab === 'todos' }" @click="tab = 'todos'">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="6" height="6" rx="1"/><path d="m4 17 2 2 4-4"/><path d="M13 6h8"/><path d="M13 12h8"/><path d="M13 18h8"/></svg>
            我的待办
            <span v-if="pendingTodos" class="mt-tab-badge">{{ pendingTodos }}</span>
          </button>
          <button class="mt-tab" :class="{ active: tab === 'settings' }" @click="tab = 'settings'">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h0a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h0a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
            接收设置
          </button>
        </div>

        <!-- 会议列表 -->
        <section v-if="tab === 'meetings'" class="mt-panel">
          <!-- 未配置账号：引导前往「接收设置」配置（切换 tab 后设置表单始终渲染） -->
          <div v-if="!account.configured" class="retrieval-state card">
            <div class="state-icon">📹</div>
            <div class="state-title">连接你的飞书账号，自动接收会议</div>
            <div class="state-hint">
              会议结束后自动接收妙记/智能纪要，由子智能体生成摘要与你的待办，无需手动上传。
            </div>
            <el-button type="primary" class="mt-btn" @click="tab = 'settings'">前往配置</el-button>
          </div>

          <template v-else>
            <div class="mt-toolbar card">
              <div class="mt-toolbar-hint">
                每 {{ syncIntervalText }}自动同步已结束会议；也可手动触发立即接收。
              </div>
              <el-button type="primary" :loading="syncing" @click="doSync">
                {{ syncing ? '接收中…' : '立即同步' }}
              </el-button>
            </div>

            <div v-if="loadingMeetings && !meetings.length" class="retrieval-state retrieval-loading card">
              <div class="spinner" /><div class="state-title">加载会议列表…</div>
            </div>
            <div v-else-if="!meetings.length" class="retrieval-state card">
              <div class="state-icon">📅</div>
              <div class="state-title">还没有接收到会议</div>
              <div class="state-hint">用飞书开一场会（开启录制或 AI 总结），结束后点「立即同步」即可自动接收。</div>
            </div>
            <div v-else class="mt-meeting-list">
              <div
                v-for="m in meetings" :key="m.meeting_id"
                class="mt-meeting card" :class="`is-${m.analyze_status}`"
                @click="openMeeting(m)"
              >
                <div class="mt-meeting-icon">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m16 13 5.2-3.1a2 2 0 0 1 3 1.7v6.8a2 2 0 0 1-3 1.7L16 17"/><rect x="2" y="6" width="14" height="12" rx="2"/></svg>
                </div>
                <div class="mt-meeting-main">
                  <div class="mt-meeting-name" :title="m.topic">{{ m.topic }}</div>
                  <div class="mt-meeting-meta">
                    <span>{{ m.start_time_text }}</span>
                    <span v-if="m.todo_count" class="mt-chip is-todo">待办 {{ m.todo_count }}</span>
                  </div>
                </div>
                <span class="mt-tag" :class="`is-${m.analyze_status}`">{{ statusText(m.analyze_status) }}</span>
              </div>
            </div>
          </template>
        </section>

        <!-- 我的待办 -->
        <section v-else-if="tab === 'todos'" class="mt-panel">
          <!-- 待我确认（不确定是否属于我） -->
          <div class="mt-todo-group" v-if="todosByStatus.pending_confirm.length">
            <div class="mt-todo-group-title">
              待我确认
              <span class="mt-todo-group-hint">以下事项由会议识别，不确定是否属于你</span>
            </div>
            <div v-for="t in todosByStatus.pending_confirm" :key="t.todo_id" class="mt-todo card is-pending">
              <div class="mt-todo-main">
                <div class="mt-todo-content">{{ t.content }}</div>
                <div class="mt-todo-meta">
                  <span>来自「{{ t.meeting_topic || '会议' }}」</span>
                  <span v-if="t.assignee">指派：{{ t.assignee }}</span>
                  <span v-if="t.due_hint">原话：{{ t.due_hint }}</span>
                  <span v-if="t.reason" :title="t.reason">依据：{{ t.reason }}</span>
                </div>
              </div>
              <div class="mt-todo-actions">
                <el-button size="small" type="primary" :loading="acting === t.todo_id" @click.stop="actTodo(t, 'confirm')">加入待办</el-button>
                <el-button size="small" :loading="acting === t.todo_id" @click.stop="actTodo(t, 'reject')">不属于我</el-button>
              </div>
            </div>
          </div>

          <!-- 我的待办 -->
          <div class="mt-todo-group" v-if="todosByStatus.confirmed.length">
            <div class="mt-todo-group-title">我的待办<span class="mt-todo-group-hint">按截止时间排序，到期前自动提醒</span></div>
            <div v-for="t in todosByStatus.confirmed" :key="t.todo_id" class="mt-todo card">
              <div class="mt-todo-main">
                <div class="mt-todo-content">{{ t.content }}</div>
                <div class="mt-todo-meta">
                  <span>来自「{{ t.meeting_topic || '会议' }}」</span>
                  <span v-if="t.due_time" :class="{ 'is-overdue': isOverdue(t.due_time) }">⏰ 截止 {{ t.due_time }}</span>
                  <span v-else-if="t.due_hint">{{ t.due_hint }}</span>
                </div>
              </div>
              <div class="mt-todo-actions">
                <el-button size="small" type="success" plain :loading="acting === t.todo_id" @click.stop="actTodo(t, 'done')">完成</el-button>
              </div>
            </div>
          </div>

          <!-- 已完成 -->
          <details v-if="todosByStatus.done.length || todosByStatus.rejected.length" class="mt-todo-history card">
            <summary>已完成 {{ todosByStatus.done.length }} 项 · 已拒绝 {{ todosByStatus.rejected.length }} 项</summary>
            <div v-for="t in [...todosByStatus.done, ...todosByStatus.rejected]" :key="t.todo_id" class="mt-todo-row is-history">
              <span class="mt-todo-content">{{ t.content }}</span>
              <span class="mt-tag" :class="t.status === 'done' ? 'is-done' : 'is-empty'">
                {{ t.status === 'done' ? '已完成' : '已拒绝' }}
              </span>
            </div>
          </details>

          <div v-if="!todos.length" class="retrieval-state card">
            <div class="state-icon">✅</div>
            <div class="state-title">暂无会议待办</div>
            <div class="state-hint">接收并分析会议后，属于你的待办会出现在这里。</div>
          </div>
        </section>

        <!-- 接收设置 -->
        <section v-else class="mt-panel">
          <!-- 飞书账号 -->
          <div class="card mt-form-card">
            <div class="mt-form-title">
              飞书账号
              <span class="mt-form-hint">使用你自己的飞书自建应用，只接收你参与的会议</span>
            </div>
            <el-form label-position="top" class="mt-form">
              <div class="mt-form-grid">
                <el-form-item label="App ID" required>
                  <el-input v-model="accountForm.app_id" placeholder="cli_xxxxxxxxxxxxxxxx" />
                </el-form-item>
                <el-form-item label="App Secret" required>
                  <el-input v-model="accountForm.app_secret" type="password" show-password
                    :placeholder="accountForm.app_secret === '•••••' ? '已保存（留空保持不变）' : '应用凭证密钥'" />
                </el-form-item>
                <el-form-item label="我的 Open ID" required>
                  <el-input v-model="accountForm.open_id" placeholder="ou_xxxxxxxxxxxxxxxxxxxx" />
                </el-form-item>
                <el-form-item label="我的称呼（用于判定待办归属）">
                  <el-input v-model="accountForm.my_name" placeholder="如：小明 / 张总，会中提到的名字或称谓" />
                </el-form-item>
              </div>
              <div class="mt-form-row">
                <div class="mt-form-switch">
                  <span>启用自动接收</span>
                  <el-switch v-model="accountForm.enabled" />
                </div>
                <div class="mt-form-actions">
                  <el-popconfirm
                    v-if="account.configured"
                    title="确认删除飞书账号配置？删除后停止自动接收。"
                    confirm-button-text="删除" cancel-button-text="取消" width="240"
                    @confirm="removeAccount"
                  >
                    <template #reference><el-button text type="danger">删除配置</el-button></template>
                  </el-popconfirm>
                  <el-button type="primary" :loading="savingAccount" @click="saveAccount">保存并校验</el-button>
                </div>
              </div>
            </el-form>
            <el-alert type="info" :closable="false" class="mt-alert">
              <template #title>
                创建方法：飞书开放平台 → 创建「企业自建应用」→ 开通权限
                「获取会议信息（含智能纪要、逐字稿）」「获取会议录制信息」「导出妙记转写的文字内容」「查看云文档」→ 发布应用。
                Open ID 可在飞书开放平台「API 调试台」获取。
              </template>
            </el-alert>
          </div>

          <!-- 用户授权（user_access_token） -->
          <div class="card mt-form-card">
            <div class="mt-form-title">
              飞书用户授权
              <span class="mt-form-hint">搜索/获取「归属于本人」的会议必须授权一次</span>
            </div>
            <div class="mt-auth-status">
              <span class="mt-tag" :class="authorized ? 'is-done' : 'is-empty'">
                {{ authorized ? '✓ 已授权' : '✗ 未授权' }}
              </span>
              <span class="mt-form-hint" v-if="!authorized">
                未授权时同步将返回空（tenant 身份看不到你的会议）。
              </span>
            </div>
            <div class="mt-form-row">
              <span class="mt-form-hint">
                在飞书应用「安全设置 → 重定向 URL」登记：<code>{{ redirectUri }}</code>
              </span>
              <el-button type="primary" :loading="authorizing" :disabled="!account.configured" @click="startAuth">
                授权飞书账号
              </el-button>
            </div>
            <el-divider content-position="left">回调不成功？手动提交授权码</el-divider>
            <div class="mt-form-inline">
              <el-input v-model="manualCode" placeholder="粘贴授权后地址栏中的 code" />
              <el-button :loading="exchanging" @click="exchangeManual">提交授权码</el-button>
            </div>
          </div>

          <!-- 通知设置 -->
          <div class="card mt-form-card">
            <div class="mt-form-title">
              提醒通知
              <span class="mt-form-hint">应用内通知始终开启；可按需启用邮件与微信推送</span>
            </div>
            <el-form label-position="top" class="mt-form">
              <div class="mt-form-grid">
                <el-form-item label="邮件通知">
                  <div class="mt-form-inline">
                    <el-input v-model="notifyForm.email" placeholder="收件邮箱" :disabled="!notifyForm.email_enabled" />
                    <el-switch v-model="notifyForm.email_enabled" />
                  </div>
                  <div v-if="notifyForm.email_enabled && !smtpReady" class="mt-form-warn">
                    服务端未配置 SMTP（.env 中 SMTP_HOST 等），邮件暂不可用
                  </div>
                </el-form-item>
                <el-form-item label="微信通知（Server酱）">
                  <div class="mt-form-inline">
                    <el-input v-model="notifyForm.wechat_key" placeholder="SendKey，见 sct.ftqq.com" :disabled="!notifyForm.wechat_enabled" />
                    <el-switch v-model="notifyForm.wechat_enabled" />
                  </div>
                </el-form-item>
              </div>
              <div class="mt-form-row">
                <span class="mt-form-hint">待办截止前 30 分钟自动提醒；新会议接收完成也会通知。</span>
                <div class="mt-form-actions">
                  <el-button :loading="testing" @click="sendTest">发送测试通知</el-button>
                  <el-button type="primary" :loading="savingNotify" @click="saveNotify">保存</el-button>
                </div>
              </div>
            </el-form>
          </div>

          <!-- 会议知识库说明 -->
          <div class="card mt-form-card">
            <div class="mt-form-title">
              会议知识库
              <span class="mt-form-hint">会议正文独立存储，与个人知识库互不混杂</span>
            </div>
            <div class="mt-kb-row">
              <span>在「AI 办公搭子」对话框的「+」菜单中开启「会议检索」，智能体即可检索你的会议内容作答；关闭后不会读取任何会议数据。</span>
              <el-tag v-if="kbReady" type="success" effect="plain">知识库就绪</el-tag>
              <el-tag v-else type="info" effect="plain">嵌入未就绪（仅影响检索）</el-tag>
            </div>
          </div>
        </section>
      </template>
    </div>

    <!-- 会议详情抽屉 -->
    <el-drawer v-model="detail.visible" :title="detail.topic" size="52%" direction="rtl">
      <div v-if="detail.loading" class="retrieval-state retrieval-loading"><div class="spinner" /><div class="state-title">读取会议…</div></div>
      <div v-else-if="detail.error" class="retrieval-state is-error"><div class="state-icon">⚠</div><div class="state-hint">{{ detail.error }}</div></div>
      <template v-else>
        <div class="mt-detail-meta">
          <span>{{ detail.meeting_no ? `会议号 ${detail.meeting_no} · ` : '' }}{{ fmtTs(detail.start_time) }} ~ {{ fmtTs(detail.end_time, true) }}</span>
        </div>

        <template v-if="detail.analysis">
          <h4 class="mt-detail-title">摘要</h4>
          <p class="mt-detail-text">{{ detail.analysis.summary }}</p>

          <h4 v-if="detail.analysis.key_points?.length" class="mt-detail-title">关键要点</h4>
          <ul v-if="detail.analysis.key_points?.length" class="mt-detail-points">
            <li v-for="(p, i) in detail.analysis.key_points" :key="i">{{ p }}</li>
          </ul>

          <h4 v-if="detail.todos?.length" class="mt-detail-title">会议待办</h4>
          <div v-if="detail.todos?.length" class="mt-detail-todos">
            <div v-for="t in detail.todos" :key="t.todo_id" class="mt-detail-todo">
              <span class="mt-tag" :class="todoTagClass(t)">{{ todoTagText(t) }}</span>
              <span class="mt-todo-content">{{ t.content }}</span>
              <span v-if="t.due_time" class="mt-todo-due">{{ t.due_time }}</span>
            </div>
          </div>
        </template>
        <div v-else-if="detail.analyze_status === 'empty'" class="retrieval-state">
          <div class="state-icon">🎙</div>
          <div class="state-title">该会议没有妙记/智能纪要</div>
          <div class="state-hint">{{ detail.error || '在飞书中开启会议录制或 AI 总结后，重新同步可接收正文。' }}</div>
          <div class="state-hint">仍无正文？请在飞书开放平台确认应用已开通「获取智能纪要信息」「获取逐字稿信息」「获取会议录制信息」「导出妙记转写的文字内容」权限。</div>
        </div>
        <div v-else-if="detail.analyze_status === 'pending'" class="retrieval-state">
          <div class="spinner" /><div class="state-title">正文接收/分析中…</div>
          <div class="state-hint">妙记生成需要几分钟，可稍后点「立即同步」。</div>
        </div>
        <div v-else-if="detail.analyze_status === 'failed'" class="retrieval-state is-error">
          <div class="state-icon">⚠</div><div class="state-title">分析失败</div>
          <div class="state-hint">{{ detail.error || '请稍后重试同步' }}</div>
        </div>

        <template v-if="detail.content_text">
          <h4 class="mt-detail-title">会议正文</h4>
          <pre class="mt-detail-content">{{ detail.content_text }}</pre>
        </template>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/utils/request'
import meetingApi from '@/api/meetings'

const tab = ref('meetings')
const accountChecked = ref(false)

// ── 账号 ──
const account = ref({ configured: false })
const accountForm = reactive({ app_id: '', app_secret: '', open_id: '', my_name: '', enabled: true })
const savingAccount = ref(false)

// ── 会议 ──
const meetings = ref([])
const loadingMeetings = ref(false)
const syncing = ref(false)

// ── 待办 ──
const todos = ref([])
const acting = ref('')

// ── 通知设置 ──
const notifyForm = reactive({ email: '', email_enabled: false, wechat_key: '', wechat_enabled: false })
const savingNotify = ref(false)
const testing = ref(false)
const smtpReady = ref(false)

// ── 会议知识库 ──
const kbReady = ref(false)

// ── 用户授权（OAuth）──
const authorized = ref(false)
const redirectUri = ref('')
const authorizing = ref(false)
const manualCode = ref('')
const exchanging = ref(false)

const startAuth = async () => {
  authorizing.value = true
  try {
    const res = await meetingApi.getOAuthUrl()
    // 新窗口打开授权页；授权后飞书回调到 redirectUri 自动完成，或手动粘 code
    window.open(res.data.url, '_blank')
    redirectUri.value = res.data.redirect_uri
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '获取授权链接失败')
  } finally {
    authorizing.value = false
  }
}

const exchangeManual = async () => {
  if (!manualCode.value.trim()) { ElMessage.warning('请粘贴授权码 code'); return }
  exchanging.value = true
  try {
    await meetingApi.exchangeCode(manualCode.value.trim())
    authorized.value = true
    manualCode.value = ''
    ElMessage.success('授权成功，可立即同步会议')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '授权失败')
  } finally {
    exchanging.value = false
  }
}

// ── 详情抽屉 ──
const detail = ref({ visible: false, loading: false, error: '', topic: '' })

const activeTodos = computed(() => todos.value.filter((t) => t.status === 'confirmed').length)
const pendingTodos = computed(() => todos.value.filter((t) => t.status === 'pending_confirm').length)
const todosByStatus = computed(() => ({
  pending_confirm: todos.value.filter((t) => t.status === 'pending_confirm'),
  confirmed: todos.value.filter((t) => t.status === 'confirmed'),
  done: todos.value.filter((t) => t.status === 'done'),
  rejected: todos.value.filter((t) => t.status === 'rejected'),
}))

const syncIntervalText = '5 分钟'

const statusText = (s) => ({ pending: '待分析', processing: '分析中', done: '已分析', failed: '分析失败', empty: '无正文' }[s] || s)
const fmtTs = (ts, timeOnly = false) => ts
  ? new Date(ts * 1000).toLocaleString('zh-CN', timeOnly
    ? { hour: '2-digit', minute: '2-digit' }
    : { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  : '未知'
const isOverdue = (due) => due && new Date(due.replace(' ', 'T')) < new Date()
const todoTagClass = (t) => ({
  confirmed: 'is-done', done: 'is-done', pending_confirm: 'is-unsure', rejected: 'is-empty',
}[t.status] || 'is-unsure')
const todoTagText = (t) => ({
  confirmed: '我的待办', done: '已完成', pending_confirm: '待确认', rejected: '已拒绝',
}[t.status] || t.status)

// ── 数据加载 ──
const fetchAccount = async () => {
  try {
    const res = await meetingApi.getAccount()
    account.value = res.data
    authorized.value = !!res.data.authorized
    redirectUri.value = res.data.redirect_uri || ''
    if (res.data.configured) {
      const a = res.data.account
      // app_secret 已脱敏：编辑时留空表示保持不变
      Object.assign(accountForm, {
        app_id: a.app_id, app_secret: a.app_secret || '',
        open_id: a.open_id, my_name: a.my_name || '', enabled: a.enabled,
      })
    }
  } catch (e) {
    account.value = { configured: false }
  } finally {
    accountChecked.value = true
  }
}

const fetchMeetings = async () => {
  loadingMeetings.value = true
  try {
    const res = await meetingApi.listMeetings()
    meetings.value = res.data.meetings || []
  } catch { /* 静默 */ } finally { loadingMeetings.value = false }
}

const fetchTodos = async () => {
  try {
    const res = await meetingApi.listTodos()
    todos.value = res.data.todos || []
  } catch { /* 静默 */ }
}

const fetchNotify = async () => {
  try {
    const res = await meetingApi.getNotifySettings()
    Object.assign(notifyForm, {
      email: res.data.email || '', email_enabled: !!res.data.email_enabled,
      wechat_key: res.data.wechat_key || '', wechat_enabled: !!res.data.wechat_enabled,
    })
    smtpReady.value = !!res.data.smtp_ready
  } catch { /* 静默 */ }
}

// ── 同步 ──
const doSync = async () => {
  syncing.value = true
  try {
    const res = await meetingApi.sync()
    const { new: n, analyzed } = res.data
    ElMessage.success(`同步完成：新接收 ${n} 场，分析 ${analyzed} 场`)
    await Promise.all([fetchMeetings(), fetchTodos()])
    if (n || analyzed) fetchAccount()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '同步失败')
  } finally {
    syncing.value = false
  }
}

// ── 待办操作 ──
const actTodo = async (t, action) => {
  acting.value = t.todo_id
  try {
    await meetingApi.updateTodo(t.todo_id, action)
    t.status = { confirm: 'confirmed', reject: 'rejected', done: 'done', reopen: 'confirmed' }[action]
    ElMessage.success({ confirm: '已加入我的待办', reject: '已忽略', done: '已完成' }[action] || '已更新')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  } finally {
    acting.value = ''
  }
}

// ── 账号保存/删除 ──
const saveAccount = async () => {
  savingAccount.value = true
  try {
    const body = { ...accountForm }
    // 脱敏占位表示未修改，回传原值由后端保留（留空时后端校验会提示）
    if (body.app_secret === '•••••') body.app_secret = ''
    const res = await meetingApi.saveAccount(body)
    account.value = { configured: true, ...res.data.account }
    accountForm.app_secret = res.data.account.app_secret || ''
    ElMessage.success('飞书账号已保存，凭证校验通过')
    fetchAccount()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    savingAccount.value = false
  }
}

const removeAccount = async () => {
  try {
    await meetingApi.deleteAccount()
    account.value = { configured: false }
    Object.assign(accountForm, { app_id: '', app_secret: '', open_id: '', my_name: '', enabled: true })
    meetings.value = []
    ElMessage.success('已删除飞书账号配置')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

// ── 通知设置 ──
const saveNotify = async () => {
  savingNotify.value = true
  try {
    await meetingApi.saveNotifySettings({ ...notifyForm })
    ElMessage.success('通知设置已保存')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    savingNotify.value = false
  }
}

const sendTest = async () => {
  testing.value = true
  try {
    await meetingApi.sendTestNotification()
    ElMessage.success('测试通知已发送，请查看应用内通知铃铛与已启用的外部渠道')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '发送失败')
  } finally {
    testing.value = false
  }
}

// ── 会议详情 ──
const openMeeting = async (m) => {
  detail.value = { visible: true, loading: true, error: '', topic: m.topic }
  try {
    const res = await meetingApi.getMeeting(m.meeting_id)
    detail.value = { ...detail.value, ...res.data, loading: false }
  } catch (e) {
    detail.value = { ...detail.value, loading: false, error: e?.response?.data?.detail || '读取失败' }
  }
}

// ── 初始化 ──
onMounted(async () => {
  await fetchAccount()
  if (account.value.configured) {
    await Promise.all([fetchMeetings(), fetchTodos(), fetchNotify()])
    try {
      const res = await request.get('/health', { serverName: 'agent' })
      kbReady.value = !!res.data?.meeting_kb_ready
    } catch { /* 静默 */ }
  }
})
</script>

<style scoped>
.mt-btn { margin-top: 14px; }

/* 统计 */
.mt-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-md);
  margin-bottom: var(--space-md);
}
.mt-stat { padding: var(--space-md) var(--space-lg); text-align: center; }
.mt-stat-num { font-size: 24px; font-weight: 700; color: var(--accent); }
.mt-stat-num.small { font-size: 15px; }
.mt-stat-label { font-size: 12px; color: var(--slate); margin-top: 2px; }

/* 标签 */
.mt-tabs { display: flex; gap: 4px; padding: 6px; margin-bottom: var(--space-md); }
.mt-tab {
  position: relative;
  display: inline-flex; align-items: center; gap: 8px;
  padding: 8px 16px; border: none; background: transparent;
  border-radius: var(--radius-sm); color: var(--slate);
  font-size: 14px; cursor: pointer; transition: all var(--transition);
}
.mt-tab svg { width: 16px; height: 16px; }
.mt-tab:hover { background: var(--mist-light); color: var(--ink); }
.mt-tab.active { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
.mt-tab-badge {
  min-width: 18px; height: 18px; padding: 0 5px;
  border-radius: 9px; background: var(--danger); color: #fff;
  font-size: 11px; font-weight: 600;
  display: inline-flex; align-items: center; justify-content: center;
}

/* 工具栏 */
.mt-toolbar { display: flex; align-items: center; justify-content: space-between; gap: var(--space-md); padding: var(--space-md) var(--space-lg); margin-bottom: var(--space-md); }
.mt-toolbar-hint { font-size: 13px; color: var(--slate); }

/* 会议列表 */
.mt-meeting-list { display: flex; flex-direction: column; gap: 10px; }
.mt-meeting {
  display: flex; align-items: center; gap: var(--space-md);
  padding: var(--space-md) var(--space-lg);
  cursor: pointer; transition: box-shadow var(--transition), transform var(--transition);
}
.mt-meeting:hover { box-shadow: var(--shadow-md); transform: translateY(-1px); }
.mt-meeting.is-pending, .mt-meeting.is-processing { border-left: 3px solid var(--warning); }
.mt-meeting.is-failed { border-left: 3px solid var(--danger); }
.mt-meeting.is-empty { border-left: 3px solid var(--slate-light); }
.mt-meeting-icon {
  flex-shrink: 0; width: 40px; height: 40px; border-radius: 50%;
  background: var(--accent-soft); color: var(--accent);
  display: flex; align-items: center; justify-content: center;
}
.mt-meeting-icon svg { width: 20px; height: 20px; }
.mt-meeting-main { flex: 1; min-width: 0; }
.mt-meeting-name { font-size: 14px; font-weight: 600; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mt-meeting-meta { display: flex; gap: 10px; margin-top: 4px; font-size: 12px; color: var(--slate); align-items: center; }
.mt-chip { padding: 1px 8px; border-radius: 10px; background: var(--mist-light); color: var(--slate); }
.mt-chip.is-todo { background: var(--accent-soft); color: var(--accent); }

.mt-tag { flex-shrink: 0; font-size: 11px; padding: 3px 10px; border-radius: 10px; font-weight: 500; }
.mt-tag.is-done { color: var(--success); background: var(--success-soft); }
.mt-tag.is-unsure { color: var(--warning); background: var(--warning-soft); }
.mt-tag.is-empty { color: var(--slate); background: var(--mist-light); }
.mt-tag.is-pending, .mt-tag.is-processing { color: var(--warning); background: var(--warning-soft); }
.mt-tag.is-failed { color: var(--danger); background: var(--danger-soft); }

/* 待办 */
.mt-todo-group { margin-bottom: var(--space-lg); }
.mt-todo-group-title {
  display: flex; align-items: baseline; gap: 10px;
  font-size: 14px; font-weight: 600; color: var(--ink);
  margin-bottom: 10px;
}
.mt-todo-group-hint { font-size: 12px; font-weight: 400; color: var(--slate); }
.mt-todo {
  display: flex; align-items: center; gap: var(--space-md);
  padding: var(--space-md) var(--space-lg); margin-bottom: 8px;
  transition: box-shadow var(--transition);
}
.mt-todo.is-pending { border-left: 3px solid var(--warning); }
.mt-todo:hover { box-shadow: var(--shadow-md); }
.mt-todo-main { flex: 1; min-width: 0; }
.mt-todo-content { font-size: 14px; color: var(--ink); font-weight: 500; }
.mt-todo-meta {
  display: flex; flex-wrap: wrap; gap: 4px 12px;
  margin-top: 4px; font-size: 12px; color: var(--slate);
}
.mt-todo-meta .is-overdue { color: var(--danger); font-weight: 600; }
.mt-todo-actions { display: flex; gap: 6px; flex-shrink: 0; }

.mt-todo-history summary {
  cursor: pointer; padding: var(--space-md) var(--space-lg);
  font-size: 13px; color: var(--slate); user-select: none;
}
.mt-todo-row {
  display: flex; align-items: center; gap: 10px;
  padding: 8px var(--space-lg); font-size: 13px;
  border-top: 1px solid var(--mist);
}
.mt-todo-row.is-history .mt-todo-content { color: var(--slate); text-decoration: line-through; }

/* 表单 */
.mt-form-card { padding: var(--space-lg); margin-bottom: var(--space-md); }
.mt-form-title {
  display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap;
  font-size: 15px; font-weight: 700; color: var(--ink);
  margin-bottom: var(--space-md);
}
.mt-form-hint { font-size: 12px; font-weight: 400; color: var(--slate); }
.mt-form-grid {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 0 var(--space-lg);
}
.mt-form-grid :deep(.el-form-item__label) { font-size: 13px; color: var(--ink-soft); }
.mt-form-inline { display: flex; align-items: center; gap: 10px; width: 100%; }
.mt-form-inline .el-input { flex: 1; }
.mt-form-warn { font-size: 12px; color: var(--warning); margin-top: 4px; line-height: 1.5; }
.mt-form-row {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--space-md); flex-wrap: wrap;
}
.mt-form-switch { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--ink-soft); }
.mt-form-actions { display: flex; gap: 8px; }
.mt-alert { margin-top: var(--space-md); }
.mt-kb-row {
  display: flex; align-items: center; justify-content: space-between; gap: var(--space-md);
  font-size: 13px; color: var(--ink-soft); line-height: 1.7;
}
.mt-auth-status {
  display: flex; align-items: center; gap: 10px; margin-bottom: var(--space-md);
}
.mt-auth-status .mt-tag { font-size: 12px; padding: 4px 12px; }
.mt-form-hint code {
  background: var(--mist-light); padding: 1px 6px; border-radius: 4px;
  font-family: var(--font-mono); font-size: 12px; word-break: break-all;
}

/* 详情抽屉 */
.mt-detail-meta { font-size: 12px; color: var(--slate); margin-bottom: var(--space-md); }
.mt-detail-title {
  font-size: 13px; font-weight: 700; color: var(--accent);
  margin: var(--space-lg) 0 8px;
}
.mt-detail-text { font-size: 13px; line-height: 1.8; color: var(--ink-soft); margin: 0; }
.mt-detail-points { margin: 0; padding-left: 18px; }
.mt-detail-points li { font-size: 13px; line-height: 1.9; color: var(--ink-soft); }
.mt-detail-todos { display: flex; flex-direction: column; gap: 8px; }
.mt-detail-todo { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.mt-detail-todo .mt-todo-content { font-weight: 400; }
.mt-todo-due { margin-left: auto; flex-shrink: 0; font-size: 12px; color: var(--slate); }
.mt-detail-content {
  white-space: pre-wrap; word-break: break-word;
  font-family: var(--font-sans); font-size: 13px; line-height: 1.7;
  color: var(--ink-soft); margin: 0;
  max-height: 400px; overflow-y: auto;
  background: var(--mist-light); border-radius: var(--radius-sm);
  padding: var(--space-md);
}

@media (max-width: 960px) {
  .mt-stats { grid-template-columns: repeat(2, 1fr); }
  .mt-form-grid { grid-template-columns: 1fr; }
  .mt-toolbar { flex-wrap: wrap; }
}
</style>

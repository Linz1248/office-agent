<template>
  <div class="app-layout" v-if="showSidebar">
    <!-- 侧边栏 -->
    <aside class="sidebar" :class="{ collapsed: isCollapsed }">
      <!-- 品牌 -->
      <div class="sidebar-brand" @click="goHome">
        <div class="brand-mark">
          <svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="32" height="32" rx="8" fill="#2563EB"/>
            <path d="M10 8.5C10 7.67 10.67 7 11.5 7H18l4 4v12.5c0 .83-.67 1.5-1.5 1.5h-9c-.83 0-1.5-.67-1.5-1.5V8.5Z" fill="white" fill-opacity="0.9"/>
            <path d="M18 7v4h4" stroke="#2563EB" stroke-width="1.5" stroke-linejoin="round" fill="white"/>
            <line x1="13" y1="15" x2="19" y2="15" stroke="#93C5FD" stroke-width="1.5" stroke-linecap="round"/>
            <line x1="13" y1="18" x2="17" y2="18" stroke="#93C5FD" stroke-width="1.5" stroke-linecap="round"/>
            <path d="M22.5 6.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z" fill="#FDE047"/>
          </svg>
        </div>
        <span v-show="!isCollapsed" class="brand-text">智能办公平台</span>
      </div>

      <!-- 导航 -->
      <nav class="sidebar-nav">
        <router-link to="/agent" class="nav-item nav-item--accent" :class="{ active: $route.path === '/agent' }">
          <el-tooltip :content="isCollapsed ? 'AI 办公搭子' : ''" placement="right" :disabled="!isCollapsed">
            <div class="nav-item-inner">
              <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/></svg>
              <span v-show="!isCollapsed" class="nav-label">AI 办公搭子</span>
            </div>
          </el-tooltip>
        </router-link>

        <div class="nav-group" v-show="!isCollapsed">
          <span class="nav-group-label">文档工具</span>
        </div>
        <router-link to="/home" class="nav-item" :class="{ active: $route.path === '/home' }">
          <el-tooltip :content="isCollapsed ? '文档抽取' : ''" placement="right" :disabled="!isCollapsed">
            <div class="nav-item-inner">
              <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="16" y2="17"/></svg>
              <span v-show="!isCollapsed" class="nav-label">文档抽取</span>
            </div>
          </el-tooltip>
        </router-link>
        <router-link to="/document_compare" class="nav-item" :class="{ active: $route.path === '/document_compare' }">
          <el-tooltip :content="isCollapsed ? '文档比对' : ''" placement="right" :disabled="!isCollapsed">
            <div class="nav-item-inner">
              <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16 3h5v5"/><path d="M8 3H3v5"/><path d="M21 3l-7 7"/><path d="M3 3l7 7"/><path d="M16 21h5v-5"/><path d="M8 21H3v-5"/><path d="M21 21l-7-7"/><path d="M3 21l7-7"/></svg>
              <span v-show="!isCollapsed" class="nav-label">文档比对</span>
            </div>
          </el-tooltip>
        </router-link>

        <div class="nav-group" v-show="!isCollapsed">
          <span class="nav-group-label">图像检索</span>
        </div>
        <router-link to="/build_image_library" class="nav-item" :class="{ active: $route.path === '/build_image_library' }">
          <el-tooltip :content="isCollapsed ? '构建图像索引' : ''" placement="right" :disabled="!isCollapsed">
            <div class="nav-item-inner">
              <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/></svg>
              <span v-show="!isCollapsed" class="nav-label">构建索引库</span>
            </div>
          </el-tooltip>
        </router-link>
        <router-link to="/image_search_image" class="nav-item" :class="{ active: $route.path === '/image_search_image' }">
          <el-tooltip :content="isCollapsed ? '图搜图' : ''" placement="right" :disabled="!isCollapsed">
            <div class="nav-item-inner">
              <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/></svg>
              <span v-show="!isCollapsed" class="nav-label">图搜图</span>
            </div>
          </el-tooltip>
        </router-link>
        <router-link to="/text_search_image" class="nav-item" :class="{ active: $route.path === '/text_search_image' }">
          <el-tooltip :content="isCollapsed ? '文搜图' : ''" placement="right" :disabled="!isCollapsed">
            <div class="nav-item-inner">
              <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/><line x1="8" y1="11" x2="14" y2="11"/></svg>
              <span v-show="!isCollapsed" class="nav-label">文搜图</span>
            </div>
          </el-tooltip>
        </router-link>

        <div class="nav-group" v-show="!isCollapsed">
          <span class="nav-group-label">音频检索</span>
        </div>
        <router-link to="/build_audio_library" class="nav-item" :class="{ active: $route.path === '/build_audio_library' }">
          <el-tooltip :content="isCollapsed ? '构建音频索引' : ''" placement="right" :disabled="!isCollapsed">
            <div class="nav-item-inner">
              <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/></svg>
              <span v-show="!isCollapsed" class="nav-label">构建索引库</span>
            </div>
          </el-tooltip>
        </router-link>
        <router-link to="/text_search_audio" class="nav-item" :class="{ active: $route.path === '/text_search_audio' }">
          <el-tooltip :content="isCollapsed ? '文本搜音频' : ''" placement="right" :disabled="!isCollapsed">
            <div class="nav-item-inner">
              <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
              <span v-show="!isCollapsed" class="nav-label">文本搜音频</span>
            </div>
          </el-tooltip>
        </router-link>
      </nav>

      <!-- 用户区 -->
      <div class="sidebar-footer">
        <el-dropdown trigger="click" placement="top-start">
          <div class="user-chip">
            <div class="user-avatar">{{ username.charAt(0).toUpperCase() }}</div>
            <div v-show="!isCollapsed" class="user-info">
              <span class="user-name">{{ username }}</span>
            </div>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="dialogFormVisible = true">
                修改密码
              </el-dropdown-item>
              <el-dropdown-item divided @click="logout">
                退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>

      <!-- 侧边栏收起/展开按钮 -->
      <button class="sidebar-toggle" @click="toggleCollapse" :title="isCollapsed ? '展开侧边栏' : '收起侧边栏'">
        <svg viewBox="0 0 16 16" fill="none"><path d="M9 12L5 8l4-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M12 12L8 8l4-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>
    </aside>

    <!-- 主内容区 -->
    <main class="main-content">
      <router-view />
    </main>
  </div>

  <!-- 登录/注册页面无侧边栏 -->
  <router-view v-else />

  <!-- 修改密码弹窗 -->
  <el-dialog v-model="dialogFormVisible" title="修改密码" width="460px" class="change-password-dialog">
    <el-form :model="form" :rules="rules" ref="formRef" label-width="80px">
      <el-form-item prop="old_password" label="原密码">
        <el-input v-model="form.old_password" type="password" show-password placeholder="请输入原密码" />
      </el-form-item>
      <el-form-item prop="new_password" label="新密码">
        <el-input v-model="form.new_password" type="password" show-password placeholder="请输入新密码" />
      </el-form-item>
      <el-form-item prop="confirm_password" label="确认密码">
        <el-input v-model="form.confirm_password" type="password" show-password placeholder="请再次输入新密码" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogFormVisible = false">取消</el-button>
      <el-button type="primary" @click="change_password">确认修改</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import router from '@/router'
import request from '@/utils/request'
import { ElMessage } from 'element-plus'

const store = useUserStore()
const route = useRoute()

const username = computed(() => store.loginInfo.user?.username || '用户')

// 登录/注册页面不显示侧边栏
const showSidebar = computed(() => {
  const p = route.path
  return p !== '/login' && p !== '/register'
})

// 侧边栏折叠
const isCollapsed = ref(false)
const toggleCollapse = () => {
  isCollapsed.value = !isCollapsed.value
}

// 点击品牌区跳转首页
const goHome = () => {
  router.push('/agent')
}

// --- 修改密码 ---
const dialogFormVisible = ref(false)
const formRef = ref()
const user = store.getUser
const form = reactive({
  username: user.username,
  old_password: '',
  new_password: '',
  confirm_password: ''
})

const validateConfirmPassword = (rule, value, callback) => {
  if (value !== form.new_password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const rules = {
  old_password: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  new_password: [{ required: true, message: '请输入新密码', trigger: 'blur' }],
  confirm_password: [
    { required: true, message: '请确认新密码', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: 'blur' }
  ]
}

const change_password = () => {
  if (!formRef.value) return
  formRef.value.validate(valid => {
    if (valid) {
      request.post('/change_password', form, { serverName: 'docExtract' }).then(res => {
        if (res.status === 200) {
          ElMessage.success('修改成功')
          store.clearLoginInfo()
          dialogFormVisible.value = false
          router.push('/login')
        } else {
          ElMessage.error('修改失败')
        }
      }).catch(e => {
        ElMessage.error(e.response.data.detail)
      })
    }
  })
}

const logout = () => {
  store.clearLoginInfo()
  router.push('/login')
}
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* --- 侧边栏 --- */
.sidebar {
  flex-shrink: 0;
  width: var(--sidebar-width);
  background: var(--sidebar-bg);
  display: flex;
  flex-direction: column;
  transition: width var(--transition);
  z-index: 100;
  position: relative;
}

.sidebar.collapsed {
  width: var(--sidebar-collapsed-width);
}

/* 品牌 */
.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px 20px;
  cursor: pointer;
  border-bottom: 1px solid var(--sidebar-border);
}

.brand-mark {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
}

.brand-mark svg {
  width: 100%;
  height: 100%;
}

.brand-text {
  color: var(--sidebar-text-hover);
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.02em;
  white-space: nowrap;
}

/* 导航 */
.sidebar-nav {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px 0;
}

.sidebar-nav::-webkit-scrollbar {
  width: 3px;
}

.sidebar-nav::-webkit-scrollbar-thumb {
  background: var(--sidebar-scrollbar);
}

.nav-group {
  padding: 16px 20px 6px;
}

.nav-group-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--sidebar-group);
}

.nav-item {
  display: block;
  padding: 0 12px;
  margin: 2px 8px;
  border-radius: var(--radius-sm);
  transition: background var(--transition);
}

.nav-item-inner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 8px;
  color: var(--sidebar-text);
  transition: color var(--transition), background var(--transition);
  border-radius: var(--radius-sm);
}

.nav-icon {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
}

.nav-label {
  font-size: 14px;
  white-space: nowrap;
}

.nav-item:hover .nav-item-inner {
  color: var(--sidebar-text-hover);
  background: var(--sidebar-hover);
}

.nav-item.active .nav-item-inner {
  color: var(--sidebar-text-active);
  background: var(--sidebar-active-bg);
}

.nav-item--accent .nav-item-inner {
  color: #93C5FD;
}

.nav-item--accent:hover .nav-item-inner {
  color: #BFDBFE;
}

.nav-item--accent.active .nav-item-inner {
  background: var(--sidebar-active-bg);
  color: var(--sidebar-text-active);
}

/* 折叠态 */
.sidebar.collapsed .nav-item {
  margin: 2px 8px;
}

.sidebar.collapsed .nav-item-inner {
  justify-content: center;
  padding: 10px;
}

/* 用户区 */
.sidebar-footer {
  padding: 12px;
  border-top: 1px solid var(--sidebar-border);
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--transition);
}

.user-chip:hover {
  background: var(--sidebar-hover);
}

.user-avatar {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.user-info {
  flex: 1;
  overflow: hidden;
}

.user-name {
  color: var(--sidebar-text-hover);
  font-size: 14px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sidebar.collapsed .user-chip {
  justify-content: center;
  padding: 4px;
}

/* --- 侧边栏收起/展开按钮 --- */
.sidebar-toggle {
  position: absolute;
  bottom: 72px;
  right: -12px;
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: 1px solid var(--mist);
  border-radius: 50%;
  background: var(--surface);
  color: var(--slate);
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: all 0.2s ease;
}

.sidebar-toggle svg {
  width: 14px;
  height: 14px;
  transition: transform 0.2s ease;
}

.sidebar-toggle:hover {
  color: var(--accent);
  border-color: var(--accent);
}

.sidebar.collapsed .sidebar-toggle svg {
  transform: rotate(180deg);
}

/* --- 主内容区 --- */
.main-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  background: var(--paper);
}

/* --- 弹窗 --- */
.change-password-dialog :deep(.el-dialog__body) {
  padding: 24px 24px 0;
}
</style>

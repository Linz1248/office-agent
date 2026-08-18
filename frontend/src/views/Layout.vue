<template>
  <div class="app-layout" v-if="showSidebar">
    <!-- 侧边栏 -->
    <aside class="sidebar" :class="{ collapsed: isCollapsed }">
      <!-- 品牌区 -->
      <div class="sidebar-brand" @click="goHome">
        <BrandLogo :size="34" class="brand-mark" />
        <div v-show="!isCollapsed" class="brand-text">
          <span class="brand-name">慧办</span>
          <span class="brand-slogan">AI 智慧办公平台</span>
        </div>
      </div>

      <!-- 导航 -->
      <nav class="sidebar-nav">
        <!-- AI 办公搭子（始终置顶、渐变突出） -->
        <el-tooltip content="AI 办公搭子" placement="right" :disabled="!isCollapsed">
          <router-link to="/agent" class="nav-item nav-item--accent" :class="{ active: $route.path === '/agent' }">
            <div class="nav-item-inner">
              <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" v-html="ICONS.agent"></svg>
              <span v-show="!isCollapsed" class="nav-label">AI 办公搭子</span>
            </div>
          </router-link>
        </el-tooltip>

        <!-- 可折叠分组 -->
        <div v-for="group in menuGroups" :key="group.label" class="nav-section">
          <!-- 展开态：分组头（图标 + 标题 + 箭头） -->
          <div v-show="!isCollapsed" class="nav-section-head" @click="toggleGroup(group.label)">
            <div class="nav-section-title">
              <svg class="nav-section-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" v-html="group.icon"></svg>
              <span class="nav-section-label">{{ group.label }}</span>
            </div>
            <svg class="nav-section-chevron" :class="{ expanded: expandedGroups.has(group.label) }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
          </div>

          <!-- 展开态子项（纯文本，无图标） -->
          <div v-show="!isCollapsed && expandedGroups.has(group.label)" class="nav-section-items">
            <router-link
              v-for="item in group.items"
              :key="item.path"
              :to="item.path"
              class="nav-item"
              :class="{ active: $route.path === item.path }"
            >
              <div class="nav-item-inner">
                <span class="nav-label">{{ item.label }}</span>
              </div>
            </router-link>
          </div>

          <!-- 折叠态：一级菜单分组图标（单项直达，多项悬浮弹出二级菜单） -->
          <el-tooltip
            v-if="isCollapsed && group.items.length === 1"
            :content="group.items[0].label"
            placement="right"
          >
            <router-link
              :to="group.items[0].path"
              class="nav-collapsed-group"
              :class="{ active: $route.path === group.items[0].path }"
            >
              <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" v-html="group.icon"></svg>
            </router-link>
          </el-tooltip>
          <el-popover
            v-else-if="isCollapsed"
            placement="right-start"
            trigger="hover"
            :width="172"
            :show-after="120"
            :hide-after="150"
            popper-class="nav-flyout-popper"
          >
            <template #reference>
              <div class="nav-collapsed-group" :class="{ active: group.items.some((i) => $route.path === i.path) }">
                <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" v-html="group.icon"></svg>
              </div>
            </template>
            <div class="nav-flyout">
              <div class="nav-flyout-title">{{ group.label }}</div>
              <router-link
                v-for="item in group.items"
                :key="item.path"
                :to="item.path"
                class="nav-flyout-item"
                :class="{ active: $route.path === item.path }"
              >{{ item.label }}</router-link>
            </div>
          </el-popover>
        </div>
      </nav>

      <!-- 用户区 -->
      <div class="sidebar-footer">
        <el-dropdown trigger="click" placement="top-start">
          <div class="user-chip">
            <div class="user-avatar">{{ username.charAt(0).toUpperCase() }}</div>
            <span v-show="!isCollapsed" class="user-name">{{ username }}</span>
            <svg v-show="!isCollapsed" class="user-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"/></svg>
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
      <!-- 主题切换浮动按钮 -->
      <div class="theme-fab">
        <ThemeToggle />
      </div>
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
import { computed, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import router from '@/router'
import request from '@/utils/request'
import { ElMessage } from 'element-plus'
import BrandLogo from '@/components/BrandLogo.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'

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

// ── 菜单图标（统一在此定义，重复图标直接复用） ──
const ICONS = {
  agent: '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>',
  fileText: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="16" y2="17"/>',
  compare: '<path d="M15 3h6v6"/><path d="M9 21H3v-6"/><path d="M21 3l-7.5 7.5"/><path d="M3 21l7.5-7.5"/>',
  folder: '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/>',
  imageSearch: '<rect x="3" y="3" width="14" height="14" rx="2"/><circle cx="7.5" cy="7.5" r="1.5"/><path d="m17 13-4-4-8 8"/><circle cx="17.5" cy="17.5" r="3"/><path d="m22 22-2-2"/>',
  textSearchImage: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/><path d="M8.5 12.5 10.5 10l3 3.5"/><circle cx="13.2" cy="9.4" r="0.5" fill="currentColor"/>',
  audioLibrary: '<path d="m16 6 4 14"/><path d="M12 6v14"/><path d="M8 8v12"/><path d="M4 4v16"/>',
  music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
  book: '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
  zap: '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
  market: '<path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/>',
  // ── 一级菜单（分组）图标 ──
  files: '<path d="M15 2H9a2 2 0 0 0-2 2v4a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2Z"/><path d="M7 8H5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.5-3.5a2 2 0 0 0-2.8 0L6 21"/>',
  audio: '<path d="M2 10v4"/><path d="M6 6v12"/><path d="M10 4v16"/><path d="M14 8v8"/><path d="M18 5v14"/><path d="M22 9v6"/>',
  blocks: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
}

// ── 多级菜单分组定义 ──
const menuGroups = [
  {
    label: '文档工具', icon: ICONS.files,
    items: [
      { path: '/home', label: '文档抽取', icon: ICONS.fileText },
      { path: '/document_compare', label: '文档比对', icon: ICONS.compare },
    ],
  },
  {
    label: '图像检索', icon: ICONS.image,
    items: [
      { path: '/build_image_library', label: '图像库', icon: ICONS.folder },
      { path: '/image_search_image', label: '图搜图', icon: ICONS.imageSearch },
      { path: '/text_search_image', label: '文搜图', icon: ICONS.textSearchImage },
    ],
  },
  {
    label: '音频检索', icon: ICONS.audio,
    items: [
      { path: '/build_audio_library', label: '音频库', icon: ICONS.audioLibrary },
      { path: '/text_search_audio', label: '文本搜音频', icon: ICONS.music },
    ],
  },
  {
    label: '知识库', icon: ICONS.book,
    items: [
      { path: '/knowledge_base', label: '个人知识库', icon: ICONS.book },
    ],
  },
  {
    label: 'Skill 系统', icon: ICONS.blocks,
    items: [
      { path: '/my_skills', label: '我的技能', icon: ICONS.zap },
      { path: '/skill_market', label: '技能市场', icon: ICONS.market },
    ],
  },
]

// 路由路径 → 分组标题 的映射，用于路由变化时自动展开对应分组
const groupOfPath = new Map(menuGroups.flatMap(g => g.items.map(i => [i.path, g.label])))

// ── 分组展开/收起状态（reactive Set，增删自动触发视图更新） ──
const expandedGroups = reactive(new Set())

const toggleGroup = (label) => {
  expandedGroups.has(label) ? expandedGroups.delete(label) : expandedGroups.add(label)
}

watch(() => route.path, (newPath) => {
  const label = groupOfPath.get(newPath)
  if (label) expandedGroups.add(label)
}, { immediate: true })

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
  background:
    radial-gradient(120% 55% at 0% 0%, rgba(37, 99, 235, 0.20) 0%, transparent 55%),
    radial-gradient(90% 50% at 100% 100%, rgba(59, 130, 246, 0.10) 0%, transparent 60%),
    var(--sidebar-bg);
  border-right: 1px solid var(--sidebar-border);
  display: flex;
  flex-direction: column;
  transition: width var(--transition);
  z-index: 100;
  position: relative;
}

.sidebar.collapsed {
  width: var(--sidebar-collapsed-width);
}

/* 品牌区 */
.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 12px 10px 2px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--transition);
}

.sidebar-brand:hover {
  background: var(--sidebar-hover);
}

.brand-mark {
  flex-shrink: 0;
  width: 34px;
  height: 34px;
  border-radius: 9px;
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
  min-width: 0;
}

.brand-name {
  color: #FFFFFF;
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.04em;
  white-space: nowrap;
}

.brand-slogan {
  color: var(--sidebar-group);
  font-size: 11px;
  white-space: nowrap;
}

.sidebar.collapsed .sidebar-brand {
  justify-content: center;
  margin: 12px 8px 2px;
  padding: 6px;
}

/* 导航 */
.sidebar-nav {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 6px 0 12px;
}

.sidebar-nav::-webkit-scrollbar {
  width: 3px;
}

.sidebar-nav::-webkit-scrollbar-thumb {
  background: var(--sidebar-scrollbar);
  border-radius: 3px;
}

/* 可折叠分组 */
.nav-section {
  margin-top: 6px;
}

.nav-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin: 2px 10px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  cursor: pointer;
  user-select: none;
  color: var(--sidebar-text);
  transition: color var(--transition), background var(--transition);
}

.nav-section-head:hover {
  color: var(--sidebar-text-hover);
  background: var(--sidebar-hover);
}

.nav-section-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.nav-section-icon {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  opacity: 0.9;
}

.nav-section-label {
  font-size: 14px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nav-section-chevron {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  transition: transform 0.2s ease;
}

.nav-section-chevron.expanded {
  transform: rotate(90deg);
}

.nav-section-items {
  display: flex;
  flex-direction: column;
}

/* 子菜单缩进，对齐到分组标题文字下方 */
.nav-section-items .nav-item {
  margin-left: 38px;
}

/* 菜单项 */
.nav-item {
  display: block;
  margin: 2px 10px;
  border-radius: var(--radius-md);
}

.nav-item-inner {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 10px;
  color: var(--sidebar-text);
  border-radius: var(--radius-md);
  transition: color var(--transition), background var(--transition), box-shadow var(--transition);
}

/* 激活态左侧指示条 */
.nav-item-inner::before {
  content: "";
  position: absolute;
  left: -10px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 16px;
  border-radius: 0 3px 3px 0;
  background: var(--sidebar-indicator);
  opacity: 0;
  transition: opacity var(--transition);
}

.nav-item:hover .nav-item-inner {
  color: var(--sidebar-text-hover);
  background: var(--sidebar-hover);
}

.nav-item.active .nav-item-inner {
  color: var(--sidebar-text-active);
  background: linear-gradient(90deg, rgba(37, 99, 235, 0.95), rgba(37, 99, 235, 0.55));
  box-shadow: 0 2px 8px rgba(2, 6, 23, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

.nav-item.active .nav-item-inner::before {
  opacity: 1;
}

.nav-icon {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
}

/* 折叠态：一级菜单分组图标按钮 */
.nav-collapsed-group {
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 2px 10px;
  padding: 10px;
  border-radius: var(--radius-md);
  color: var(--sidebar-text);
  cursor: pointer;
  text-decoration: none;
  transition: color var(--transition), background var(--transition);
}

.nav-collapsed-group:hover {
  color: var(--sidebar-text-hover);
  background: var(--sidebar-hover);
}

.nav-collapsed-group.active {
  color: var(--sidebar-text-active);
  background: var(--sidebar-active-bg);
}

.nav-label {
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 置顶强调项：默认浅蓝弱强调，仅激活时才显示渐变胶囊 */
.nav-item--accent {
  margin-top: 4px;
  margin-bottom: 6px;
}

.nav-item--accent .nav-item-inner {
  color: var(--sidebar-accent-text);
}

.nav-item--accent .nav-item-inner::before {
  display: none;
}

.nav-item--accent:hover .nav-item-inner {
  color: var(--sidebar-accent-text-hover);
  background: var(--sidebar-hover);
}

.nav-item--accent.active .nav-item-inner {
  color: var(--sidebar-text-active);
  background: var(--sidebar-accent-grad);
  box-shadow: 0 4px 14px rgba(37, 99, 235, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.18);
}

/* 折叠态：仅图标居中 */
.sidebar.collapsed .nav-item-inner {
  justify-content: center;
  padding: 10px;
}

.sidebar.collapsed .nav-section {
  margin-top: 8px;
}

/* 用户区 */
.sidebar-footer {
  padding: 10px;
  border-top: 1px solid var(--sidebar-border);
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 9px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--transition);
}

.user-chip:hover {
  background: var(--sidebar-hover);
}

.user-avatar {
  flex-shrink: 0;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: linear-gradient(135deg, #60A5FA, #2563EB);
  box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.18);
  color: #FFFFFF;
  font-size: 14px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.user-name {
  flex: 1;
  min-width: 0;
  color: var(--sidebar-text-hover);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-chevron {
  flex-shrink: 0;
  width: 13px;
  height: 13px;
  color: var(--sidebar-group);
}

.sidebar.collapsed .user-chip {
  justify-content: center;
  padding: 5px;
}

/* --- 主题切换浮动按钮 --- */
.theme-fab {
  position: absolute;
  top: 16px;
  right: 24px;
  z-index: 50;
}

/* --- 侧边栏收起/展开按钮 --- */
.sidebar-toggle {
  position: absolute;
  bottom: 78px;
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
  box-shadow: var(--shadow-md);
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
  position: relative;
}

/* --- 弹窗 --- */
.change-password-dialog :deep(.el-dialog__body) {
  padding: 24px 24px 0;
}
</style>

<!-- 折叠态二级菜单飞出面板：内容经 el-popover 传送至 body，
     脱离本组件 scoped 作用域，故单独用非 scoped 样式 -->
<style>
.nav-flyout-popper.el-popover.el-pure-popper {
  padding: 6px;
  background: var(--surface);
  border: 1px solid var(--mist);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
}

.nav-flyout {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-flyout-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--slate);
  padding: 4px 8px 6px;
  border-bottom: 1px solid var(--mist);
  margin-bottom: 2px;
}

.nav-flyout-item {
  display: block;
  padding: 7px 10px;
  border-radius: var(--radius-sm);
  color: var(--ink-soft);
  font-size: 13px;
  white-space: nowrap;
  text-decoration: none;
  transition: background 0.15s ease, color 0.15s ease;
}

.nav-flyout-item:hover {
  background: var(--accent-soft);
  color: var(--accent);
}

.nav-flyout-item.active {
  background: var(--accent);
  color: #fff;
}
</style>

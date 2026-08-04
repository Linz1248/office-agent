<template>
  <div class="auth-page">
    <!-- 左侧品牌区 -->
    <div class="auth-brand">
      <div class="auth-brand-content">
        <div class="brand-logo">
          <svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="32" height="32" rx="8" fill="white" fill-opacity="0.2"/>
            <path d="M10 8.5C10 7.67 10.67 7 11.5 7H18l4 4v12.5c0 .83-.67 1.5-1.5 1.5h-9c-.83 0-1.5-.67-1.5-1.5V8.5Z" fill="white" fill-opacity="0.95"/>
            <path d="M18 7v4h4" stroke="#2563EB" stroke-width="1.5" stroke-linejoin="round" fill="white"/>
            <line x1="13" y1="15" x2="19" y2="15" stroke="#93C5FD" stroke-width="1.5" stroke-linecap="round"/>
            <line x1="13" y1="18" x2="17" y2="18" stroke="#93C5FD" stroke-width="1.5" stroke-linecap="round"/>
            <path d="M22.5 6.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z" fill="#FDE047"/>
          </svg>
        </div>
        <h1>智能办公平台</h1>
        <p class="brand-tagline">文档智能处理 · 多模态检索 · AI 对话</p>

        <div class="auth-features">
          <div class="auth-feature">
            <div class="feature-icon">
              <svg viewBox="0 0 20 20" fill="none"><path d="M6 3h8l3 3v11a1 1 0 01-1 1H6a1 1 0 01-1-1V4a1 1 0 011-1z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M14 3v3h3" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M8 11l2 2 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </div>
            <div class="feature-text">
              <span class="feature-title">智能文档抽取</span>
              <span class="feature-desc">PDF 结构化信息提取，支持增强模式</span>
            </div>
          </div>
          <div class="auth-feature">
            <div class="feature-icon">
              <svg viewBox="0 0 20 20" fill="none"><rect x="2" y="4" width="7" height="12" rx="1" stroke="currentColor" stroke-width="1.5"/><rect x="11" y="4" width="7" height="12" rx="1" stroke="currentColor" stroke-width="1.5"/><path d="M9 10h2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-dasharray="1.5 1.5"/></svg>
            </div>
            <div class="feature-text">
              <span class="feature-title">文档逐页比对</span>
              <span class="feature-desc">高亮差异内容，快速定位变更</span>
            </div>
          </div>
          <div class="auth-feature">
            <div class="feature-icon">
              <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="currentColor" stroke-width="1.5"/><circle cx="7" cy="7" r="1.5" fill="currentColor"/><circle cx="13" cy="8" r="1" fill="currentColor"/><circle cx="12" cy="13" r="1.2" fill="currentColor"/><circle cx="7" cy="12" r="1" fill="currentColor"/></svg>
            </div>
            <div class="feature-text">
              <span class="feature-title">跨模态语义检索</span>
              <span class="feature-desc">以文搜图、以图搜图、以文搜音</span>
            </div>
          </div>
          <div class="auth-feature">
            <div class="feature-icon">
              <svg viewBox="0 0 20 20" fill="none"><path d="M10 3l1.8 4.7L16.5 9l-4.7 1.3L10 15l-1.8-4.7L3.5 9l4.7-1.3L10 3z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><circle cx="15.5" cy="15.5" r="1.5" fill="currentColor"/></svg>
            </div>
            <div class="feature-text">
              <span class="feature-title">AI 对话助手</span>
              <span class="feature-desc">AgentScope 驱动的智能问答</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 右侧表单区 -->
    <div class="auth-form-side">
      <div class="auth-form-box">
        <div class="form-logo">
          <svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="32" height="32" rx="8" fill="#2563EB"/>
            <path d="M10 8.5C10 7.67 10.67 7 11.5 7H18l4 4v12.5c0 .83-.67 1.5-1.5 1.5h-9c-.83 0-1.5-.67-1.5-1.5V8.5Z" fill="white" fill-opacity="0.9"/>
            <path d="M18 7v4h4" stroke="#2563EB" stroke-width="1.5" stroke-linejoin="round" fill="white"/>
            <line x1="13" y1="15" x2="19" y2="15" stroke="#93C5FD" stroke-width="1.5" stroke-linecap="round"/>
            <line x1="13" y1="18" x2="17" y2="18" stroke="#93C5FD" stroke-width="1.5" stroke-linecap="round"/>
            <path d="M22.5 6.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z" fill="#FDE047"/>
          </svg>
        </div>
        <h2 class="auth-form-title">创建账号</h2>
        <p class="auth-form-subtitle">注册以开始使用智能办公平台</p>

        <el-form
          ref="registerFormRef"
          :model="registerForm"
          :rules="registerRules"
          label-position="top"
          @submit.prevent="handleRegister"
        >
          <el-form-item prop="username" label="用户名">
            <el-input v-model="registerForm.username" placeholder="3-20 个字符" size="large" :prefix-icon="User" />
          </el-form-item>
          <el-form-item prop="email" label="邮箱">
            <el-input v-model="registerForm.email" placeholder="请输入邮箱" size="large" :prefix-icon="Message" />
          </el-form-item>
          <el-form-item prop="password" label="密码">
            <el-input v-model="registerForm.password" type="password" placeholder="6-50 个字符" size="large" :prefix-icon="Lock" show-password />
          </el-form-item>
          <el-form-item prop="confirmPassword" label="确认密码">
            <el-input v-model="registerForm.confirmPassword" type="password" placeholder="请再次输入密码" size="large" :prefix-icon="Lock" show-password @keyup.enter="handleRegister" />
          </el-form-item>
          <el-form-item prop="admin_password" label="管理员密码">
            <el-input v-model="registerForm.admin_password" type="password" placeholder="请联系管理员获取" size="large" :prefix-icon="Lock" show-password />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" size="large" :loading="loading" @click="handleRegister" class="auth-submit-btn">
              注册
            </el-button>
          </el-form-item>
        </el-form>

        <div class="auth-footer">
          <span>已有账号？</span>
          <router-link to="/login" class="auth-link">立即登录</router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock, Message } from '@element-plus/icons-vue'
import request from '@/utils/request'

const reg = /^\w+((.\w+)|(-\w+))@[A-Za-z0-9]+((.|-)[A-Za-z0-9]+).[A-Za-z0-9]+$/
const router = useRouter()
const registerFormRef = ref()
const loading = ref(false)

const registerForm = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
  admin_password: ''
})

const validateConfirmPassword = (rule, value, callback) => {
  if (value !== registerForm.password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const validateEmail = (rule, value, callback) => {
  if (!reg.test(value)) {
    callback(new Error('邮箱格式不合法'))
  }
  callback()
}

const registerRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 50, message: '用户名长度在3到20个字符', trigger: 'blur' },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { validator: validateEmail, trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 50, message: '密码长度在6到50个字符', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: 'blur' },
  ],
  admin_password: [
    { required: true, message: '请输入管理员密码', trigger: 'blur' },
  ],
}

const handleRegister = () => {
  if (!registerFormRef.value) return

  try {
    const valid = registerFormRef.value.validate()
    if (!valid) return

    loading.value = true

    request.post('register', registerForm, { serverName: 'docExtract' }).then(res => {
      if (res.status === 200) {
        ElMessage.success('注册成功，请登录')
        router.push('/login')
      } else {
        ElMessage.error('注册失败')
      }
    })
  } catch (error) {
    console.error('注册错误:', error)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* --- 左侧品牌区 --- */
.auth-brand {
  flex: 1;
  background: linear-gradient(135deg, #1E293B 0%, #1D4ED8 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
}

.auth-brand::before {
  content: '';
  position: absolute;
  top: -30%;
  right: -15%;
  width: 600px;
  height: 600px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(96, 165, 250, 0.18) 0%, transparent 65%);
}

.auth-brand::after {
  content: '';
  position: absolute;
  bottom: -35%;
  left: -10%;
  width: 500px;
  height: 500px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(59, 130, 246, 0.12) 0%, transparent 65%);
}

.auth-brand-content {
  position: relative;
  z-index: 1;
  max-width: 460px;
  padding: 48px;
}

.brand-logo {
  width: 56px;
  height: 56px;
  margin-bottom: 28px;
  filter: drop-shadow(0 4px 12px rgba(0, 0, 0, 0.2));
}

.brand-logo svg {
  width: 100%;
  height: 100%;
}

.auth-brand h1 {
  font-size: 30px;
  font-weight: 700;
  color: #F1F5F9;
  margin: 0 0 8px;
  letter-spacing: -0.01em;
}

.brand-tagline {
  font-size: 14px;
  color: #93C5FD;
  margin: 0 0 44px;
}

.auth-features {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.auth-feature {
  display: flex;
  align-items: flex-start;
  gap: 14px;
}

.feature-icon {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.12);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #BFDBFE;
}

.feature-icon svg {
  width: 20px;
  height: 20px;
}

.feature-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-top: 1px;
}

.feature-title {
  font-size: 14px;
  font-weight: 600;
  color: #E2E8F0;
}

.feature-desc {
  font-size: 13px;
  color: #94A3B8;
}

/* --- 右侧表单区 --- */
.auth-form-side {
  width: 480px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface);
  overflow-y: auto;
}

.auth-form-box {
  width: 100%;
  max-width: 360px;
  padding: 40px;
}

.form-logo {
  width: 44px;
  height: 44px;
  margin-bottom: 20px;
}

.form-logo svg {
  width: 100%;
  height: 100%;
}

.auth-form-title {
  font-size: 26px;
  font-weight: 700;
  color: var(--ink);
  margin: 0 0 6px;
  letter-spacing: -0.01em;
}

.auth-form-subtitle {
  font-size: 14px;
  color: var(--slate);
  margin: 0 0 28px;
}

.auth-form-box :deep(.el-form-item__label) {
  font-size: 13px;
  font-weight: 500;
  color: var(--ink);
  padding-bottom: 6px;
}

.auth-form-box :deep(.el-input__wrapper) {
  border-radius: var(--radius-sm);
}

.auth-submit-btn {
  width: 100%;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.auth-footer {
  text-align: center;
  font-size: 14px;
  color: var(--slate);
  margin-top: 24px;
}

.auth-link {
  color: var(--accent);
  font-weight: 500;
  margin-left: 4px;
}

.auth-link:hover {
  text-decoration: underline;
}

@media (max-width: 900px) {
  .auth-brand {
    display: none;
  }

  .auth-form-side {
    width: 100%;
  }
}
</style>

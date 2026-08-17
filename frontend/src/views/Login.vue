<template>
  <div class="auth-page">
    <!-- 左侧品牌区 -->
    <div class="auth-brand">
      <div class="auth-brand-content">
        <div class="brand-logo">
          <BrandLogo :size="56" variant="glass" />
        </div>
        <h1>慧办</h1>
        <p class="brand-tagline">智能办公平台 · 文档处理 · 多模态检索 · AI 对话</p>

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
          <BrandLogo :size="44" />
        </div>
        <h2 class="auth-form-title">欢迎回来</h2>
        <p class="auth-form-subtitle">登录你的慧办账号以继续</p>

        <el-form ref="ruleFormRef" :model="form" :rules="rules" status-icon @keyup.enter="login" label-position="top">
          <el-form-item prop="username" label="用户名">
            <el-input size="large" v-model="form.username" placeholder="请输入用户名" :prefix-icon="User" />
          </el-form-item>
          <el-form-item prop="password" label="密码">
            <el-input size="large" v-model="form.password" show-password placeholder="请输入密码" autocomplete="new-password" :prefix-icon="Lock" />
          </el-form-item>
          <el-form-item>
            <el-button size="large" type="primary" class="auth-submit-btn" @click="login">登录</el-button>
          </el-form-item>
        </el-form>

        <div class="auth-footer">
          <span>还没有账号？</span>
          <router-link to="/register" class="auth-link">立即注册</router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { User, Lock } from '@element-plus/icons-vue'
import router from '@/router'
import request from '@/utils/request'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import BrandLogo from '@/components/BrandLogo.vue'

const ruleFormRef = ref()
const form = reactive({})
const store = useUserStore()

const rules = reactive({
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
})

const login = () => {
  ruleFormRef.value.validate(valid => {
    if (valid) {
      request.post('/login', form, { serverName: 'docExtract' }).then(res => {
        if (res.status === 200) {
          store.setLoginInfo(res.data)
          ElMessage.success('登录成功')
          router.push('/')
        } else {
          ElMessage.error('登录失败')
        }
      }).catch(e => {
        console.log(e)
      })
    }
  })
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
  font-size: 34px;
  font-weight: 700;
  color: #F1F5F9;
  margin: 0 0 8px;
  letter-spacing: 0.06em;
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
}

.auth-form-box {
  width: 100%;
  max-width: 360px;
  padding: 48px 40px;
}

.form-logo {
  width: 44px;
  height: 44px;
  margin-bottom: 24px;
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
  margin: 0 0 36px;
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
  margin-top: 28px;
}

.auth-link {
  color: var(--accent);
  font-weight: 500;
  margin-left: 4px;
}

.auth-link:hover {
  text-decoration: underline;
}

/* --- 响应式 --- */
@media (max-width: 900px) {
  .auth-brand {
    display: none;
  }

  .auth-form-side {
    width: 100%;
  }
}
</style>

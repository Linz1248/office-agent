<template>
  <div class="page-container">
    <div class="retrieval-page">
      <header class="retrieval-header">
        <h1 class="page-title"><span class="title-accent" />我的技能</h1>
        <p class="kb-subtitle">创建 Markdown 指令技能扩展 AI 能力，或管理从市场安装的技能；启用的技能在对话中自动注入。</p>
      </header>

      <!-- 统计 -->
      <div class="kb-stats">
        <div class="kb-stat card">
          <div class="kb-stat-num">{{ mySkills.length }}</div>
          <div class="kb-stat-label">技能总数</div>
        </div>
        <div class="kb-stat card">
          <div class="kb-stat-num">{{ mySharedCount }}</div>
          <div class="kb-stat-label">已公开</div>
        </div>
        <div class="kb-stat card">
          <div class="kb-stat-num">{{ installedCount }}</div>
          <div class="kb-stat-label">已安装</div>
        </div>
        <div class="kb-stat card">
          <div class="kb-stat-num">{{ enabledCount }}</div>
          <div class="kb-stat-label">已启用</div>
        </div>
      </div>

      <!-- 操作栏 -->
      <div class="skill-create-bar">
        <el-button type="primary" @click="openCreateDialog">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;margin-right:6px"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          创建新技能
        </el-button>
        <el-button :loading="uploading" @click="skillFileInput?.click()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;margin-right:6px"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          上传 SKILL.md
        </el-button>
        <input ref="skillFileInput" type="file" accept=".md" hidden @change="onSkillFilePick" />
        <el-button v-if="installedCount > 0" :loading="checkingUpdates" @click="checkUpdates">
          检查更新
        </el-button>
      </div>

      <!-- 列表 -->
      <div v-if="loadingMine && !mySkills.length" class="retrieval-state retrieval-loading card">
        <div class="spinner" /><div class="state-title">加载技能列表…</div>
      </div>
      <div v-else-if="!mySkills.length" class="retrieval-state card">
        <div class="state-icon">⚡</div>
        <div class="state-title">还没有技能</div>
        <div class="state-hint">创建你的第一个 Markdown 指令技能，或从技能市场安装他人共享的技能。</div>
      </div>
      <div v-else class="skill-grid">
        <div v-for="s in mySkills" :key="s.skill_id" class="skill-card card" :class="{ 'is-installed': s.author }">
          <!-- 已安装标记 -->
          <div v-if="s.author" class="skill-badge-installed">安装</div>
          <div v-if="s.has_update" class="skill-badge-update" title="原作者有更新">更新</div>
          <div class="skill-card-head">
            <div class="skill-card-icon">⚡</div>
            <div class="skill-card-title-area">
              <div class="skill-card-name" :title="s.name">{{ s.name }}</div>
              <div class="skill-card-author" v-if="s.author">来自：{{ s.author }}</div>
            </div>
          </div>
          <div class="skill-card-desc" :title="s.description">{{ s.description }}</div>
          <div v-if="s.tags" class="skill-card-tags">
            <span v-for="t in s.tags.split(',')" :key="t" class="skill-tag">{{ t.trim() }}</span>
          </div>
          <div class="skill-card-footer">
            <div class="skill-toggles">
              <div class="kb-toggle" :title="s.enabled ? '已启用' : '已禁用'">
                <span class="kb-toggle-label">{{ s.enabled ? '启用' : '禁用' }}</span>
                <el-switch :model-value="s.enabled" :loading="togglingEnabled === s.skill_id" @change="(v) => toggleEnabled(s, v)" />
              </div>
              <div v-if="!s.author" class="kb-toggle" :title="s.shared ? '已公开到市场' : '仅自己可见'">
                <span class="kb-toggle-label">{{ s.shared ? '公开' : '私有' }}</span>
                <el-switch :model-value="s.shared" :loading="toggling === s.skill_id" @change="(v) => toggleShare(s, v)" />
              </div>
            </div>
            <div class="skill-actions">
              <el-button v-if="s.has_update" text type="primary" size="small" @click="syncSkill(s)">同步</el-button>
              <el-button text size="small" @click="viewSkill(s)">查看</el-button>
              <el-button v-if="!s.author" text size="small" @click="editSkill(s)">编辑</el-button>
              <el-popconfirm title="确认删除此技能？删除后不可恢复。" confirm-button-text="删除" cancel-button-text="取消" width="240" @confirm="removeSkill(s)">
                <template #reference><el-button text size="small" type="danger">删除</el-button></template>
              </el-popconfirm>
            </div>
          </div>
        </div>
      </div>

      <!-- 创建/编辑对话框 -->
      <el-dialog v-model="dialogVisible" :title="editingId ? '编辑技能' : '创建新技能'" width="680px" class="skill-dialog" :close-on-click-modal="false">
        <el-form :model="formData" label-position="top" class="skill-form">
          <el-form-item label="技能名称" required>
            <el-input v-model="formData.name" placeholder="如：合同审查" maxlength="50" />
          </el-form-item>
          <el-form-item label="一句话描述" required>
            <el-input v-model="formData.description" placeholder="如：当用户需要审查合同条款时使用此技能" maxlength="200" />
          </el-form-item>
          <el-form-item label="标签（逗号分隔）">
            <el-input v-model="formData.tags" placeholder="如：法律,合同,审查" maxlength="100" />
          </el-form-item>
          <el-form-item label="指令正文（Markdown）" required>
            <el-input v-model="formData.body" type="textarea" :rows="12" placeholder="输入技能的详细指令步骤。智能体读取后会按此指令执行操作。" />
            <div class="form-hint">frontmatter（name/description/tags）由系统自动生成，只需输入正文。</div>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="saveSkill">{{ editingId ? '保存' : '创建' }}</el-button>
        </template>
      </el-dialog>

      <!-- 查看对话框 -->
      <el-dialog v-model="viewVisible" title="技能详情" width="680px" class="skill-dialog">
        <div v-if="viewing">
          <div class="view-meta">
            <h3 class="view-name">{{ viewing.name }}</h3>
            <p class="view-desc">{{ viewing.description }}</p>
            <div v-if="viewing.tags" class="skill-card-tags">
              <span v-for="t in viewing.tags.split(',')" :key="t" class="skill-tag">{{ t.trim() }}</span>
            </div>
          </div>
          <pre class="view-body">{{ viewing.markdown }}</pre>
        </div>
      </el-dialog>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/utils/request'

const loadingMine = ref(false)
const mySkills = ref([])

const toggling = ref('')
const togglingEnabled = ref('')
const checkingUpdates = ref(false)
const saving = ref(false)
const uploading = ref(false)
const skillFileInput = ref(null)

const dialogVisible = ref(false)
const editingId = ref('')
const formData = ref({ name: '', description: '', tags: '', body: '' })

const viewVisible = ref(false)
const viewing = ref(null)

const mySharedCount = computed(() => mySkills.value.filter((s) => s.shared && !s.author).length)
const installedCount = computed(() => mySkills.value.filter((s) => s.author).length)
const enabledCount = computed(() => mySkills.value.filter((s) => s.enabled).length)

const fetchMine = async () => {
  loadingMine.value = true
  try {
    const res = await request.get('/skills', { serverName: 'agent' })
    if (res.status === 200) mySkills.value = res.data.skills || []
  } catch { } finally { loadingMine.value = false }
}

const onSkillFilePick = async (e) => {
  const file = e.target.files?.[0]
  e.target.value = ''
  if (!file) return
  uploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', file)
    const res = await request.post('/skills/upload', formData, {
      serverName: 'agent',
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    if (res.status === 200) {
      ElMessage.success(`已上传技能「${res.data.name}」`)
      await fetchMine()
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '上传失败，请检查文件格式')
  } finally { uploading.value = false }
}

const openCreateDialog = () => {
  editingId.value = ''
  formData.value = { name: '', description: '', tags: '', body: '' }
  dialogVisible.value = true
}

const editSkill = (s) => {
  editingId.value = s.skill_id
  formData.value = { name: s.name, description: s.description, tags: s.tags, body: s.markdown || '' }
  const fmMatch = formData.value.body.match(/^---\n[\s\S]*?\n---\n?/)
  if (fmMatch) formData.value.body = formData.value.body.slice(fmMatch[0].length).trim()
  dialogVisible.value = true
}

const saveSkill = async () => {
  if (!formData.value.name.trim() || !formData.value.description.trim() || !formData.value.body.trim()) {
    ElMessage.warning('请填写技能名称、描述和指令正文')
    return
  }
  saving.value = true
  try {
    if (editingId.value) {
      await request.put(`/skills/${editingId.value}`, formData.value, { serverName: 'agent' })
      ElMessage.success('技能已更新')
    } else {
      await request.post('/skills', formData.value, { serverName: 'agent' })
      ElMessage.success('技能已创建')
    }
    dialogVisible.value = false
    await fetchMine()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  } finally { saving.value = false }
}

const toggleShare = async (s, v) => {
  toggling.value = s.skill_id
  try {
    await request.patch(`/skills/${s.skill_id}`, { shared: v }, { serverName: 'agent' })
    s.shared = v
    ElMessage.success(v ? '已公开到市场' : '已设为私有')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '切换失败')
  } finally { toggling.value = '' }
}

const toggleEnabled = async (s, v) => {
  togglingEnabled.value = s.skill_id
  try {
    await request.patch(`/skills/${s.skill_id}/enabled`, { enabled: v }, { serverName: 'agent' })
    s.enabled = v
    ElMessage.success(v ? '已启用' : '已禁用')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '切换失败')
  } finally { togglingEnabled.value = '' }
}

const removeSkill = async (s) => {
  try {
    await request.delete(`/skills/${s.skill_id}`, { serverName: 'agent' })
    ElMessage.success('已删除')
    await fetchMine()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

const viewSkill = (s) => { viewing.value = s; viewVisible.value = true }

const checkUpdates = async () => {
  checkingUpdates.value = true
  try {
    const res = await request.post('/skills/check-updates', {}, { serverName: 'agent' })
    if (res.status === 200) {
      const updates = res.data.updates || []
      if (updates.length) {
        ElMessage.success(`发现 ${updates.length} 个技能有更新`)
        await fetchMine()
      } else {
        ElMessage.info('所有技能均为最新版本')
      }
    }
  } catch { ElMessage.error('检查更新失败') } finally { checkingUpdates.value = false }
}

const syncSkill = async (s) => {
  try {
    await request.post(`/skills/${s.skill_id}/sync`, {}, { serverName: 'agent' })
    ElMessage.success('已同步最新版本')
    await fetchMine()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '同步失败')
  }
}

onMounted(fetchMine)
</script>

<style scoped>
.kb-subtitle { margin: -4px 0 0; color: var(--slate); font-size: 13px; }

.kb-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-md); margin-bottom: var(--space-md); }
.kb-stat { padding: var(--space-md) var(--space-lg); text-align: center; }
.kb-stat-num { font-size: 26px; font-weight: 700; color: var(--accent); }
.kb-stat-label { font-size: 12px; color: var(--slate); margin-top: 2px; }

.skill-create-bar { display: flex; gap: var(--space-sm); margin-bottom: var(--space-md); }

.skill-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: var(--space-md); }

.skill-card {
  position: relative;
  padding: var(--space-md) var(--space-lg);
  display: flex; flex-direction: column; gap: 10px;
  transition: box-shadow var(--transition);
}
.skill-card:hover { box-shadow: var(--shadow-md); }

.skill-badge-installed {
  position: absolute; top: 10px; right: 10px;
  font-size: 10px; padding: 2px 8px; border-radius: 10px;
  background: var(--mist-light); color: var(--slate);
  font-weight: 500;
}
.skill-badge-update {
  position: absolute; top: 10px; right: 60px;
  font-size: 10px; padding: 2px 8px; border-radius: 10px;
  background: var(--warning-soft); color: var(--warning);
  font-weight: 600; cursor: default;
}

.skill-card-head { display: flex; align-items: center; gap: 12px; }
.skill-card-icon {
  flex-shrink: 0; width: 40px; height: 40px; border-radius: 10px;
  background: var(--accent-soft); color: var(--accent);
  display: flex; align-items: center; justify-content: center; font-size: 20px;
}
.skill-card-title-area { flex: 1; min-width: 0; }
.skill-card-name { font-size: 15px; font-weight: 700; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.skill-card-author { font-size: 12px; color: var(--slate); margin-top: 2px; }

.skill-card-desc {
  font-size: 13px; color: var(--slate); line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}

.skill-card-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.skill-tag {
  font-size: 11px; padding: 2px 8px; border-radius: 10px;
  background: var(--mist-light); color: var(--slate);
}

.skill-card-footer {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--space-sm); margin-top: auto; padding-top: 8px;
  border-top: 1px solid var(--mist);
}
.skill-toggles { display: flex; gap: 12px; }
.kb-toggle { display: flex; align-items: center; gap: 6px; }
.kb-toggle-label { font-size: 12px; color: var(--slate); white-space: nowrap; }

.skill-actions { display: flex; gap: 4px; flex-shrink: 0; }

.skill-dialog :deep(.el-dialog__body) { padding: 20px 24px 0; }
.skill-form .form-hint { font-size: 12px; color: var(--slate); margin-top: 4px; }

.view-meta { margin-bottom: var(--space-md); }
.view-name { font-size: 18px; font-weight: 700; color: var(--ink); margin: 0 0 8px; }
.view-desc { font-size: 13px; color: var(--slate); margin: 0 0 10px; }
.view-body {
  background: var(--mist-light); border-radius: var(--radius-sm);
  padding: var(--space-md); font-size: 13px; line-height: 1.6;
  white-space: pre-wrap; word-break: break-word; max-height: 400px; overflow-y: auto;
  font-family: var(--font-mono);
}

.retrieval-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: var(--space-sm); padding: var(--space-2xl) var(--space-lg); text-align: center;
}
.retrieval-state .state-icon { font-size: 34px; line-height: 1; color: var(--slate-light); }
.retrieval-state .state-title { font-size: 15px; font-weight: 600; color: var(--ink-soft); }
.retrieval-state .state-hint { font-size: 13px; color: var(--slate-light); max-width: 360px; }
.retrieval-loading .spinner {
  width: 28px; height: 28px; border: 3px solid var(--mist);
  border-top-color: var(--accent); border-radius: 50%; animation: rt-spin 0.7s linear infinite;
}
@keyframes rt-spin { to { transform: rotate(360deg); } }
</style>

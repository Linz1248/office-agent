<template>
  <div class="page-container">
    <div class="retrieval-page">
      <header class="retrieval-header">
        <h1 class="page-title"><span class="title-accent" />技能市场</h1>
        <p class="kb-subtitle">浏览团队共享的技能，一键安装到个人技能库；安装后获得独立副本，不受原作者删除影响。</p>
      </header>

      <!-- 统计 -->
      <div class="kb-stats">
        <div class="kb-stat card">
          <div class="kb-stat-num">{{ marketTotal }}</div>
          <div class="kb-stat-label">市场技能</div>
        </div>
        <div class="kb-stat card">
          <div class="kb-stat-num">{{ marketSkills.length }}</div>
          <div class="kb-stat-label">当前页</div>
        </div>
      </div>

      <!-- 搜索栏 -->
      <div class="market-search card">
        <el-input v-model="marketKeyword" placeholder="搜索技能名称或描述…" clearable @keyup.enter="searchMarket" @clear="searchMarket" class="market-search-input">
          <template #prefix><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg></template>
        </el-input>
        <el-button type="primary" @click="searchMarket">搜索</el-button>
      </div>

      <!-- 列表 -->
      <div v-if="loadingMarket && !marketSkills.length" class="retrieval-state retrieval-loading card">
        <div class="spinner" /><div class="state-title">加载市场技能…</div>
      </div>
      <div v-else-if="!marketSkills.length" class="retrieval-state card">
        <div class="state-icon">🏪</div>
        <div class="state-title">市场暂无技能</div>
        <div class="state-hint">前往「我的技能」页面创建并公开技能，与团队成员共享。</div>
      </div>
      <div v-else class="skill-grid">
        <div v-for="s in marketSkills" :key="s.skill_id" class="skill-card card is-market">
          <div class="skill-card-head">
            <div class="skill-card-icon">⚡</div>
            <div class="skill-card-title-area">
              <div class="skill-card-name" :title="s.name">{{ s.name }}</div>
              <div class="skill-card-author">作者：{{ s.author }}</div>
            </div>
          </div>
          <div class="skill-card-desc" :title="s.description">{{ s.description }}</div>
          <div v-if="s.tags" class="skill-card-tags">
            <span v-for="t in s.tags.split(',')" :key="t" class="skill-tag">{{ t.trim() }}</span>
          </div>
          <div class="skill-card-footer">
            <div class="skill-actions">
              <el-button text size="small" @click="viewSkill(s)">查看</el-button>
              <el-button type="primary" size="small" :loading="installing === s.skill_id" @click="installSkill(s)">安装</el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div v-if="marketTotal > marketSize" class="market-pager">
        <el-pagination background layout="prev, pager, next" :total="marketTotal" :page-size="marketSize" v-model:current-page="marketPage" @current-change="fetchMarket" />
      </div>

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
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/utils/request'

const loadingMarket = ref(false)
const marketSkills = ref([])
const marketTotal = ref(0)
const marketKeyword = ref('')
const marketPage = ref(1)
const marketSize = 20
const installing = ref('')

const viewVisible = ref(false)
const viewing = ref(null)

const fetchMarket = async () => {
  loadingMarket.value = true
  try {
    const params = { page: marketPage.value, size: marketSize }
    if (marketKeyword.value) params.keyword = marketKeyword.value
    const res = await request.get('/skills/market', { serverName: 'agent', params })
    if (res.status === 200) {
      marketSkills.value = res.data.items || []
      marketTotal.value = res.data.total || 0
    }
  } catch { } finally { loadingMarket.value = false }
}

const searchMarket = () => { marketPage.value = 1; fetchMarket() }

const installSkill = async (s) => {
  installing.value = s.skill_id
  try {
    await request.post('/skills/install', { author_id: s.author, author_skill_id: s.skill_id }, { serverName: 'agent' })
    ElMessage.success(`已安装「${s.name}」`)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '安装失败')
  } finally { installing.value = '' }
}

const viewSkill = (s) => { viewing.value = s; viewVisible.value = true }

onMounted(fetchMarket)
</script>

<style scoped>
.kb-subtitle { margin: -4px 0 0; color: var(--slate); font-size: 13px; }

.kb-stats { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-md); margin-bottom: var(--space-md); max-width: 320px; }
.kb-stat { padding: var(--space-md) var(--space-lg); text-align: center; }
.kb-stat-num { font-size: 26px; font-weight: 700; color: var(--accent); }
.kb-stat-label { font-size: 12px; color: var(--slate); margin-top: 2px; }

.market-search { display: flex; gap: var(--space-sm); padding: var(--space-md); margin-bottom: var(--space-md); }
.market-search-input { flex: 1; }

.skill-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: var(--space-md); }

.skill-card {
  position: relative;
  padding: var(--space-md) var(--space-lg);
  display: flex; flex-direction: column; gap: 10px;
  transition: box-shadow var(--transition);
}
.skill-card:hover { box-shadow: var(--shadow-md); }

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
  display: flex; align-items: center; justify-content: flex-end;
  gap: var(--space-sm); margin-top: auto; padding-top: 8px;
  border-top: 1px solid var(--mist);
}
.skill-actions { display: flex; gap: 4px; flex-shrink: 0; }

.market-pager { display: flex; justify-content: center; margin-top: var(--space-lg); }

.skill-dialog :deep(.el-dialog__body) { padding: 20px 24px 0; }
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

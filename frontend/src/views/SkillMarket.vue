<template>
  <div class="page-container">
    <div class="retrieval-page">
      <header class="retrieval-header">
        <h1 class="page-title"><span class="title-accent" />技能市场</h1>
      </header>

      <!-- 增长曲线 -->
      <section class="growth-card card">
        <div class="growth-head">
          <div class="growth-hero">
            <span class="growth-hero-dot" />
            <div>
              <div class="growth-hero-num">{{ marketTotal }}</div>
              <div class="growth-hero-label">市场技能</div>
            </div>
          </div>
        </div>

        <div
          ref="chartRef"
          class="growth-chart"
          @mousemove="onChartMove"
          @mouseleave="onChartLeave"
        >
          <svg v-if="width > 0 && points.length > 1" :width="width" :height="height" class="growth-svg">
            <defs>
              <linearGradient id="growthFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.16" />
                <stop offset="100%" stop-color="var(--accent)" stop-opacity="0" />
              </linearGradient>
            </defs>

            <!-- 水平网格线 + Y 轴刻度 -->
            <g class="grid">
              <g v-for="t in yTicks" :key="'g' + t.i">
                <line
                  :x1="pad.left"
                  :y1="t.y"
                  :x2="width - pad.right"
                  :y2="t.y"
                  stroke="var(--mist)"
                  stroke-width="1"
                />
                <text
                  :x="pad.left - 8"
                  :y="t.y + 3"
                  text-anchor="end"
                  class="axis-text"
                >{{ t.label }}</text>
              </g>
            </g>

            <!-- 区域填充 + 趋势线 -->
            <path :d="areaPath" fill="url(#growthFill)" />
            <path
              :d="linePath"
              fill="none"
              stroke="var(--accent)"
              stroke-width="2"
              stroke-linejoin="round"
              stroke-linecap="round"
            />

            <!-- X 轴刻度 -->
            <g class="x-axis">
              <text
                v-for="t in xTicks"
                :key="'x' + t.i"
                :x="t.x"
                :y="height - pad.bottom + 18"
                text-anchor="middle"
                class="axis-text"
              >{{ t.label }}</text>
            </g>

            <!-- 末端点 -->
            <circle
              :cx="lastPoint.x"
              :cy="lastPoint.y"
              r="4.5"
              fill="var(--accent)"
              stroke="var(--surface)"
              stroke-width="2"
            />

            <!-- 悬浮十字线 + 高亮点 -->
            <g v-if="hover">
              <line
                :x1="hover.x"
                :y1="pad.top"
                :x2="hover.x"
                :y2="height - pad.bottom"
                stroke="var(--slate-light)"
                stroke-width="1"
              />
              <circle
                :cx="hover.x"
                :cy="hover.y"
                r="4.5"
                fill="var(--accent)"
                stroke="var(--surface)"
                stroke-width="2"
              />
            </g>
          </svg>
          <div v-else class="growth-empty">暂无足够数据绘制增长曲线</div>

          <!-- 悬浮提示 -->
          <div
            v-if="hover && hoverTip"
            class="growth-tooltip"
            :style="{ left: hoverTip.left + 'px', top: hoverTip.top + 'px' }"
          >
            <div class="tt-date">{{ hoverTip.date }}</div>
            <div class="tt-count">累计 <strong>{{ hoverTip.count }}</strong> 个</div>
          </div>
        </div>
      </section>

      <!-- 搜索栏 -->
      <div class="market-search card">
        <el-input
          v-model="marketKeyword"
          placeholder="搜索技能名称或描述…"
          clearable
          @keyup.enter="searchMarket"
          @clear="searchMarket"
          class="market-search-input"
        >
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
          <div class="skill-card-footer">
            <div class="skill-actions">
              <el-button text size="small" @click="viewSkill(s)">查看</el-button>
              <el-button
                v-if="!isOwnSkill(s)"
                type="primary"
                size="small"
                :loading="installing === s.skill_id"
                @click="installSkill(s)"
              >安装</el-button>
              <span v-else class="own-skill-hint">我发布的</span>
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
          </div>
          <pre class="view-body">{{ viewing.markdown }}</pre>
        </div>
      </el-dialog>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/utils/request'
import { useUserStore } from '@/stores/user'

const store = useUserStore()

// 判断是否为当前用户自己发布的技能（author 为原作者 user_id）
const isOwnSkill = (s) => s.author === store.getUser?.username

const loadingMarket = ref(false)
const marketSkills = ref([])
const marketTotal = ref(0)
const marketKeyword = ref('')
const marketPage = ref(1)
const marketSize = 20
const installing = ref('')

const viewVisible = ref(false)
const viewing = ref(null)

// ── 增长曲线 ─────────────────────────────────────────────────────────────
const points = ref([])
const chartRef = ref(null)
const width = ref(0)
const height = 260
const pad = { top: 16, right: 16, bottom: 28, left: 40 }

let ro = null
const measure = () => {
  if (chartRef.value) width.value = chartRef.value.clientWidth
}

const plotW = computed(() => Math.max(0, width.value - pad.left - pad.right))
const plotH = computed(() => height - pad.top - pad.bottom)

const maxCount = computed(() =>
  points.value.reduce((m, p) => Math.max(m, p.count), 0)
)

// 取整到 1/2/5×10ⁿ 的"干净"上限，Y 轴刻度才好看
const niceMax = computed(() => {
  const m = maxCount.value || 1
  const pow = Math.pow(10, Math.floor(Math.log10(m)))
  const n = m / pow
  const nice = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10
  return nice * pow
})

const yTicks = computed(() => {
  const steps = 4
  const out = []
  for (let i = 0; i <= steps; i++) {
    const v = Math.round((niceMax.value * i) / steps)
    const y = pad.top + plotH.value - (v / niceMax.value) * plotH.value
    out.push({ i, y, label: v })
  }
  return out
})

const xOf = (i) =>
  pad.left +
  (points.value.length <= 1 ? 0 : (i / (points.value.length - 1)) * plotW.value)
const yOf = (v) => pad.top + plotH.value - (v / niceMax.value) * plotH.value

const linePath = computed(() => {
  if (points.value.length < 2) return ''
  return points.value
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${xOf(i).toFixed(1)} ${yOf(p.count).toFixed(1)}`)
    .join(' ')
})

const areaPath = computed(() => {
  if (points.value.length < 2) return ''
  const base = pad.top + plotH.value
  const first = xOf(0)
  const last = xOf(points.value.length - 1)
  const line = points.value
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${xOf(i).toFixed(1)} ${yOf(p.count).toFixed(1)}`)
    .join(' ')
  return `${line} L ${last.toFixed(1)} ${base} L ${first.toFixed(1)} ${base} Z`
})

const lastPoint = computed(() => {
  if (!points.value.length) return { x: 0, y: 0 }
  const i = points.value.length - 1
  return { x: xOf(i), y: yOf(points.value[i].count) }
})

const fmtDate = (iso) => {
  const d = new Date(iso + 'T00:00:00')
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${m}-${day}`
}

const xTicks = computed(() => {
  const n = points.value.length
  if (n < 2) return []
  const want = Math.min(6, n)
  const out = []
  for (let k = 0; k < want; k++) {
    const i = Math.round((n - 1) * (k / (want - 1)))
    out.push({ i, x: xOf(i), label: fmtDate(points.value[i].date) })
  }
  return out
})

// ── 悬浮交互 ─────────────────────────────────────────────────────────────
const hover = ref(null)
const hoverTip = ref(null)

const onChartMove = (e) => {
  if (!points.value.length || plotW.value <= 0) return
  const rect = chartRef.value.getBoundingClientRect()
  const x = e.clientX - rect.left
  const ratio = (x - pad.left) / plotW.value
  let i = Math.round(ratio * (points.value.length - 1))
  i = Math.max(0, Math.min(points.value.length - 1, i))
  const px = xOf(i)
  const py = yOf(points.value[i].count)
  hover.value = { x: px, y: py, index: i }

  const tipW = 132
  const tipH = 50
  let left = px + 12
  if (left + tipW > width.value) left = px - tipW - 12
  let top = py - tipH - 8
  if (top < 4) top = py + 12
  hoverTip.value = {
    left,
    top,
    date: points.value[i].date,
    count: points.value[i].count,
  }
}

const onChartLeave = () => {
  hover.value = null
  hoverTip.value = null
}

const fetchGrowth = async () => {
  try {
    const res = await request.get('/skills/market/growth', { serverName: 'agent' })
    if (res.status === 200) points.value = res.data.points || []
  } catch { /* 忽略，曲线非核心路径 */ }
}

// ── 市场列表 ─────────────────────────────────────────────────────────────
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

onMounted(() => {
  fetchMarket()
  fetchGrowth()
  measure()
  if (chartRef.value && window.ResizeObserver) {
    ro = new ResizeObserver(measure)
    ro.observe(chartRef.value)
  }
})
onUnmounted(() => { ro && ro.disconnect() })
</script>

<style scoped>
/* 增长曲线卡片 */
.growth-card { padding: var(--space-lg); margin-bottom: var(--space-md); }
.growth-head {
  display: flex; align-items: center; justify-content: flex-end;
  gap: var(--space-md); margin-bottom: var(--space-sm);
}
.growth-hero { display: flex; align-items: center; gap: 8px; text-align: right; }
.growth-hero-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--accent); flex-shrink: 0; margin-top: 14px;
}
.growth-hero-num {
  font-size: 30px; font-weight: 700; color: var(--ink); line-height: 1;
  font-variant-numeric: tabular-nums;
}
.growth-hero-label { font-size: 12px; color: var(--slate); margin-top: 4px; }

.growth-chart { position: relative; width: 100%; height: 260px; }
.growth-svg { display: block; overflow: visible; }
.axis-text { fill: var(--slate); font-size: 11px; font-family: var(--font-sans); }
.growth-empty {
  display: flex; align-items: center; justify-content: center;
  height: 100%; color: var(--slate-light); font-size: 13px;
}
.growth-tooltip {
  position: absolute; pointer-events: none;
  background: var(--ink); color: #fff;
  padding: 6px 10px; border-radius: var(--radius-sm);
  font-size: 12px; box-shadow: var(--shadow-md); z-index: 5; white-space: nowrap;
}
.growth-tooltip .tt-date { color: rgba(255, 255, 255, 0.7); font-size: 11px; }
.growth-tooltip .tt-count strong { color: #fff; }

/* 搜索栏（紧凑） */
.market-search {
  display: flex; gap: var(--space-sm); align-items: center;
  padding: var(--space-sm) var(--space-md); margin-bottom: var(--space-md);
  width: fit-content;
}
.market-search-input { width: 320px; flex: 0 0 320px; }

/* 列表 */
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

.own-skill-hint {
  font-size: 12px; color: var(--slate-light);
  padding: 0 8px; align-self: center;
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

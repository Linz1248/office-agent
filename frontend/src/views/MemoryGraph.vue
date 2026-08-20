<template>
  <div class="mg-page">
    <!-- 头部 -->
    <header class="mg-header">
      <div class="mg-heading">
        <div class="mg-heading-mark">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="5" r="2" /><circle cx="5" cy="19" r="2" /><circle cx="19" cy="19" r="2" />
            <path d="M12 7v4M12 11 6 17M12 11l6 6" />
          </svg>
        </div>
        <h1 class="mg-title">记忆图谱</h1>
      </div>
      <div class="mg-stats" v-if="graphData">
        <div class="mg-stat" v-for="s in statItems" :key="s.label">
          <span class="mg-stat-num" :style="s.color ? { color: s.color } : null">{{ s.value }}</span>
          <span class="mg-stat-label">{{ s.label }}</span>
        </div>
      </div>
    </header>

    <!-- 工具条 -->
    <div class="mg-toolbar">
      <div class="mg-toolbar-group">
        <el-input
          v-model="searchText"
          placeholder="定位实体名称"
          clearable
          size="small"
          class="mg-search"
          @keyup.enter="locateNode"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-button size="small" @click="locateNode">定位</el-button>
      </div>
      <div class="mg-toolbar-divider"></div>
      <div class="mg-toolbar-group">
        <el-button size="small" @click="zoomFit" title="适应窗口">
          <el-icon><FullScreen /></el-icon>
        </el-button>
        <el-button size="small" @click="loadGraph" title="刷新">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </div>

      <div class="mg-toolbar-spacer"></div>

      <!-- 主动记住 -->
      <el-popover placement="bottom" :width="360" trigger="click" popper-class="mg-remember-pop">
        <template #reference>
          <el-button size="small" type="primary" plain :icon="EditPen">主动记住</el-button>
        </template>
        <div class="mg-remember">
          <div class="mg-remember-title">把一段话交给系统萃取成记忆</div>
          <el-input
            v-model="rememberText"
            type="textarea"
            :rows="4"
            placeholder="例如：我在腾讯做后端，熟悉 Python 与 Kubernetes，最近在重构分布式交易系统。"
          />
          <div class="mg-remember-foot">
            <span class="mg-remember-hint">萃取在后台进行，稍后刷新可见</span>
            <el-button size="small" type="primary" :loading="acting" @click="onRemember">记住</el-button>
          </div>
        </div>
      </el-popover>

      <!-- 维护操作 -->
      <el-dropdown trigger="click" @command="onMaintain">
        <el-button size="small" :icon="Operation">维护</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="merge">合并重复实体</el-dropdown-item>
            <el-dropdown-item command="recluster">重新社区聚类</el-dropdown-item>
            <el-dropdown-item divided command="consolidate">记忆巩固（短期→长期）</el-dropdown-item>
            <el-dropdown-item command="reflect">反思（归纳洞察）</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <!-- 图例 / 类型过滤 -->
    <div class="mg-legend">
      <span class="mg-legend-label">显示</span>
      <el-check-tag
        v-for="k in KIND_KEYS"
        :key="k"
        :checked="visibleKinds.has(k)"
        :style="{ '--tag-color': KIND_COLORS[k] }"
        @change="toggleKind(k)"
      >
        <span class="mg-dot" :style="{ background: KIND_COLORS[k] }"></span>
        {{ KIND_LABELS[k] }}<span class="mg-dot-count">{{ kindCounts[k] || 0 }}</span>
      </el-check-tag>
    </div>

    <!-- 画布 + 详情面板 -->
    <div class="mg-body">
      <div ref="canvasRef" class="mg-canvas" @dblclick="onCanvasDblClick"></div>

      <!-- 缩放控制浮层 -->
      <div class="mg-zoom-fab" v-if="g">
        <button class="mg-zoom-btn" title="放大" @click="zoomBy(1.5)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
        </button>
        <button class="mg-zoom-btn" title="缩小" @click="zoomBy(0.67)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M5 12h14"/></svg>
        </button>
        <button class="mg-zoom-btn" title="适应窗口" @click="zoomFit">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9V5a1 1 0 0 1 1-1h4M20 9V5a1 1 0 0 0-1-1h-4M4 15v4a1 1 0 0 0 1 1h4M20 15v4a1 1 0 0 1-1 1h-4"/></svg>
        </button>
      </div>

      <!-- 详情面板 -->
      <transition name="mg-slide">
        <aside v-if="selectedNode" class="mg-detail" tabindex="-1" @keydown.esc="selectedId = null">
          <div class="mg-detail-head">
            <span class="mg-detail-kind" :style="{ '--k-color': KIND_COLORS[selectedNode.kind] || '#888' }">
              {{ KIND_LABELS[selectedNode.kind] || selectedNode.kind }}
            </span>
            <span class="mg-detail-name">{{ selectedNode.name }}</span>
            <button class="mg-detail-close" title="关闭 (Esc)" @click="selectedId = null">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
            </button>
          </div>

          <template v-if="selectedNode.kind === 'Entity'">
            <section class="mg-detail-section">
              <h3 class="mg-detail-section-title">基本信息</h3>
              <div class="mg-row"><span>类型</span><b>{{ selectedNode.type || '—' }}</b></div>
              <div class="mg-row">
                <span>记忆层</span>
                <span class="mg-layer" :class="selectedNode.memory_layer">
                  {{ selectedNode.memory_layer === 'long_term' ? '长期' : '短期' }}
                </span>
              </div>
              <div class="mg-row"><span>重要度</span><b>{{ fmt(selectedNode.importance) }}</b></div>
              <div class="mg-row"><span>提及 / 检索</span><b>{{ selectedNode.mention_count }} / {{ selectedNode.access_count }}</b></div>
            </section>

            <section class="mg-detail-section" v-if="selectedNode.description">
              <h3 class="mg-detail-section-title">描述</h3>
              <p class="mg-desc">{{ selectedNode.description }}</p>
            </section>

            <section class="mg-detail-section" v-if="selectedNode.aliases?.length">
              <h3 class="mg-detail-section-title">别名</h3>
              <div class="mg-tags">
                <span class="mg-chip" v-for="a in selectedNode.aliases" :key="a">{{ a }}</span>
              </div>
            </section>

            <section class="mg-detail-section" v-if="selectedNode.traits?.length">
              <h3 class="mg-detail-section-title">特征</h3>
              <div class="mg-tags">
                <span class="mg-chip mg-chip-trait" v-for="t in selectedNode.traits" :key="t">{{ t }}</span>
              </div>
            </section>

            <section class="mg-detail-section" v-if="selectedNode.core_facts?.length">
              <h3 class="mg-detail-section-title">核心事实</h3>
              <div class="mg-facts">
                <div v-for="f in selectedNode.core_facts" :key="f" class="mg-fact">{{ f }}</div>
              </div>
            </section>

            <section class="mg-detail-section" v-if="selectedNeighbors.length">
              <h3 class="mg-detail-section-title">关联节点 ({{ selectedNeighbors.length }})</h3>
              <div class="mg-neighbors">
                <button
                  v-for="nb in selectedNeighbors"
                  :key="nb.id"
                  class="mg-neighbor"
                  @click="selectNode(nb.id)"
                >
                  <span class="mg-neighbor-dot" :style="{ background: KIND_COLORS[nb.kind] || '#888' }"></span>
                  <span class="mg-neighbor-name">{{ nb.name }}</span>
                  <span class="mg-neighbor-rel">{{ nb.relLabel }}</span>
                </button>
              </div>
            </section>
          </template>
          <template v-else>
            <div class="mg-row"><span>类型</span><b>{{ selectedNode.type || selectedNode.kind }}</b></div>
            <p class="mg-desc">{{ selectedNode.description || selectedNode.name }}</p>
          </template>

          <div class="mg-detail-actions" v-if="selectedNode.kind === 'Entity'">
            <el-button size="small" type="success" plain :loading="acting" @click="onConfirm(selectedNode.id)">确认正确</el-button>
            <el-button size="small" type="danger" plain :loading="acting" @click="onDeleteEntity(selectedNode.id)">删除</el-button>
          </div>
        </aside>
      </transition>

      <!-- 加载 / 空态 -->
      <div v-if="loading" class="mg-overlay">
        <el-icon class="is-loading mg-spin"><Loading /></el-icon>
        <span>加载记忆图谱…</span>
      </div>
      <div v-if="!loading && !hasNodes" class="mg-empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="5" r="2" /><circle cx="5" cy="19" r="2" /><circle cx="19" cy="19" r="2" />
          <path d="M12 7v4M12 11 6 17M12 11l6 6" />
        </svg>
        <p class="mg-empty-title">还没有记忆</p>
        <p class="mg-empty-hint">与 AI 办公搭子对话后会自动萃取记忆；也可点右上「主动记住」添加。</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading, Search, Refresh, EditPen, Operation, FullScreen } from '@element-plus/icons-vue'
import ForceGraph from 'force-graph'
import memoryApi from '@/api/memories'
import { useTheme } from '@/composables/useTheme'

const KIND_KEYS = ['Entity', 'Event', 'Statement', 'Chunk', 'Dialogue']
const KIND_COLORS = {
  Entity: '#155EEF', Event: '#FF8A34', Statement: '#52C41A',
  Chunk: '#9254DE', Dialogue: '#13A8A8',
}
const KIND_LABELS = {
  Entity: '实体', Event: '事件', Statement: '陈述', Chunk: '片段', Dialogue: '对话',
}
const REL_LABEL = {
  HAS_CHUNK: '包含片段', HAS_STATEMENT: '包含陈述', MENTIONS: '提及',
  RELATION: '关系', INVOLVES: '涉及',
}

const canvasRef = ref(null)
let g = null
const graphData = ref(null)
const allNodes = ref([])
const allEdges = ref([])
const loading = ref(false)
const acting = ref(false)
// 仅存 id（基本类型），不把 force-graph 内部 node 对象塞进响应式 ref——
// 否则 Vue 深响应式会代理库内部可变对象，与 force-graph 的 tick/drag 写入互相干扰。
const selectedId = ref(null)
const selectedNode = computed(() => allNodes.value.find(n => n.id === selectedId.value) || null)
const searchText = ref('')
const rememberText = ref('')
const visibleKinds = reactive(new Set(['Entity', 'Event']))
const kindCounts = ref({})
let hoverNode = null
let hoverNeighbors = new Set()

const { isDark } = useTheme()

const entityCount = computed(() => kindCounts.value.Entity || 0)
const eventCount = computed(() => kindCounts.value.Event || 0)
const hasNodes = computed(() => !!(graphData.value && graphData.value.nodes.length))

const statItems = computed(() => [
  { label: '实体', value: entityCount.value, color: KIND_COLORS.Entity },
  { label: '事件', value: eventCount.value, color: KIND_COLORS.Event },
  { label: '关系', value: graphData.value?.edges?.length || 0 },
  { label: '社区', value: graphData.value?.communities?.length || 0 },
])

// 选中节点的关联节点（一跳邻居），用于详情面板导航
const selectedNeighbors = computed(() => {
  if (!selectedId.value) return []
  const id = selectedId.value
  const result = []
  for (const e of allEdges.value) {
    if (e.source === id) {
      const n = allNodes.value.find(n => n.id === e.target)
      if (n) result.push({ ...n, relLabel: e.predicate_surface || e.predicate || REL_LABEL[e.rel] || e.rel || '关联' })
    } else if (e.target === id) {
      const n = allNodes.value.find(n => n.id === e.source)
      if (n) result.push({ ...n, relLabel: e.predicate_surface || e.predicate || REL_LABEL[e.rel] || e.rel || '关联' })
    }
  }
  return result.slice(0, 30)
})

onMounted(async () => {
  await loadGraph()
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if (g) { g._destructor && g._destructor(); g = null }
})

function onKeydown(e) {
  if (e.key === 'Escape' && selectedId.value) {
    selectedId.value = null
  }
}

// 主题切换：重染色（链接/标签/画布）后刷新
watch(isDark, () => {
  if (!g) return
  applyThemeColors()
  requestAnimationFrame(() => g && g.refresh())
})

// 选中变化：模拟冷却后 force-graph 不再每帧重绘，需主动触发一次重绘以显示选中环
watch(selectedId, () => {
  requestAnimationFrame(() => g && g.refresh())
})

// ── 从 CSS 变量读取主题色（画布无法直接用 var）──
function readVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}
let themeColors = {}
function applyThemeColors() {
  themeColors = {
    link: readVar('--slate') || '#64748B',
    linkDim: readVar('--slate-light') || '#9CA3AF',
    label: readVar('--ink-soft') || '#334155',
    canvasBg: readVar('--paper') || '#F5F7FA',
  }
}
function rgba(hex, a) {
  // 仅支持 #RRGGBB
  const h = hex.replace('#', '')
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${a})`
}

async function loadGraph() {
  loading.value = true
  try {
    const res = await memoryApi.graph()
    const data = res.data || {}
    allNodes.value = data.nodes || []
    allEdges.value = data.edges || []
    graphData.value = data
    const counts = {}
    for (const n of allNodes.value) counts[n.kind] = (counts[n.kind] || 0) + 1
    kindCounts.value = counts
    await nextTick()
    render()
  } catch (e) {
    ElMessage.error('加载记忆图谱失败：' + (e?.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

function filteredData() {
  const nodes = allNodes.value.filter(n => visibleKinds.has(n.kind))
  const ids = new Set(nodes.map(n => n.id))
  const links = allEdges.value
    .filter(e => ids.has(e.source) && ids.has(e.target))
    .map(e => ({
      source: e.source, target: e.target,
      rel: e.rel, label: e.predicate_surface || e.predicate || REL_LABEL[e.rel] || e.rel,
    }))
  return { nodes: nodes.map(n => ({ ...n })), links }
}

function nodeRadius(n) {
  if (n.kind === 'Entity') {
    return 4 + Math.min(8, (n.mention_count || 1) * 0.6 + (n.importance || 0.5) * 4)
  }
  if (n.kind === 'Event') return 6
  return 3
}

function isDimmed(n) {
  return hoverNode && n !== hoverNode && !hoverNeighbors.has(n.id)
}

function ensureGraph() {
  if (g || !canvasRef.value) return
  applyThemeColors()
  g = ForceGraph()(canvasRef.value)
    .nodeId('id')
    .nodeLabel(n => n.name)
    .nodeRelSize(4)
    .nodeVal(n => nodeRadius(n))
    .nodeCanvasObject((n, ctx, globalScale) => {
      // 力模拟初始化帧中 n.x/n.y 可能为 NaN，跳过以避免 Canvas API 抛 TypeError
      if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) return
      const r = nodeRadius(n)
      const color = KIND_COLORS[n.kind] || '#888'
      const dim = isDimmed(n)
      const alpha = dim ? 0.18 : 1

      // 外层光晕
      const glow = ctx.createRadialGradient(n.x, n.y, r * 0.6, n.x, n.y, r * 2.8)
      glow.addColorStop(0, rgba(color, dim ? 0.06 : 0.32))
      glow.addColorStop(1, rgba(color, 0))
      ctx.fillStyle = glow
      ctx.beginPath(); ctx.arc(n.x, n.y, r * 2.8, 0, 2 * Math.PI); ctx.fill()

      // 长期记忆：实线环；短期：细弱环
      const longTerm = n.memory_layer === 'long_term'
      ctx.lineWidth = longTerm ? 2 : 1
      ctx.strokeStyle = rgba(color, dim ? 0.12 : (longTerm ? 0.9 : 0.4))
      ctx.beginPath(); ctx.arc(n.x, n.y, r + 1.6, 0, 2 * Math.PI); ctx.stroke()

      // 核心
      ctx.fillStyle = dim ? rgba(color, 0.25) : color
      ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, 2 * Math.PI); ctx.fill()

      // 选中高亮
      if (selectedId.value && n.id === selectedId.value) {
        ctx.strokeStyle = readVar('--accent') || '#2563EB'
        ctx.lineWidth = 2.5
        ctx.beginPath(); ctx.arc(n.x, n.y, r + 4, 0, 2 * Math.PI); ctx.stroke()
      }

      // 标签：实体常显（缩放足够时），或悬停/选中
      const showLabel =
        (n.kind === 'Entity' && globalScale >= 1.1) ||
        n === hoverNode ||
        (selectedId.value && n.id === selectedId.value)
      if (showLabel && n.name) {
        const fs = 11 / globalScale
        ctx.font = `${fs}px ui-sans-serif, system-ui, sans-serif`
        ctx.textAlign = 'center'
        ctx.textBaseline = 'bottom'
        ctx.fillStyle = dim ? rgba(themeColors.linkDim || '#9CA3AF', 0.5) : (themeColors.label || '#334155')
        ctx.fillText(n.name, n.x, n.y - r - 3 / globalScale)
      }
    })
    .nodePointerAreaPaint((n, color, ctx) => {
      if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) return
      // 命中区：比可见半径略大，保证小节点好点选
      const r = nodeRadius(n) + 5
      ctx.fillStyle = color
      ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, 2 * Math.PI); ctx.fill()
    })
    .linkLabel(l => l.label)
    .linkColor(() => rgba(themeColors.link || '#64748B', 0.4))
    .linkWidth(() => 1)
    .linkDirectionalArrowLength(4)
    .linkDirectionalArrowRelPos(1)
    .linkDirectionalArrowColor(() => rgba(themeColors.link || '#64748B', 0.6))
    // 关系方向粒子流，让有向边"活"起来
    .linkDirectionalParticles(2)
    .linkDirectionalParticleWidth(2)
    .linkDirectionalParticleSpeed(0.004)
    .linkDirectionalParticleColor(() => rgba(themeColors.link || '#64748B', 0.7))
    .cooldownTicks(200)
    .onNodeHover(n => {
      hoverNode = n || null
      hoverNeighbors = new Set()
      if (n) {
        for (const e of allEdges.value) {
          if (e.source === n.id) hoverNeighbors.add(e.target)
          if (e.target === n.id) hoverNeighbors.add(e.source)
        }
      }
      canvasRef.value.style.cursor = n ? 'pointer' : null
      // 用 rAF 延迟刷新，避免在 force-graph 事件回调内同步重入绘制导致卡死
      requestAnimationFrame(() => g && g.refresh())
    })
    .onNodeClick(n => { selectedId.value = n.id })
    .onNodeDrag(n => { /* force-graph 内部已处理拖拽位置 */ })
    .onNodeDragEnd(() => { requestAnimationFrame(() => g && g.refresh()) })
}

function render() {
  ensureGraph()
  if (!g) return
  applyThemeColors()
  const data = filteredData()
  const n = data.nodes.length
  g.graphData(data)
  g.d3Force('charge').strength(n > 60 ? -420 : n > 25 ? -320 : -240)
  g.d3Force('link').distance(70)
}

function toggleKind(k) {
  if (visibleKinds.has(k)) visibleKinds.delete(k)
  else visibleKinds.add(k)
  render()
}

function zoomFit() { g && g.zoomToFit(400, 40) }

function zoomBy(factor) {
  if (!g) return
  const currentZoom = g.zoom()
  g.zoom(currentZoom * factor, 300)
}

function locateNode() {
  if (!g || !searchText.value) return
  const q = searchText.value.trim().toLowerCase()
  const node = allNodes.value.find(n => (n.name || '').toLowerCase().includes(q))
  if (!node) { ElMessage.info('未找到匹配节点'); return }
  // 用 force-graph 当前渲染坐标定位（allNodes 原始节点无 x/y）
  const cur = g.graphData().nodes.find(n => n.id === node.id)
  g.centerAt(cur ? cur.x : 0, cur ? cur.y : 0, 400)
  g.zoom(2.5, 400)
  selectedId.value = node.id
}

// 双击画布空白处取消选中
function onCanvasDblClick(e) {
  // 如果双击命中节点，force-graph 的 onNodeClick 已触发；这里处理空白
  // 简单取消选中
  if (!e.target.closest('canvas')) return
  // 空白双击不做操作，保留给 force-graph 的默认双击行为（缩放重置）
}

// 从详情面板关联节点跳转
function selectNode(id) {
  selectedId.value = id
  // 定位到该节点
  if (g) {
    const cur = g.graphData().nodes.find(n => n.id === id)
    if (cur) {
      g.centerAt(cur.x, cur.y, 400)
      g.zoom(2.5, 400)
    }
  }
}

const fmt = v => (v == null ? '—' : Number(v).toFixed(2))

async function onRemember() {
  const t = rememberText.value.trim()
  if (!t) return
  acting.value = true
  try {
    await memoryApi.remember(t)
    ElMessage.success('已提交萃取，稍后刷新可见')
    rememberText.value = ''
    setTimeout(loadGraph, 4000)
  } catch (e) {
    ElMessage.error('记住失败：' + (e?.response?.data?.detail || e.message))
  } finally { acting.value = false }
}

const MAINTAIN = {
  merge: { fn: memoryApi.mergeDuplicates, ok: '已合并重复实体', err: '合并失败' },
  recluster: { fn: memoryApi.recluster, ok: '聚类完成', err: '聚类失败' },
  consolidate: { fn: memoryApi.consolidate, ok: '记忆巩固完成', err: '巩固失败' },
  reflect: { fn: memoryApi.reflect, ok: '反思完成', err: '反思失败' },
}
function onMaintain(cmd) {
  const m = MAINTAIN[cmd]
  if (!m) return
  act(m.fn, m.ok, m.err)
}
async function act(fn, okMsg, errMsg) {
  acting.value = true
  try {
    await fn()
    ElMessage.success(okMsg)
    setTimeout(loadGraph, 3000)
  } catch (e) {
    ElMessage.error(errMsg + '：' + (e?.response?.data?.detail || e.message))
  } finally { acting.value = false }
}

async function onConfirm(id) {
  acting.value = true
  try {
    await memoryApi.confirmEntity(id)
    ElMessage.success('已确认')
    setTimeout(loadGraph, 1500)
  } catch (e) {
    ElMessage.error('确认失败：' + (e?.response?.data?.detail || e.message))
  } finally { acting.value = false }
}

async function onDeleteEntity(id) {
  try {
    await ElMessageBox.confirm('确认删除该实体及其关系？', '删除记忆实体', { type: 'warning' })
  } catch { return }
  acting.value = true
  try {
    await memoryApi.deleteEntityWithReason(id)
    ElMessage.success('已删除')
    selectedId.value = null
    setTimeout(loadGraph, 1500)
  } catch (e) {
    ElMessage.error('删除失败：' + (e?.response?.data?.detail || e.message))
  } finally { acting.value = false }
}
</script>

<style scoped>
.mg-page {
  position: relative;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--paper);
  padding: var(--space-md) var(--space-lg) var(--space-md);
  gap: var(--space-sm);
  overflow: hidden;
}

/* ── 头部 ── */
.mg-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
  flex-wrap: wrap;
}
.mg-heading {
  display: flex;
  align-items: center;
  gap: 14px;
}
.mg-heading-mark {
  flex-shrink: 0;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  background: var(--accent-soft);
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.08);
}
.mg-heading-mark svg { width: 24px; height: 24px; }
.mg-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--ink);
  letter-spacing: 0.01em;
}
.mg-stats {
  display: flex;
  gap: 8px;
}
.mg-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 6px 16px;
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow-xs);
  min-width: 64px;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.mg-stat:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}
.mg-stat-num { font-size: 18px; font-weight: 700; color: var(--ink); line-height: 1.2; }
.mg-stat-label { font-size: 11px; color: var(--slate); margin-top: 2px; }

/* ── 工具条 ── */
.mg-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 10px 14px;
  background: var(--surface);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-xs);
}
.mg-toolbar-group {
  display: flex;
  align-items: center;
  gap: 6px;
}
.mg-toolbar-divider {
  width: 1px;
  height: 20px;
  background: var(--mist);
  margin: 0 4px;
}
.mg-search { width: 220px; }
.mg-toolbar-spacer { flex: 1; }

/* ── 图例 ── */
.mg-legend {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 8px 14px;
  background: var(--surface);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-xs);
}
.mg-legend-label { color: var(--slate); font-size: 13px; margin-right: 2px; }
.mg-dot {
  display: inline-block;
  width: 9px; height: 9px;
  border-radius: 50%;
  margin-right: 5px;
  vertical-align: middle;
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.15);
}
.mg-dot-count { margin-left: 4px; color: var(--slate-light); font-size: 12px; }
.el-check-tag { --el-color-primary: var(--tag-color); border-radius: var(--radius-sm); }

/* ── 画布 + 详情 ── */
.mg-body {
  flex: 1;
  position: relative;
  min-height: 0;
  display: flex;
  background: var(--surface);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.mg-canvas {
  flex: 1;
  min-width: 0;
  /* 细网点底纹，主题自适应 */
  background-image:
    radial-gradient(circle, rgba(100, 116, 139, 0.10) 1px, transparent 1px);
  background-size: 22px 22px;
  background-color: var(--paper);
}

/* ── 缩放控制浮层 ── */
.mg-zoom-fab {
  position: absolute;
  bottom: 16px;
  left: 16px;
  z-index: 6;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px;
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow-md);
  border: 1px solid var(--mist);
}
.mg-zoom-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--slate);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
}
.mg-zoom-btn:hover {
  background: var(--mist-light);
  color: var(--ink);
}
.mg-zoom-btn svg { width: 16px; height: 16px; }

/* ── 详情面板 ── */
/* 详情面板：浮层覆盖在画布右侧（画布尺寸恒定，选中节点不触发 resize，
   避免 force-graph 指针映射失配导致卡死） */
.mg-detail {
  position: absolute;
  top: 12px;
  right: 12px;
  bottom: 12px;
  width: 320px;
  max-width: 42%;
  overflow-y: auto;
  padding: 16px 18px;
  border: 1px solid var(--mist);
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow-lg);
  z-index: 5;
  outline: none;
}
.mg-detail-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}
.mg-detail-close {
  margin-left: auto;
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--slate);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
}
.mg-detail-close:hover {
  background: var(--mist-light);
  color: var(--ink);
}
.mg-detail-close svg { width: 16px; height: 16px; }
.mg-detail-kind {
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 12px;
  background: var(--k-color, #888);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.12);
  flex-shrink: 0;
}
.mg-detail-name {
  font-weight: 600;
  font-size: 15px;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── 详情面板分节 ── */
.mg-detail-section {
  padding: 10px 0;
  border-top: 1px solid var(--mist);
}
.mg-detail-section:first-of-type {
  border-top: none;
  padding-top: 0;
}
.mg-detail-section-title {
  margin: 0 0 8px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--slate);
}
.mg-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  margin: 7px 0;
}
.mg-row span { color: var(--slate); }
.mg-row b { color: var(--ink-soft); font-weight: 600; }
.mg-layer {
  font-size: 12px;
  padding: 2px 9px;
  border-radius: 10px;
}
.mg-layer.long_term { background: var(--success-soft); color: var(--success); }
.mg-layer.short_term { background: var(--mist-light); color: var(--slate); }
.mg-desc {
  font-size: 13px;
  line-height: 1.65;
  margin: 0;
  color: var(--ink-soft);
}
.mg-tags { display: flex; flex-wrap: wrap; gap: 6px; margin: 0; }
.mg-chip {
  font-size: 12px;
  padding: 2px 9px;
  border-radius: 10px;
  background: var(--mist-light);
  color: var(--ink-soft);
}
.mg-chip-trait { background: rgba(146, 84, 222, 0.12); color: #9254DE; }
.mg-facts { margin: 0; font-size: 13px; color: var(--ink-soft); }
.mg-fact { line-height: 1.65; padding: 3px 0; }

/* ── 关联节点列表 ── */
.mg-neighbors {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.mg-neighbor {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 8px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  cursor: pointer;
  text-align: left;
  font-size: 13px;
  color: var(--ink-soft);
  transition: background 0.15s;
}
.mg-neighbor:hover {
  background: var(--mist-light);
}
.mg-neighbor-dot {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.mg-neighbor-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mg-neighbor-rel {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--slate-light);
}

.mg-detail-actions { display: flex; gap: 8px; margin-top: 14px; }

/* ── 加载 / 空态 ── */
.mg-overlay, .mg-empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  pointer-events: none;
}
.mg-overlay { color: var(--slate); font-size: 14px; }
.mg-spin { width: 22px; height: 22px; }
.mg-empty svg { width: 56px; height: 56px; color: var(--slate-light); opacity: 0.6; }
.mg-empty-title { margin: 4px 0 0; font-size: 16px; font-weight: 600; color: var(--slate); }
.mg-empty-hint { margin: 0; font-size: 13px; color: var(--slate-light); max-width: 360px; text-align: center; }

/* 详情面板滑入 */
.mg-slide-enter-active, .mg-slide-leave-active { transition: transform 0.22s ease, opacity 0.22s ease; }
.mg-slide-enter-from, .mg-slide-leave-to { transform: translateX(12px); opacity: 0; }
</style>

<!-- 主动记住气泡：经 popover 传送至 body，脱离 scoped，单列样式 -->
<style>
.mg-remember-pop.el-popover.el-pure-popper {
  padding: 14px;
  border-radius: var(--radius-md);
}
.mg-remember { display: flex; flex-direction: column; gap: 8px; }
.mg-remember-title { font-size: 13px; font-weight: 600; color: var(--ink); }
.mg-remember-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.mg-remember-hint { font-size: 12px; color: var(--slate); }
</style>

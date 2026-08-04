<template>
  <div class="pdf-viewer">
    <!-- 工具栏 -->
    <div class="pdf-toolbar">
      <div class="toolbar-group">
        <button
          class="toolbar-btn"
          :disabled="page <= 1"
          @click="goPage(page - 1)"
          title="上一页"
        >
          <svg viewBox="0 0 16 16" fill="none"><path d="M10 12L6 8l4-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
        <span class="page-indicator">
          <input
            v-model.number="pageInput"
            class="page-input"
            type="text"
            @keyup.enter="goPage(pageInput)"
            @blur="pageInput = page"
          />
          <span class="page-divider">/</span>
          <span class="page-total">{{ totalPages }}</span>
        </span>
        <button
          class="toolbar-btn"
          :disabled="page >= totalPages"
          @click="goPage(page + 1)"
          title="下一页"
        >
          <svg viewBox="0 0 16 16" fill="none"><path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
      </div>

      <div class="toolbar-divider"></div>

      <div class="toolbar-group">
        <button class="toolbar-btn" @click="zoomOut" :disabled="scale <= 0.5" title="缩小">
          <svg viewBox="0 0 16 16" fill="none"><circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.5"/><path d="M11 11l3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M5 7h4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        </button>
        <span class="zoom-label">{{ Math.round(scale * 100) }}%</span>
        <button class="toolbar-btn" @click="zoomIn" :disabled="scale >= 3" title="放大">
          <svg viewBox="0 0 16 16" fill="none"><circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.5"/><path d="M11 11l3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M7 5v4M5 7h4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        </button>
        <button class="toolbar-btn" @click="resetZoom" title="重置缩放">
          <svg viewBox="0 0 16 16" fill="none"><path d="M4 4h8v8H4z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M4 4l8 8M12 4L4 12" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
        </button>
      </div>
    </div>

    <!-- 画布区 -->
    <div ref="scrollRef" class="pdf-canvas-area">
      <div class="canvas-scroll-inner">
        <canvas ref="canvasRef" class="pdf-canvas"></canvas>
      </div>
      <div v-if="loading" class="pdf-loading">
        <div class="loading-spinner"></div>
        <span>正在加载 PDF…</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import * as pdfjsLib from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.js?url'

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl

const props = defineProps({ src: String })

const canvasRef = ref(null)
const scrollRef = ref(null)
const page = ref(1)
const pageInput = ref(1)
const totalPages = ref(0)
const scale = ref(1.2)
const loading = ref(false)
let pdfDoc = null
let renderTask = null

async function render() {
  if (!pdfDoc || !canvasRef.value) return
  loading.value = true
  try {
    if (renderTask) renderTask.cancel()
    const p = await pdfDoc.getPage(page.value)
    const dpr = window.devicePixelRatio || 1
    const viewport = p.getViewport({ scale: scale.value })
    const ctx = canvasRef.value.getContext('2d')
    // 高分屏适配：canvas 实际像素 = CSS 像素 × dpr
    canvasRef.value.width = Math.floor(viewport.width * dpr)
    canvasRef.value.height = Math.floor(viewport.height * dpr)
    canvasRef.value.style.width = viewport.width + 'px'
    canvasRef.value.style.height = viewport.height + 'px'
    // 将渲染坐标系映射到 dpr 缩放后的画布
    renderTask = p.render({
      canvasContext: ctx,
      viewport,
      transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
    })
    await renderTask.promise
  } catch (e) {
    if (e?.name !== 'RenderingCancelledException') console.error(e)
  } finally {
    loading.value = false
  }
}

async function loadPdf() {
  if (!props.src) return
  loading.value = true
  try {
    if (pdfDoc) { pdfDoc.destroy(); pdfDoc = null }
    // Fetch blob URL to ArrayBuffer - avoids worker CORS issues with blob: URLs
    const res = await fetch(props.src)
    const data = await res.arrayBuffer()
    pdfDoc = await pdfjsLib.getDocument({ data }).promise
    totalPages.value = pdfDoc.numPages
    page.value = 1
    pageInput.value = 1
    scale.value = 1.2
    await nextTick()
    await render()
  } catch (e) {
    console.error('PDF 加载失败:', e)
    loading.value = false
  }
}

function goPage(n) {
  const target = Math.max(1, Math.min(totalPages.value, Number(n) || 1))
  page.value = target
  pageInput.value = target
}

function zoomIn() {
  scale.value = Math.min(3, +(scale.value + 0.2).toFixed(1))
}
function zoomOut() {
  scale.value = Math.max(0.5, +(scale.value - 0.2).toFixed(1))
}
function resetZoom() {
  scale.value = 1.2
}

watch(() => props.src, loadPdf)
watch(page, () => { render(); scrollRef.value?.scrollTo({ top: 0, behavior: 'smooth' }) })
watch(scale, render)
onMounted(loadPdf)
onBeforeUnmount(() => { if (pdfDoc) pdfDoc.destroy() })
</script>

<style scoped>
.pdf-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

/* 工具栏 */
.pdf-toolbar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  background: #1E293B;
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
  flex-shrink: 0;
}

.toolbar-group {
  display: flex;
  align-items: center;
  gap: 2px;
}

.toolbar-divider {
  width: 1px;
  height: 18px;
  background: rgba(255, 255, 255, 0.15);
  margin: 0 6px;
}

.toolbar-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: #94A3B8;
  cursor: pointer;
  transition: all 0.15s ease;
}

.toolbar-btn svg {
  width: 16px;
  height: 16px;
}

.toolbar-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

.toolbar-btn:active:not(:disabled) {
  background: rgba(255, 255, 255, 0.15);
}

.toolbar-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.page-indicator {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #CBD5E1;
  margin: 0 4px;
}

.page-input {
  width: 32px;
  height: 24px;
  text-align: center;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s ease;
}

.page-input:focus {
  border-color: var(--accent);
}

.page-divider {
  color: #64748B;
}

.page-total {
  color: #94A3B8;
  min-width: 20px;
}

.zoom-label {
  font-size: 12px;
  color: #94A3B8;
  min-width: 40px;
  text-align: center;
}

/* 画布区 */
.pdf-canvas-area {
  flex: 1;
  overflow: auto;
  background: #52565B;
  position: relative;
}

.canvas-scroll-inner {
  display: flex;
  justify-content: center;
  min-width: 100%;
  width: fit-content;
  padding: 16px;
  box-sizing: border-box;
}

.pdf-canvas {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  border-radius: 2px;
  flex-shrink: 0;
}

/* 加载态 - 绝对覆盖层，不隐藏 canvas */
.pdf-loading {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #CBD5E1;
  font-size: 14px;
  background: #52565B;
  z-index: 1;
}

.loading-spinner {
  width: 28px;
  height: 28px;
  border: 3px solid rgba(255, 255, 255, 0.2);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .loading-spinner { animation: none; }
  .pdf-canvas-area { scroll-behavior: auto; }
}
</style>

<template>
  <div class="retrieval-gallery">
    <button class="rg-header" @click="expanded = !expanded">
      <span class="rg-icon">{{ isImage ? '📷' : '🔊' }}</span>
      <span class="rg-title">检索到 {{ items.length }} {{ isImage ? '张图片' : '段音频' }}</span>
      <svg class="rg-chevron" :class="{ open: expanded }" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="9 18 15 12 9 6" />
      </svg>
    </button>

    <div v-show="expanded" class="rg-body">
      <!-- 图片：缩略图网格，点击放大 -->
      <div v-if="isImage" class="rg-image-grid">
        <figure v-for="(it, i) in items" :key="i" class="rg-thumb" @click="enlarge(it)">
          <img :src="it.thumb_url || it.url" loading="lazy" :alt="`相似度 ${it.score}`" />
          <figcaption>相似度 {{ it.score }}</figcaption>
        </figure>
      </div>

      <!-- 音频：播放器 + 片段定位 -->
      <div v-else class="rg-audio-list">
        <div v-for="(it, i) in items" :key="i" class="rg-audio-item">
          <audio
            :ref="el => { if (el) audioEls[i] = el }"
            :src="it.url"
            preload="none"
            controls
          />
          <div class="rg-audio-meta">
            <button class="rg-seg-btn" @click="playSegment(i, it)">
              ▶ 播放片段 {{ it.start }}s–{{ it.end }}s
            </button>
            <span class="rg-audio-text">{{ it.text }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 放大 modal -->
    <Teleport to="body">
      <div v-if="enlarged" class="rg-modal" @click="enlarged = null">
        <img :src="enlarged.url" :alt="`相似度 ${enlarged.score}`" />
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onBeforeUnmount } from 'vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
})

const expanded = ref(true)
const enlarged = ref(null)
const audioEls = ref([])
const activeListeners = ref([])

const isImage = computed(() => props.items[0]?.kind === 'image')

const enlarge = (it) => {
  enlarged.value = it
}

const playSegment = (i, it) => {
  const el = audioEls.value[i]
  if (!el) return
  // 清理上一个片段的监听
  activeListeners.value.forEach(({ el: e, fn }) => e.removeEventListener('timeupdate', fn))
  activeListeners.value = []
  try {
    el.currentTime = it.start
  } catch (e) {
    /* 忽略 seek 错误 */
  }
  const onTime = () => {
    if (el.currentTime >= it.end) {
      el.pause()
      el.removeEventListener('timeupdate', onTime)
      activeListeners.value = activeListeners.value.filter(x => x.fn !== onTime)
    }
  }
  el.addEventListener('timeupdate', onTime)
  activeListeners.value.push({ el, fn: onTime })
  el.play().catch(() => {})
}

onBeforeUnmount(() => {
  activeListeners.value.forEach(({ el, fn }) => el.removeEventListener('timeupdate', fn))
  activeListeners.value = []
})
</script>

<style scoped>
.retrieval-gallery {
  margin-top: var(--space-md, 16px);
  border: 1px solid var(--mist, #E8ECF1);
  border-radius: var(--radius-md, 10px);
  background: var(--surface, #FFFFFF);
  overflow: hidden;
}
.rg-header {
  display: flex;
  align-items: center;
  gap: var(--space-sm, 8px);
  width: 100%;
  padding: var(--space-sm, 8px) var(--space-md, 16px);
  background: var(--mist-light, #F1F4F8);
  border: none;
  cursor: pointer;
  font-size: 13px;
  color: var(--ink-soft, #334155);
}
.rg-header:hover { background: var(--mist, #E8ECF1); }
.rg-icon { font-size: 15px; }
.rg-title { flex: 1; font-weight: 500; }
.rg-chevron { width: 16px; height: 16px; transition: transform var(--transition, 0.2s); }
.rg-chevron.open { transform: rotate(90deg); }

.rg-body {
  max-height: 280px;
  overflow: auto;
  padding: var(--space-sm, 8px);
}

.rg-image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: var(--space-sm, 8px);
}
.rg-thumb {
  margin: 0;
  cursor: zoom-in;
  border-radius: var(--radius-sm, 6px);
  overflow: hidden;
  background: var(--mist, #E8ECF1);
  box-shadow: var(--shadow-xs, 0 1px 2px rgba(0,0,0,0.05));
  transition: transform var(--transition, 0.2s);
}
.rg-thumb:hover { transform: scale(1.04); }
.rg-thumb img {
  width: 100%;
  height: 96px;
  object-fit: cover;
  display: block;
}
.rg-thumb figcaption {
  font-size: 11px;
  color: var(--slate, #64748B);
  padding: 2px 6px;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rg-audio-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-md, 16px);
}
.rg-audio-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs, 4px);
  padding: var(--space-sm, 8px);
  border-radius: var(--radius-sm, 6px);
  background: var(--mist-light, #F1F4F8);
}
.rg-audio-item audio { width: 100%; height: 34px; }
.rg-audio-meta {
  display: flex;
  align-items: center;
  gap: var(--space-sm, 8px);
  font-size: 12px;
  flex-wrap: wrap;
}
.rg-seg-btn {
  flex-shrink: 0;
  padding: 3px 10px;
  border-radius: 20px;
  border: 1px solid var(--mist, #E8ECF1);
  background: var(--accent-soft, #EFF6FF);
  color: var(--accent, #2563EB);
  font-size: 12px;
  cursor: pointer;
  transition: all var(--transition, 0.2s);
}
.rg-seg-btn:hover { background: var(--accent, #2563EB); color: #fff; }
.rg-audio-text {
  color: var(--slate, #64748B);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rg-modal {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  padding: var(--space-lg, 24px);
  cursor: zoom-out;
}
.rg-modal img {
  max-width: 92vw;
  max-height: 90vh;
  border-radius: var(--radius-md, 10px);
  box-shadow: var(--shadow-lg, 0 10px 30px rgba(0,0,0,0.3));
}
</style>

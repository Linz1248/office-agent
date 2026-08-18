<template>
  <div ref="containerRef" class="markdown-body" @click="handleClick">
    <span v-html="html"></span>
    <span v-if="streaming" class="streaming-cursor"></span>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { renderMarkdown, CODE_PLACEHOLDER_PREFIX, decodeHtmlEntities } from '@/utils/markdown'

const props = defineProps({
  content: { type: String, default: '' },
  streaming: { type: Boolean, default: false },
})

const containerRef = ref(null)

const html = computed(() => renderMarkdown(props.content))

function handleClick(e) {
  const copyBtn = e.target.closest(`.${CODE_PLACEHOLDER_PREFIX}__copy`)
  if (!copyBtn) return

  const encoded = copyBtn.getAttribute('data-code') || ''
  const rawCode = decodeHtmlEntities(encoded)

  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(rawCode).then(() => flashCopied(copyBtn))
  } else {
    // fallback
    const ta = document.createElement('textarea')
    ta.value = rawCode
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try { document.execCommand('copy'); flashCopied(copyBtn) } catch {}
    document.body.removeChild(ta)
  }
}

function flashCopied(btn) {
  const old = btn.textContent
  btn.textContent = '已复制'
  btn.classList.add('is-copied')
  setTimeout(() => {
    btn.textContent = old
    btn.classList.remove('is-copied')
  }, 1200)
}

onMounted(() => {})
onBeforeUnmount(() => {})
</script>

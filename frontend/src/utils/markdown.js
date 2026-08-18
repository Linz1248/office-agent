import { marked } from 'marked'
import hljs from 'highlight.js/lib/common'
import DOMPurify from 'dompurify'

// 按需注册常用语言（highlight.js/lib/common 已含 40+ 语言，足够 AI 对话场景）
// 如需更多语言，可改为 import hljs from 'highlight.js'

const CODE_PLACEHOLDER_PREFIX = 'md-code-block'

// 自定义渲染器：代码块加语言标签 + 复制按钮 + 语法高亮
const renderer = {
  code({ text, lang }) {
    const language = (lang || '').trim()
    const validLang = language && hljs.getLanguage(language) ? language : 'plaintext'
    let highlighted
    try {
      highlighted = hljs.highlight(text, { language: validLang }).value
    } catch {
      highlighted = escapeHtml(text)
    }

    // 转义原始代码，存入 data-code 供复制按钮读取
    const escapedCode = escapeHtml(text)
    const langLabel = language || validLang

    return `<div class="${CODE_PLACEHOLDER_PREFIX}">
      <div class="${CODE_PLACEHOLDER_PREFIX}__header">
        <span class="${CODE_PLACEHOLDER_PREFIX}__lang">${escapeHtml(langLabel)}</span>
        <button class="${CODE_PLACEHOLDER_PREFIX}__copy" data-code="${escapedCode}" type="button">复制</button>
      </div>
      <pre><code class="hljs language-${escapeHtml(validLang)}">${highlighted}</code></pre>
    </div>`
  },
}

marked.use({ breaks: true, gfm: true, renderer })

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function decodeHtmlEntities(str) {
  const txt = document.createElement('textarea')
  txt.innerHTML = str
  return txt.value
}

/**
 * 将 Markdown 文本渲染为安全的 HTML 字符串。
 * - marked 解析（GFM、breaks）
 * - highlight.js 语法高亮 + 复制按钮
 * - DOMPurify 清洗 XSS
 */
export function renderMarkdown(text) {
  if (!text) return ''
  const rawHtml = marked.parse(text)
  return DOMPurify.sanitize(rawHtml, {
    ADD_ATTR: ['target', 'rel'],
  })
}

export { CODE_PLACEHOLDER_PREFIX, decodeHtmlEntities }

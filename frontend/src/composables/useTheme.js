import { ref, watch } from 'vue'

const STORAGE_KEY = 'app-theme'
const THEMES = ['light', 'dark']

const currentTheme = ref('light')
let initialized = false

function applyTheme(theme) {
  const root = document.documentElement
  if (theme === 'dark') {
    root.classList.add('dark')
  } else {
    root.classList.remove('dark')
  }
}

function persistTheme(theme) {
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    /* ignore quota / privacy errors */
  }
}

function readStoredTheme() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored && THEMES.includes(stored)) return stored
  } catch {
    /* ignore */
  }
  return null
}

function initTheme() {
  if (initialized) return
  initialized = true

  const stored = readStoredTheme()
  if (stored) {
    currentTheme.value = stored
  } else {
    currentTheme.value = 'light' // 默认明亮主题
  }
  applyTheme(currentTheme.value)
}

watch(currentTheme, (next) => {
  applyTheme(next)
  persistTheme(next)
})

export function useTheme() {
  // 确保在使用前已初始化（对非入口调用的组件也安全）
  initTheme()

  const isDark = ref(currentTheme.value === 'dark')

  watch(currentTheme, (next) => {
    isDark.value = next === 'dark'
  })

  function setTheme(theme) {
    if (!THEMES.includes(theme)) return
    currentTheme.value = theme
  }

  function toggleTheme() {
    setTheme(currentTheme.value === 'dark' ? 'light' : 'dark')
  }

  return {
    theme: currentTheme,
    isDark,
    setTheme,
    toggleTheme,
  }
}

export { initTheme }

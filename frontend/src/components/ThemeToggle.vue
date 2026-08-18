<template>
  <button
    class="theme-toggle"
    :class="{ 'is-dark': isDark }"
    @click="toggleTheme"
    :title="isDark ? '切换到明亮主题' : '切换到暗黑主题'"
    :aria-label="isDark ? '切换到明亮主题' : '切换到暗黑主题'"
  >
    <svg class="icon icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
    </svg>
    <svg class="icon icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  </button>
</template>

<script setup>
import { useTheme } from '@/composables/useTheme'

const { isDark, toggleTheme } = useTheme()
</script>

<style scoped>
.theme-toggle {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  border: 1px solid var(--mist);
  background: var(--surface);
  color: var(--ink-soft);
  cursor: pointer;
  outline: none;
  box-shadow: var(--shadow-xs);
  transition: color 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease, transform 0.2s ease;
}

.theme-toggle:hover {
  color: var(--accent);
  border-color: var(--accent);
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}

.theme-toggle:active {
  transform: translateY(0);
}

.icon {
  position: absolute;
  width: 19px;
  height: 19px;
  transition: opacity 0.3s ease, transform 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.icon-sun {
  color: #F59E0B;
  opacity: 1;
  transform: rotate(0) scale(1);
}

.icon-moon {
  color: #64748B;
  opacity: 0;
  transform: rotate(-90deg) scale(0.5);
}

.theme-toggle.is-dark .icon-sun {
  opacity: 0;
  transform: rotate(90deg) scale(0.5);
}

.theme-toggle.is-dark .icon-moon {
  opacity: 1;
  transform: rotate(0) scale(1);
  color: var(--accent);
}
</style>

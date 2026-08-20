<template>
  <button
    class="theme-toggle"
    :class="{ 'is-dark': isDark, 'is-collapsed': collapsed }"
    @click="toggleTheme"
    :title="isDark ? '切换到明亮主题' : '切换到暗黑主题'"
    :aria-label="isDark ? '切换到明亮主题' : '切换到暗黑主题'"
  >
    <span class="theme-toggle-icon">
      <svg class="icon icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
      </svg>
      <svg class="icon icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
      </svg>
    </span>
    <span v-if="!collapsed" class="theme-toggle-label">{{ isDark ? '暗黑模式' : '明亮模式' }}</span>
  </button>
</template>

<script setup>
import { useTheme } from '@/composables/useTheme'

defineProps({
  collapsed: { type: Boolean, default: false },
})

const { isDark, toggleTheme } = useTheme()
</script>

<style scoped>
/* 侧边栏内的主题切换：与导航项同语言的整行胶囊控件。
   侧边栏始终为深色底，故用 sidebar 令牌配色，不随明暗主题变底色。 */
.theme-toggle {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 9px 10px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--sidebar-text);
  font-size: 14px;
  cursor: pointer;
  outline: none;
  transition: background var(--transition), color var(--transition);
}

.theme-toggle:hover {
  background: var(--sidebar-hover);
  color: var(--sidebar-text-hover);
}

.theme-toggle:focus-visible {
  box-shadow: 0 0 0 2px var(--sidebar-indicator);
}

.theme-toggle.is-collapsed {
  justify-content: center;
  padding: 10px;
}

/* 图标容器：日月图标绝对定位，旋转+缩放互换 */
.theme-toggle-icon {
  position: relative;
  flex-shrink: 0;
  width: 20px;
  height: 20px;
}

.icon {
  position: absolute;
  inset: 0;
  margin: auto;
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
  color: var(--sidebar-indicator);
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
}

.theme-toggle-label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>

<template>
  <!--
    慧办品牌标识：渐变方底 + 文档页 + 智慧星点。
    variant:
      - solid: 用于浅色背景（侧栏 / 表单 / 欢迎页）
      - glass: 用于深色品牌区（登录/注册左侧），半透明白底 + 蓝色细节
  -->
  <svg
    class="brand-logo"
    :width="size"
    :height="size"
    viewBox="0 0 32 32"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <defs>
      <linearGradient id="huibanGrad" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#3B82F6" />
        <stop offset="1" stop-color="#1D4ED8" />
      </linearGradient>
    </defs>

    <!-- 底座 -->
    <rect
      width="32"
      height="32"
      rx="9"
      :fill="variant === 'glass' ? 'rgba(255,255,255,0.18)' : 'url(#huibanGrad)'"
    />

    <!-- 文档页 -->
    <path
      d="M11 9.2C11 8.0 11.9 7.5 12.9 7.5H18l4 4v11.3c0 1-.8 1.7-1.8 1.7H12.9c-1 0-1.9-.7-1.9-1.7V9.2Z"
      :fill="variant === 'glass' ? 'rgba(255,255,255,0.95)' : '#FFFFFF'"
      fill-opacity="0.96"
    />
    <!-- 折角 -->
    <path
      d="M18 7.5v4h4"
      stroke="#2563EB"
      stroke-width="1.6"
      stroke-linejoin="round"
      fill="rgba(255,255,255,0.9)"
    />
    <!-- 行文线 -->
    <line x1="13.5" y1="16" x2="19" y2="16" stroke="#93C5FD" stroke-width="1.6" stroke-linecap="round" />
    <line x1="13.5" y1="19" x2="17" y2="19" stroke="#93C5FD" stroke-width="1.6" stroke-linecap="round" />

    <!-- 智慧星点 -->
    <path
      d="M23 6.6l.95 2.45 2.45.95-2.45.95-.95 2.45-.95-2.45-2.45-.95 2.45-.95.95-2.45Z"
      fill="#FDE047"
    />
  </svg>
</template>

<script setup>
defineProps({
  size: {
    type: [Number, String],
    default: 32,
  },
  variant: {
    type: String,
    default: 'solid', // 'solid' | 'glass'
  },
})
</script>

<style scoped>
.brand-logo {
  display: block;
  flex-shrink: 0;
}
</style>

<script setup>
import { RouterView, useRouter } from 'vue-router'
import {nextTick, provide, ref, watch} from "vue";
import {useUserStore} from "@/stores/user";

const userStore = useUserStore()
const router = useRouter()

// 监听登录状态：token 过期或手动登出时，SPA 内跳转到登录页（避免 location.href 整页刷新）
const publicPaths = ['/login', '/register']
watch(() => userStore.isLoggedIn, (loggedIn) => {
  if (!loggedIn && !publicPaths.includes(router.currentRoute.value.path)) {
    router.push('/login')
  }
})

userStore.restoreTimer()

const isRouterAlive = ref(true)

// 让页面在不刷新的情况下 重新渲染一次
const reload = () => {
  isRouterAlive.value = false   //先让页面消失
  nextTick(() => {
    isRouterAlive.value = true   //在让页面出现
  })
}
provide('reload', reload)   //供子页面调用

</script>

<template>
  <RouterView v-if="isRouterAlive" :key="$route.fullPath"/>
  <!-- <RouterView /> -->

</template>

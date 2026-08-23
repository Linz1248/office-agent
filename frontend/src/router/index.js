import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from "@/stores/user";

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('../views/Login.vue')
    },
    {
      path: '/register',
      name: 'Register',
      component: () => import('../views/Register.vue')
    },
    {
      path: '/',
      name: 'Layout',
      component: () => import('../views/Layout.vue'),
      redirect: '/agent',
      children: [                   //子路由
        {
          path: 'home',
          name: 'Home',
          component: () => import('../views/HomeView.vue'),
        },
        {
          path: '/document_compare',
          name: 'DocumentCompare',
          component: () => import('../views/DocumentCompare.vue')
        },
        {
          path: '/document_compare_result',
          name: 'DocumentCompareResult',
          component: () => import('../views/DocumentCompareResult.vue')
        },
        {
          path: '/build_image_library',
          name: 'BuildImageLibrary',
          component: () => import('../views/BuildImageLibrary.vue')
        },
        {
          path: '/image_search_image',
          name: 'ImageSearchImage',
          component: () => import('../views/ImageSearchImage.vue')
        },
        {
          path: '/text_search_image',
          name: 'TextSearchImage',
          component: () => import('../views/TextSearchImage.vue')
        },
        {
          path: '/build_audio_library',
          name: 'BuildAudioLibrary',
          component: () => import('../views/BuildAudioLibrary.vue')
        },
        {
          path: '/text_search_audio',
          name: 'TextSearchAudio',
          component: () => import('../views/TextSearchAudio.vue')
        },
        {
          path: '/knowledge_base',
          name: 'KnowledgeBase',
          component: () => import('../views/KnowledgeBase.vue')
        },
        {
          path: '/memory_graph',
          name: 'MemoryGraph',
          component: () => import('../views/MemoryGraph.vue')
        },
        {
          path: '/meetings',
          name: 'Meetings',
          component: () => import('../views/Meetings.vue')
        },
        {
          path: '/skill_market',
          name: 'SkillMarket',
          component: () => import('../views/SkillMarket.vue')
        },
        {
          path: '/my_skills',
          name: 'MySkills',
          component: () => import('../views/MySkills.vue')
        },
        {
          path: '/agent',
          name: 'AgentChat',
          component: () => import('../views/AgentChat.vue')
        },
      ]
    },

  ]
})


// 路由守卫
router.beforeEach((to, from, next) => {
  const store = useUserStore()   //拿到用户对象信息
  const user = store.loginInfo.user
  const hasUser = user && user.id
  const noPermissionPaths = ['/login', '/register']   //无需登录的路由
  if (!hasUser && !noPermissionPaths.includes(to.path)){  //缓存中没有user,用户没有登录,当前跳转的页面不是login时，才跳转到login，否则会发生无限循环跳转
    next('/login')
  } else {
    next()
  }
})

export default router

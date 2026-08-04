import { defineStore } from 'pinia'   // 导入 defineStore

export const useUserStore = defineStore('office-agent', {   // 以 office-agent 作为 key 持久化到缓存中
    state: () => ({
        loginInfo: {},
        expiresAt: 0
    }),
    getters: {
        getUserId() {
          return this.loginInfo.user ? this.loginInfo.user.id : 0    //若有id则返回用户id，否则返回0，防止报错
        },
        getUid() {
            return this.loginInfo.user ? this.loginInfo.user.uid : 0    //若有id则返回用户id，否则返回0，防止报错
        },
        getUser() {
          return this.loginInfo.user || {}
        },
        getBearerToken() {
            return this.loginInfo.access_token ? 'Bearer ' + this.loginInfo.access_token : ''
        },
        getToken() {
            return this.loginInfo.access_token || ""
        },
        isLoggedIn() {
            return !!this.loginInfo.access_token
        }
    },
    actions: {
        setLoginInfo(loginInfo) {
            // 插件会自动同步到 localStorage 的 key 'office-agent'
            this.expiresAt = Date.now() + loginInfo.expiresIn
            this.loginInfo = { ...loginInfo, expireAt: this.expiresAt }
            this.setAutoLogout(loginInfo.expiresIn)
          },
        /// 退出登录
        clearLoginInfo() {
            this.loginInfo = {}
            this.expiresAt = 0
            // 插件会自动同步清空 localStorage
          },
    
        // 私有：token 过期后清除登录状态（跳转由 App.vue 的 watch 处理）
        setAutoLogout(delay) {
            setTimeout(() => {
                this.clearLoginInfo()
            }, delay)
        },

        // 页面刷新时恢复自动登出定时器（persist 插件已自动恢复状态）
        restoreTimer() {
            // 清理旧版本代码遗留的 localStorage 键，避免数据冲突
            localStorage.removeItem('loginInfo')

            if (!this.isLoggedIn) return
            const left = this.expiresAt - Date.now()
            if (isNaN(left) || left <= 0) {
                this.clearLoginInfo()
            } else {
                this.setAutoLogout(left)
            }
        }
    },
    // 开启数据持久化，使用插件pinia-plugin-persistedstate
    persist: true
})

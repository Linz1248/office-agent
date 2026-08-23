// 会议 API 客户端。经网关 /agent/meetings/* 访问 agent 服务的会议路由。
import request from '@/utils/request'

const S = { serverName: 'agent' }

export const meetingApi = {
  // 飞书账号配置
  getAccount: () => request.get('/meetings/account', S),
  saveAccount: (body) => request.put('/meetings/account', body, S),
  deleteAccount: () => request.delete('/meetings/account', S),
  // 用户授权（OAuth user_access_token）
  getOAuthUrl: () => request.get('/meetings/oauth/url', S),
  getOAuthStatus: () => request.get('/meetings/oauth/status', S),
  exchangeCode: (code) => request.post('/meetings/oauth/exchange', { code }, S),
  // 立即同步（自动接收已结束会议的妙记/智能纪要）
  sync: () => request.post('/meetings/sync', {}, { ...S, timeout: 300000 }),
  // 会议与待办
  listMeetings: () => request.get('/meetings', S),
  getMeeting: (meetingId) => request.get(`/meetings/${meetingId}`, S),
  listTodos: (status) =>
    request.get('/meetings/todos', { ...S, params: status ? { status } : {} }),
  updateTodo: (todoId, action) =>
    request.patch(`/meetings/todos/${todoId}`, { action }, S),
  // 应用内通知
  listNotifications: (unread = false) =>
    request.get('/meetings/notifications', { ...S, params: { unread } }),
  markNotificationsRead: (ids = null) =>
    request.post('/meetings/notifications/read', { ids }, S),
  // 通知渠道设置（邮件 / 微信）
  getNotifySettings: () => request.get('/meetings/notify-settings', S),
  saveNotifySettings: (body) => request.put('/meetings/notify-settings', body, S),
  sendTestNotification: () => request.post('/meetings/notify-test', {}, S),
  // 会议知识库检索（独立集合）
  searchKb: (query, top_k = 5) =>
    request.get('/meetings/kb/search', { ...S, params: { query, top_k }, timeout: 120000 }),
}

export default meetingApi

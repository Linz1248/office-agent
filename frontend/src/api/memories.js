// 记忆图谱 API 客户端。经网关 /agent/memories/* 访问 agent 服务的记忆图谱路由。
import request from '@/utils/request'

const S = { serverName: 'agent' }

export const memoryApi = {
  // 主动记住一段文本
  remember: (text) => request.post('/memories/remember', { text }, S),
  // 记忆检索
  search: (query, top_k = 10) =>
    request.post('/memories/search', { query, top_k }, { ...S, timeout: 120000 }),
  // 画像视图（实体按类型分组）
  profile: () => request.get('/memories/profile', S),
  // 记忆审查全景
  reviewOverview: (days = 30) =>
    request.get('/memories/review/overview', { ...S, params: { days } }),
  // 低置信度实体列表
  reviewEntities: (params = {}) =>
    request.get('/memories/review/entities', { ...S, params }),
  // 确认实体
  confirmEntity: (entity_id, reason) =>
    request.post(`/memories/review/${entity_id}/confirm`, { reason }, S),
  // 修正实体
  correctEntity: (entity_id, body) =>
    request.patch(`/memories/review/${entity_id}/correct`, body, S),
  // 删除实体（带理由）
  deleteEntityWithReason: (entity_id, reason) =>
    request.delete(`/memories/review/${entity_id}`, { ...S, params: { reason } }),
  // 社区
  communities: () => request.get('/memories/communities', S),
  communityMembers: (community_id) =>
    request.get(`/memories/communities/${community_id}`, S),
  // 重聚类 / 合并重复 / 巩固 / 反思
  recluster: () => request.post('/memories/recluster', {}, S),
  mergeDuplicates: () => request.post('/memories/merge-duplicates', {}, S),
  consolidate: () => request.post('/memories/consolidate', {}, S),
  reflect: () => request.post('/memories/reflect', {}, S),
  // 洞察
  insights: () => request.get('/memories/insights', S),
  deleteInsight: (insight_id) => request.delete(`/memories/insights/${insight_id}`, S),
  // 全量图谱（节点 + 边 + 社区）
  graph: () => request.get('/memories/graph', S),
  // 单实体一跳子图
  entitySubgraph: (entity_id) =>
    request.get(`/memories/graph/entity/${entity_id}`, S),
  // 事件时间线
  timeline: () => request.get('/memories/timeline', S),
  // 记忆原文列表（审计/溯源）
  list: (page = 1, page_size = 20) =>
    request.get('/memories', { ...S, params: { page, page_size } }),
  getMemory: (memory_id) => request.get(`/memories/${memory_id}`, S),
  deleteMemory: (memory_id) => request.delete(`/memories/${memory_id}`, S),
}

export default memoryApi

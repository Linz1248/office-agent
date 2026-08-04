// 后端统一入口：通过 API 网关（单一端口）访问四个服务。
// VITE_API_BASE 为网关地址，默认本地 8080；四个服务以路径前缀区分：
//   docExtract -> /extract   docCompare -> /compare   multimodel -> /multimodel   agent -> /agent
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8080'

export default {
    docExtract: `${API_BASE}/extract`,
    docCompare: `${API_BASE}/compare`,
    multimodel: `${API_BASE}/multimodel`,
    agent: `${API_BASE}/agent`,
}

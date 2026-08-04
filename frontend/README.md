# frontend

Vue 3 + Vite 5 + Element Plus + Pinia 前端，默认开发端口 `9092`。

## 环境要求

- **Node.js** >= 18（推荐 20 LTS）
- **npm** >= 9

## 安装与运行

```bash
cp .env.example .env        # 按需修改后端地址
npm install
npm run dev                 # http://localhost:9092
```

生产构建与预览：

```bash
npm run build
npm run preview             # http://localhost:4173
```

## 后端地址配置

前端通过 **API 网关**（单一端口）访问后端，四个服务以路径前缀区分。先在 `backend/` 下执行 `./start_all.sh` 启动网关（默认 `8080`），再启动前端。

网关地址在 `config.js` 中读取 Vite 环境变量 `VITE_API_BASE`，默认 `http://localhost:8080`：

| `serverName` | 实际请求前缀 |
| --- | --- |
| `docExtract` | `${VITE_API_BASE}/extract` |
| `docCompare` | `${VITE_API_BASE}/compare` |
| `multimodel` | `${VITE_API_BASE}/multimodel` |
| `agent` | `${VITE_API_BASE}/agent` |

请求统一通过 `src/utils/request.js` 的 axios 实例发送，调用时用 `serverName` 字段指定目标服务，并自动附带 `Authorization` 头。

## 目录

```
frontend/
├── index.html
├── vite.config.js
├── config.js              # 后端地址（环境变量驱动）
├── .env.example
├── public/
└── src/
    ├── main.js
    ├── App.vue
    ├── router/             # 路由 + 登录守卫
    ├── stores/user.js      # Pinia 用户态（持久化）
    ├── utils/request.js    # axios 封装
    ├── components/         # PDF 预览等
    ├── assets/
    └── views/              # 各功能页面
```

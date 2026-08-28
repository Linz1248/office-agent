# 记忆图谱模块（memory_graph）

将 Comet 项目的「图式长期记忆系统」忠实移植为 office-agent 的可拔插模块，替换原有的
`AgenticMemoryMiddleware`（Markdown 文件式记忆）。模块自包含、可按需启停，并以
**AgentScope 中间件**形态接入智能体，符合 AgentScope 2.0 长期记忆中间件规范。

## 一、设计目标与取舍

- **忠实移植**：保留 Comet 的 Neo4j 图存储（原生向量 + cjk 全文 + 图遍历一体）、四层溯源
  （Dialogue→Chunk→Statement→Entity）、受控词表（13 实体类型 / 13 谓词）、12 步萃取流水线、
  两层去重、混合检索、巩固 / 反思 / 聚类 / 人工反馈全部引擎。
- **可拔插**：模块为独立 Python 包 `memory_graph/`，对外暴露 `init_memory_graph()` /
  `is_ready()` / `set_memory_context()` / `MemoryGraphMiddleware` / `router`，与 office-agent
  现有 `kb.py`（知识库 RAG）的接入面完全一致——在 `main.py` 的 `lifespan` 初始化、在
  `_create_agent` 的 `middlewares` 列表里按 `is_ready()` 网关插入。
- **AgentScope 原生集成**：萃取 / 检索使用的 chat 与 embedding 模型由 AgentScope 模型适配
  （`llm_bridge.AgentScopeLLMClient`），复用 office-agent 已有 `llm_config` 配置，无需另配
  provider key（与 ReMe / Mem0 中间件“注入 AgentScope 模型”的官方做法一致）。
- **多租户**：复刻 `kb.py` 的 `ContextVar` 模式，按请求解析 `user_id`，全图按 `user_id` 隔离。
- **双模型架构**：萃取 / 检索走非流式 sidecar 模型，不抢占主推理流式连接（保留
  PROJECT_DOCUMENT 第 394 行的架构约束）。
- **优雅降级 / 确保运行**：Neo4j / PG / Redis / Celery 不可用时 `is_ready()=False`，模块整体
  旁路，智能体其余能力不受影响；萃取派发优先 Celery，worker 未起时自动回退进程内
  asyncio 后台任务，保证“项目正确运行”。

## 二、存储

| 用途 | 实现 | 说明 |
| --- | --- | --- |
| 图谱（实体/陈述/关系/事件/社区/洞察） | **Neo4j** | 原生向量索引（余弦）+ cjk 全文索引 + 唯一约束；按 `id` MERGE 幂等写入。 |
| 来源原文 / 萃取审计 / 人工纠错 / 反思计数 | **SQLite**（默认，可选 PostgreSQL） | `memories`、`memory_corrections`、`mg_counters` 三表；`user_id` 为 String（office-agent 用户名），不外键。SQLAlchemy 双兼容（JSON/JSONB 变体）。 |
| 异步萃取 | 进程内 asyncio（默认）或 **Celery**（可选） | Celery 仅在 `MEMORY_GRAPH_CELERY_ENABLED=true` 时启用（broker=RabbitMQ，result backend=Redis）；默认零队列依赖，中间件直接派发进程内后台任务。 |

### 部署形态

- **无 Docker（默认，推荐给无法装 Docker 的服务器）**：
  唯一必需的外部服务是 Neo4j，一条命令原生部署（本机已实测通过）：
  ```bash
  cd backend
  ./install_memory_infra.sh install   # JDK(按需) + Neo4j + 初始密码 + 内存调优
  ./install_memory_infra.sh start     # 启动（stop/status/restart 同理）
  ```
  脚本细节（均为实测路径）：
  - **安装位置**：root 用户装到 `/opt/office-agent-memory/{neo4j,jdk}`，用专用系统用户
    `neo4j` 运行（Neo4j 拒绝 root；/opt 布局不依赖 /root 权限）；非 root 用户装到
    `backend/infra/` 以当前用户运行。无 systemd 的环境用 `neo4j start` 守护进程方式。
  - **Neo4j 获取**（服务器封锁 dist.neo4j.org 时自动回退）：本地 tarball → 三源下载
    （dist → neo4j.com → 华为云）→ **yum.neo4j.com 社区版 RPM + 纯标准库解包器
    `rpm_extract.py` 重组为 tarball 布局**（无需 rpm/rpm2cpio/cpio）。
  - **JDK 获取**：系统 java(>=17) → 已装目录 → 本地 tarball → Adoptium 21 tarball
    （清华 tuna 镜像 → 官方 API），解压到 `<安装位置>/jdk`，全程不动系统、不依赖 conda。
  - 启动前自动把内存调小（heap 512m/1G，pagecache 512m）并归一化配置目录。
  - `start_all.sh` 会在启动 agent 前 best-effort 拉起 Neo4j，`stop_all.sh` 配套停止。
  审计库默认 SQLite（`backend/agent/memory_graph.db`），反思计数也在 SQLite，无 Redis 依赖。
  Neo4j 不可达时 `is_ready()=False`，模块旁路，对话不受影响。
- **有 Docker 的环境**：`docker compose -f docker-compose.memory-graph.yml up -d`
  （Neo4j/PG/Redis 一起起；PG/Redis 仅在 `MEMORY_GRAPH_AUDIT_BACKEND=postgres` /
  `MEMORY_GRAPH_CELERY_ENABLED=true` 时才被用到）。

向量维度 `embedding_dims` 必须与所用 embedding 模型输出维度一致，默认复用 office-agent
知识库的 Ollama `qwen3-embedding:8b`（4096 维）；可经环境变量覆盖。

## 三、模块结构

```
memory_graph/
  __init__.py            对外门面：init/close/is_ready/set_memory_context/router/MemoryGraphMiddleware
  config.py              pydantic-settings：Neo4j/PG/Redis/embedding/各引擎阈值
  logger.py              get_logger
  llm_bridge.py          AgentScopeLLMClient(chat+embed) + get_clients()
  db/{neo4j,audit_db,redis}.py   audit_db：SQLite 默认/可选 PG；redis 可选
  models/{memory_model,memory_correction_model,counter_model}.py   审计库 ORM（user_id: String）
  core/
    graph_models.py      节点/边 Pydantic 模型与常量
    ontology.py          受控词表
    graph_schema.py      ensure_graph_schema()
    json_utils.py        LLM JSON 健壮解析
    prompt_renderer.py   jinja2 渲染
    tokenizer.py         count_tokens（tiktoken cl100k_base）
    prompts/*.jinja2     萃取/去重/巩固/反思提示词
    preprocessing/{chunker,statement_extractor}.py
    extraction/{models,embedder,triplet_extractor,dedup,orchestrator}.py
    retrieval/{searcher,active_recall}.py
    consolidation/consolidator.py
    reflection/reflector.py
    clustering/label_propagation.py
  repositories/{memory_repository,memory_correction_repository}.py
  repositories/neo4j/{cypher_queries,memory_graph_repository,community_repository}.py
  services/memory_service.py
  schemas/memory_schema.py
  api/memory_controller.py   FastAPI 路由（/memories/*），鉴权依赖由 main 注入
  celery_app.py / tasks/{memory,beat}.py
  middleware.py          MemoryGraphMiddleware(MiddlewareBase) + memory_search 工具
```

## 四、AgentScope 集成

`MemoryGraphMiddleware(MiddlewareBase)`：

- `on_reasoning`：首个推理步前做 active_recall（向量+全文+1跳邻居+洞察），以 `HintBlock`
  注入上下文（`static_control` / `both` 模式）。
- `on_reply`：回复结束后派发萃取（写回），`source=auto`，建 `memories` 行 + Celery /
  asyncio 后台 `run_extraction`。
- `on_system_prompt`：`agent_control` / `both` 模式下追加 `memory_search` 工具使用提示。
- `list_tools`：返回 `MemorySearch` 工具（`agent_control` / `both`）。
- 多租户：`_current_user` ContextVar，`set_memory_context(user_id)` 由 `/chat` 设置。

控制模式 `static_control | agent_control | both` 与官方 ReMe / Mem0 中间件一致。

## 五、API（经网关 `/agent/memories/*`）

remember / search / profile / review(overview/entities/confirm/correct/delete) /
communities / recluster / merge-duplicates / consolidate / reflect / insights /
graph / graph/entity/{id} / timeline / 列表 / 详情 / 删除。

## 六、前端

Vue3 + `vue-force-graph`（与 Comet 的 `react-force-graph-2d` 同为 d3-force 引擎，迁移成本最低）
新增 `MemoryGraph.vue` 视图 + `/memory_graph` 路由 + 侧边栏入口；`memoryApi` 走 axios
`request.js`（serverName=`agent`）。

## 七、启用步骤（无 Docker，默认形态）

1. `cd backend && ./install_memory_infra.sh install && ./install_memory_infra.sh start`
   （安装 JDK 与 Neo4j；start_all.sh 也会在启动 agent 前自动 best-effort 拉起 Neo4j）。
2. 在 `backend/agent/` 环境 `pip install -r memory_graph/requirements.txt`
   （已在 office-agent conda env 安装：neo4j/SQLAlchemy/asyncpg/redis/celery/tiktoken）。
3. （可选）高并发需队列时：`.env` 设 `MEMORY_GRAPH_CELERY_ENABLED=true`，安装并启动
   RabbitMQ（`backend/install_rabbitmq.sh install && ./install_rabbitmq.sh start`），
   再启动 `backend/run_memory_worker.sh`（broker=RabbitMQ，result backend=Redis）。
   不启动也完全可运行--萃取走进程内后台任务。
4. 启动 agent 服务（`./start_all.sh`）即可。默认零额外配置：审计库 SQLite、无 Redis。

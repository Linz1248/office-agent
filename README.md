# office-agent

办公智能体平台，包含一个 Vue3 前端、三个 FastAPI 后端微服务（多模态检索、文档抽取、文档比对）、一个 MCP Server、一个 Agent Service，以及一个统一入口的 API 网关（单端口对外）。

## 目录结构

```
office-agent/
├── backend/
│   ├── multimodel/          # 多模态检索服务（图像/语音/人脸相似度检索）
│   ├── document_extract/    # 文档字段抽取服务（OCR + LLM）
│   ├── document_compare/    # 文档比对服务（合同差异比对）
│   ├── office_mcp/          # MCP Server（将后端能力暴露为 MCP 工具）
│   ├── agent/               # Agent Service（AgentScope ReAct 智能对话）
│   ├── gateway/             # API 网关：单端口统一入口（反向代理）
│   └── start_all.sh         # 一键启动全部后端服务
└── frontend/                # Vue3 + Vite 5 + Element Plus 前端
```

## 服务与端口

| 服务 | 目录 | conda 环境 | 端口 | 说明 |
| --- | --- | --- | --- | --- |
| gateway | `backend/gateway` | `retrieve` | 8080 | 统一入口（对外） |
| multimodel | `backend/multimodel` | `retrieve` | 8000 | CLIP/Whisper/SBERT/InsightFace 检索 |
| document_extract | `backend/document_extract` | `agent` | 9090 | PaddleOCR + contextgem(LLM) 抽取 |
| document_compare | `backend/document_compare` | `agent` | 9900 | RapidOCR + 印章识别 比对 |
| office_mcp | `backend/office_mcp` | `office-agent` | 9091 | MCP Server（工具层） |
| agent | `backend/agent` | `office-agent` | 9093 | AgentScope ReAct 对话服务 |
| frontend | `frontend` | - | 9092 | Vue3 前端（dev） |

> 后端服务分属三个 conda 环境（`retrieve` / `agent` / `office-agent`），依赖互不兼容，无法合并为同一进程。通过 **API 网关**在 `8080` 端口统一暴露，前端只需访问网关。

## 环境要求

- **Node.js** >= 18（前端构建需要，推荐 20 LTS）
- **Conda**（后端依赖管理）
- **Ollama**（文档抽取 LLM，默认 `qwen2.5-1m:14b`，地址 `http://localhost:11434`）
- **DeepSeek API Key**（Agent Service 默认 LLM 提供商，可通过环境变量切换）

## 快速开始

### 1. 后端（一键启动，统一端口）

```bash
cd backend
./start_all.sh            # 启动全部后端服务，统一对外 http://localhost:8080
```

`start_all.sh` 会依次启动 6 个服务：

| 网关路径前缀 | 内部服务 | 内部端口 |
| --- | --- | --- |
| `/multimodel` | multimodel | 8000 |
| `/extract` | document_extract | 9090 |
| `/compare` | document_compare | 9900 |
| `/agent` | agent | 9093 |

MCP Server（端口 9091）不通过网关暴露，仅供 Agent Service 内部调用。

按 `Ctrl+C` 停止全部；日志在 `backend/logs/`。环境变量可覆盖端口、环境名和 LLM 配置，详见 `backend/README.md`。

> 如需单独调试某个服务，可在对应目录用 `uvicorn main:app --port <port>` 启动，详见各服务 `README.md`。

### 2. 前端

```bash
cd frontend
cp .env.example .env        # 默认指向网关 http://localhost:8080
npm install
npm run dev                 # http://localhost:9092
```

生产构建：`npm run build`，预览：`npm run preview`。

## 模型与数据资产

为使项目开箱即用，运行所需的模型权重与样例数据已随项目一并放入：

- `backend/multimodel/models/`：Chinese-CLIP `ViT-B-16`、insightface `buffalo_l`
- `backend/multimodel/repositories/`：样例图像 / 音频 / 转写文本 / 缩略图
- `backend/multimodel/indices/`：已构建的 FAISS 索引及 meta
- `backend/document_extract/pretrained_models/`：PaddleOCR PPStructureV3 各子模块 + sat 段落切分模型
- `backend/document_extract/data/`、`backend/document_compare/data/`：样例 PDF

## 环境变量配置

项目通过 `.env` 文件管理 API Key 等敏感信息。`start_all.sh` 启动时会自动加载项目根目录的 `.env` 文件。

**快速配置：**

```bash
cp .env.example .env    # 复制模板
# 编辑 .env，填入 API Key 等信息
./backend/start_all.sh  # 自动加载 .env
```

> `.env` 已在 `.gitignore` 中忽略，不会泄露到版本库。模板见 [`.env.example`](.env.example)。

### 环境变量一览

| 环境变量 | 说明 | 默认值 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥（默认提供商） | 空（必须设置） |
| `OPENAI_API_KEY` | OpenAI API 密钥 | 空 |
| `DASHSCOPE_API_KEY` | DashScope API 密钥 | 空 |
| `OLLAMA_API_KEY` | Ollama API 密钥 | `ollama` |
| `DOC_EXTRACT_SECRET_KEY` | JWT 签名密钥（Agent 与 document_extract 共享） | `document-extract-key` |
| `SERVICE_ACCOUNT_PASSWORD` | document_extract 服务账号密码 | `123456` |

## 备注

- 各服务的 `users.db`（含初始 admin 账号）位于 `backend/document_extract/users.db`，迁移/重置时请保留或重新初始化。
- MCP Server 直连内部服务（不走网关），避免循环依赖；需要 `SERVICE_ACCOUNT_PASSWORD` 环境变量配置服务账号密码。

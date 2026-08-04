# backend

六个后端服务 + 一个 API 网关。每个服务在自己的目录下独立运行，使用对应的 conda 环境。

> 服务分属三个 conda 环境（`retrieve` / `agent` / `office-agent`），依赖互不兼容，无法合并为同一进程。通过 **API 网关**在单一端口统一暴露，由 `start_all.sh` 一键拉起全部。

## 服务概览

| 服务 | 目录 | conda 环境 | 端口 | 启动方式 |
| --- | --- | --- | --- | --- |
| gateway | `gateway/` | `retrieve` | 8080 | `uvicorn main:app --port 8080` |
| multimodel | `multimodel/` | `retrieve` | 8000 | `uvicorn main:app --port 8000` |
| document_extract | `document_extract/` | `agent` | 9090 | `uvicorn main:app --port 9090` |
| document_compare | `document_compare/` | `agent` | 9900 | `uvicorn main:app --port 9900` |
| office_mcp | `office_mcp/` | `office-agent` | 9091 | `python server.py` |
| agent | `agent/` | `office-agent` | 9093 | `uvicorn main:app --port 9093` |

## 环境准备

```bash
# retrieve 环境（multimodel 服务 + 网关）
conda activate retrieve
pip install -r multimodel/requirements.txt
pip install -r gateway/requirements.txt

# agent 环境（document_extract + document_compare 服务共用）
conda activate agent
pip install -r document_extract/requirements.txt
pip install -r document_compare/requirements.txt

# office-agent 环境（MCP Server + Agent Service 共用）
conda activate office-agent
pip install -r office_mcp/requirements.txt
pip install -r agent/requirements.txt
```

> PyTorch / PaddlePaddle 的 GPU 版本需通过各自的专用索引安装，详见各 `requirements.txt` 顶部注释。

## 一键启动（统一端口，推荐）

```bash
./start_all.sh
```

启动 6 个服务，网关统一对外端口 `8080`：

| 网关路径前缀 | 内部服务 | 内部端口 |
| --- | --- | --- |
| `/multimodel` | multimodel | 8000 |
| `/extract` | document_extract | 9090 |
| `/compare` | document_compare | 9900 |
| `/agent` | agent | 9093 |

MCP Server（端口 9091）不通过网关暴露，仅供 Agent Service 内部调用。

按 `Ctrl+C` 停止全部；日志位于 `logs/`。

### 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `GATEWAY_PORT` | 8080 | 网关端口 |
| `MULTIMODEL_PORT` | 8000 | 多模态检索服务端口 |
| `DOC_EXTRACT_PORT` | 9090 | 文档抽取服务端口 |
| `DOC_COMPARE_PORT` | 9900 | 文档比对服务端口 |
| `OFFICE_MCP_PORT` | 9091 | MCP Server 端口 |
| `AGENT_PORT` | 9093 | Agent Service 端口 |
| `RETRIEVE_ENV` | retrieve | multimodel + gateway 的 conda 环境 |
| `AGENT_ENV` | agent | document_extract + document_compare 的 conda 环境 |
| `GATEWAY_ENV` | retrieve | 网关的 conda 环境 |
| `OFFICE_AGENT_ENV` | office-agent | MCP Server + Agent Service 的 conda 环境 |
| `LLM_PROVIDER` | deepseek | Agent Service 模型提供商（deepseek/openai/dashscope/ollama） |
| `DEEPSEEK_API_KEY` | - | DeepSeek API 密钥 |
| `SERVICE_ACCOUNT_PASSWORD` | 123456 | MCP Server 访问 document_extract 的服务账号密码 |

## 单独启动（调试用）

在对应目录下执行启动命令（见上方"服务概览"表），以便 `config.py` 正确定位模型与数据目录。

## 配置

每个服务的 `config.py` 集中管理路径、设备、端口等参数，均支持环境变量覆盖。各服务目录的 `README.md` 有详细说明。

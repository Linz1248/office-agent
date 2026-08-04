# document_extract 文档抽取服务

基于 PaddleOCR（PPStructureV3）+ contextgem（LLM）的文档字段抽取，带 OCR 与 LLM 结果缓存。运行在 conda 环境 `agent`，默认端口 `9090`。

## 启动

```bash
conda activate agent
cd backend/document_extract
uvicorn main:app --host 0.0.0.0 --port 9090
```

> 需本机运行 Ollama 并拉取大模型（默认 `myiani/qwen2.5-1m:14b`）。

## 目录

```
document_extract/
├── main.py              # FastAPI 入口（鉴权、上传/删除、抽取、缓存）
├── config.py            # 路径/设备/LLM/鉴权配置
├── pretrained_models/   # PaddleOCR 各子模块 + sat 模型
├── data/                # 样例 PDF 与中间产物（temp.md / prompt.txt）
├── uploads/             # 运行时上传目录（自动创建）
├── users.db             # 用户库（含初始 admin 账号）
└── requirements.txt
```

## 主要接口

- 鉴权：`POST /register`、`POST /login`、`POST /change_password`
- 文件：`POST /doc_upload`、`DELETE /doc_delete/{filename}`
- 抽取：`POST /doc_extract`（支持 `enhance` 增强抽取）
- 测试：`POST /doc_test`

除 `/register`、`/login`、`/doc_test` 外，接口均需 `Authorization: Bearer <token>`。

## 配置（环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DOC_EXTRACT_DEVICE` | `gpu:1` | PaddlePaddle 设备，如 `cpu` / `gpu:0` |
| `DOC_EXTRACT_PORT` | `9090` | 服务端口 |
| `DOC_EXTRACT_PRETRAINED_MODELS` | `./pretrained_models` | OCR 模型根目录 |
| `OLLAMA_API_BASE` | `http://localhost:11434` | Ollama 服务地址 |
| `OLLAMA_MODEL` | `ollama_chat/myaniu/qwen2.5-1m:14b` | LLM 模型名 |
| `DOC_EXTRACT_LLM_TIMEOUT` | `120` | LLM 调用超时（秒） |
| `DOC_EXTRACT_SECRET_KEY` | `document-extract-key` | JWT 签名密钥 |

## 缓存

- `cache.db`（SQLite，WAL 模式）：按文件 SHA256 缓存 OCR 文本，按 `文件哈希 + 字段哈希` 缓存 LLM 抽取结果。模型/提示词变更时递增 `config.CACHE_VERSION` 可令旧缓存自动失效。
- `users.db`：使用 `nolock=1` 连接以兼容 NFS，包含初始 admin 账号（注册新用户需校验 admin 密码），迁移时请保留。

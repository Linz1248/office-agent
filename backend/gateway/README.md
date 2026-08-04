# gateway API 网关

统一入口：在**单一端口**（默认 8080）暴露三个后端服务，通过路径前缀路由并剥离前缀：

| 前缀 | 内部服务 | 内部端口 |
| --- | --- | --- |
| `/multimodel` | multimodel | 8000 |
| `/extract` | document_extract | 9090 |
| `/compare` | document_compare | 9900 |

> 三个服务运行在两个不同的 conda 环境（`retrieve` / `agent`），依赖互不兼容，无法合并为同一进程。网关只做反向代理，不依赖它们的环境，仅需 `fastapi + uvicorn + httpx`（`retrieve` / `agent` 环境均已具备）。

## 单独启动

```bash
conda activate retrieve   # 或 agent
cd backend/gateway
uvicorn main:app --host 0.0.0.0 --port 8080
```

> 需先启动三个内部服务（见上级目录 `start_all.sh` 或各服务 README）。

## 一键启动全部

```bash
cd backend
./start_all.sh          # 启动 3 个服务 + 网关，统一对外 8080
```

## 配置（环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `GATEWAY_PORT` | `8080` | 网关对外端口 |
| `MULTIMODEL_UPSTREAM` | `http://127.0.0.1:8000` | multimodel 内部地址 |
| `DOC_EXTRACT_UPSTREAM` | `http://127.0.0.1:9090` | document_extract 内部地址 |
| `DOC_COMPARE_UPSTREAM` | `http://127.0.0.1:9900` | document_compare 内部地址 |

## 示例

前端或客户端只需访问网关一个地址：

```
http://localhost:8080/extract/login        -> document_extract /login
http://localhost:8080/multimodel/get_images_dir/?include_files=true
http://localhost:8080/compare/compare
```

网关处理跨域（CORS），并流式转发请求体与响应，支持大文件上传与 PDF 下载。

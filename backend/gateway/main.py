"""统一 API 网关：在单一端口暴露三个后端服务。

通过路径前缀路由到各内部服务，并剥离前缀：
  /multimodel/*  ->  http://127.0.0.1:8000/*
  /extract/*     ->  http://127.0.0.1:9090/*
  /compare/*     ->  http://127.0.0.1:9900/*
x
三个服务运行在两个不同的 conda 环境（retrieve / agent），依赖互不兼容，
因此无法合并为同一进程；本网关只做反向代理，不引入它们的依赖，
仅需 fastapi + uvicorn + httpx。
"""
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

import uvicorn

from config import UPSTREAMS, PORT


# 不转发给上游 / 不回传给客户端的 hop-by-hop 头。
# content-length / content-encoding 由代理层重新处理；CORS 由网关统一加。
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "expect",
    "content-length",  # httpx / StreamingResponse 重新计算
    # 上游各自带了 CORS，交给网关的 CORSMiddleware 统一处理，避免重复头
    "access-control-allow-origin",
    "access-control-allow-methods",
    "access-control-allow-headers",
    "access-control-allow-credentials",
    "access-control-expose-headers",
    "access-control-max-age",
}

app = FastAPI(title="office-agent API 网关")

# 网关统一处理跨域；鉴权用的是 Authorization 头而非 Cookie，故 credentials=False
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 复用连接；超时设大以适配 OCR / LLM 等长耗时接口
client = httpx.AsyncClient(
    timeout=httpx.Timeout(300.0, connect=10.0),
    follow_redirects=False,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
)


@app.get("/")
async def root():
    return {"message": "office-agent API 网关", "routes": list(UPSTREAMS.keys())}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy(full_path: str, request: Request):
    parts = full_path.split("/", 1)
    prefix = "/" + parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    upstream = UPSTREAMS.get(prefix)
    if upstream is None:
        return JSONResponse(
            {"detail": f"未知服务前缀: {prefix}（可用: {', '.join(UPSTREAMS.keys())}）"},
            status_code=404,
        )

    # 构造上游 URL，保留 query string
    url = f"{upstream}/{rest}"
    if request.url.query:
        url += f"?{request.url.query}"

    # 转发请求头（剥离 hop-by-hop）
    headers = {
        k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP
    }

    # 流式转发请求体，适合大文件上传
    async def body_stream():
        async for chunk in request.stream():
            yield chunk

    content = None if request.method in ("GET", "HEAD") else body_stream()
    upstream_req = client.build_request(
        request.method, url, headers=headers, content=content
    )

    try:
        resp = await client.send(upstream_req, stream=True)
    except httpx.ConnectError:
        return JSONResponse(
            {"detail": f"上游服务不可达: {prefix}（是否已启动？）"}, status_code=502
        )
    except httpx.ReadTimeout:
        return JSONResponse({"detail": f"上游服务响应超时: {prefix}"}, status_code=504)

    # 转发响应头（剥离 hop-by-hop / CORS）
    resp_headers = {
        k: v for k, v in resp.headers.items() if k.lower() not in HOP_BY_HOP
    }

    async def stream_upstream():
        try:
            async for chunk in resp.aiter_raw():
                yield chunk
        finally:
            await resp.aclose()

    return StreamingResponse(
        stream_upstream(),
        status_code=resp.status_code,
        headers=resp_headers,
    )


@app.on_event("shutdown")
async def shutdown():
    await client.aclose()


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT)

"""API 网关配置。

路径前缀到内部服务地址的映射，以及网关端口。均可通过环境变量覆盖。
"""
import os
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent

# 网关对外端口
PORT = int(os.environ.get("GATEWAY_PORT", "8080"))

# 前缀 -> 内部服务地址（前缀会被剥离后转发）
#   /multimodel/foo  ->  http://127.0.0.1:8000/foo
#   /extract/foo     ->  http://127.0.0.1:9090/foo
#   /compare/foo     ->  http://127.0.0.1:9900/foo
#   /agent/foo       ->  http://127.0.0.1:9093/foo
UPSTREAMS = {
    "/multimodel": os.environ.get(
        "MULTIMODEL_UPSTREAM", "http://127.0.0.1:8000"
    ),
    "/extract": os.environ.get(
        "DOC_EXTRACT_UPSTREAM", "http://127.0.0.1:9090"
    ),
    "/compare": os.environ.get(
        "DOC_COMPARE_UPSTREAM", "http://127.0.0.1:9900"
    ),
    "/agent": os.environ.get(
        "AGENT_UPSTREAM", "http://127.0.0.1:9093"
    ),
}

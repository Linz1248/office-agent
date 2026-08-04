"""Office MCP Server 配置。

通过环境变量配置各后端服务地址和认证信息。
"""
import os
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent

# MCP 服务端口
PORT = int(os.environ.get("OFFICE_MCP_PORT", "9091"))

# 内部服务地址（直连，不走网关，避免循环依赖）
DOC_EXTRACT_URL = os.environ.get("DOC_EXTRACT_URL", "http://127.0.0.1:9090")
DOC_COMPARE_URL = os.environ.get("DOC_COMPARE_URL", "http://127.0.0.1:9900")
MULTIMODEL_URL = os.environ.get("MULTIMODEL_URL", "http://127.0.0.1:8000")

# document_extract 服务账号（用于获取 JWT token）
SERVICE_ACCOUNT_USERNAME = os.environ.get("SERVICE_ACCOUNT_USERNAME", "admin")
SERVICE_ACCOUNT_PASSWORD = os.environ.get("SERVICE_ACCOUNT_PASSWORD", "123456")

# HTTP 请求超时（秒）
HTTP_TIMEOUT = float(os.environ.get("OFFICE_MCP_HTTP_TIMEOUT", "300"))

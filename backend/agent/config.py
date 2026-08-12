"""
Agent Service 配置
"""
import os
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent

# 服务端口
PORT = 9093

# 统一 LLM 配置
# 通过 LLM_PROVIDER 切换模型提供商: deepseek / openai / dashscope / ollama
LLM_PROVIDER = "deepseek"

# DeepSeek 配置（默认）
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# OpenAI 配置
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = "gpt-4o"
OPENAI_BASE_URL = "https://api.openai.com/v1"

# DashScope 配置
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
DASHSCOPE_MODEL = "qwen-max"

# Ollama 配置
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "ollama")
OLLAMA_MODEL = "qwen2.5:14b"
OLLAMA_BASE_URL = "http://localhost:11434/v1"

# 模型生成参数
LLM_TEMPERATURE = 0.8
LLM_MAX_TOKENS = 8192
# 是否启用思维链（DeepSeek thinking 模式，前端展示推理过程）
LLM_THINKING_ENABLE = True

# MCP Server 配置
OFFICE_MCP_URL = "http://127.0.0.1:9091/mcp"

# 文档服务地址（直连，不走网关，与 office_mcp 保持一致）
DOC_EXTRACT_URL = os.environ.get("DOC_EXTRACT_URL", "http://127.0.0.1:9090")
DOC_COMPARE_URL = os.environ.get("DOC_COMPARE_URL", "http://127.0.0.1:9900")

# document_extract 服务账号（用于上传文件时获取 JWT token）
SERVICE_ACCOUNT_USERNAME = os.environ.get("SERVICE_ACCOUNT_USERNAME", "admin")
SERVICE_ACCOUNT_PASSWORD = os.environ.get("SERVICE_ACCOUNT_PASSWORD", "123456")

# Agent 最大迭代次数（ReAct 循环）
AGENT_MAX_ITERS = 20

# 鉴权
JWT_SECRET_KEY = os.environ.get("DOC_EXTRACT_SECRET_KEY", "document-extract-key")
JWT_ALGORITHM = "HS256"

# 会话与上下文管理
# 会话状态持久化 SQLite 数据库路径
SESSION_DB_PATH = SERVICE_ROOT / "sessions.db"

# 上下文压缩配置
# trigger_ratio: token 用量超过该比例 × 模型上下文长度时触发压缩（上限 0.9）
# reserve_ratio: 压缩后保留的最近消息 token 比例
# tool_result_limit: 单条工具结果的最大 token 数，超出则截断
CONTEXT_TRIGGER_RATIO = 0.8
CONTEXT_RESERVE_RATIO = 0.1
TOOL_RESULT_LIMIT = 4096

# 感知环境配置（InjectionConfig）
# timezone: 注入时间的时区
# time_interval: 距上次时间记录超过该小时数时刷新注入
# context_buffer_ratio: 压缩阈值前的缓冲区比例，须小于 trigger_ratio
INJECTION_TIMEZONE = "Asia/Shanghai"
INJECTION_TIME_INTERVAL = 1.0
INJECTION_CONTEXT_BUFFER_RATIO = 0.2

# 上下文卸载配置（LocalWorkspace）
# 被压缩的消息与截断的工具结果持久化到此目录，供智能体按需回查
WORKSPACE_DIR = SERVICE_ROOT / "workspace"

# 长期记忆配置（AgenticMemoryMiddleware）
# 每个用户拥有独立子目录，跨会话持久化偏好、决策与知识（Markdown 文件）
MEMORY_DIR = SERVICE_ROOT / "memory"

# 临时上传目录（用户上传的图片文件，供图搜图工具使用）
UPLOAD_DIR = SERVICE_ROOT / "uploads"

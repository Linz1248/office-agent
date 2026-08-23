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

# 定时清理保留期（单位：天），均可经环境变量覆盖；置 0 关闭对应清理
# - CLEANUP_FILE_DAYS：agent/uploads/ 图片（file_path）与 workspace/ 任务草稿目录保留期
# - CLEANUP_SESSION_DAYS：sessions.db 会话行（按 updated_at，epoch 毫秒）保留期
# 活跃会话（分钟级）远短于保留期（天级），故不会被误删。
# 长期记忆 memory/ 永不清理（见 cleanup.py，与 workspace 同级但不在清理范围）。
CLEANUP_FILE_DAYS = float(os.environ.get("CLEANUP_FILE_DAYS", "7"))
CLEANUP_SESSION_DAYS = float(os.environ.get("CLEANUP_SESSION_DAYS", "30"))
CLEANUP_INTERVAL_SECONDS = float(os.environ.get("CLEANUP_INTERVAL_SECONDS", "3600"))

# ── 个人知识库（RAG）配置 ─────────────────────────────────────
# 复用 document_extract 抽取全文（PDF/Word/Excel/图片 OCR），本地分块 + 嵌入 + 向量检索。
# 通过自定义 search_knowledge 工具（注册到 Agent Toolkit）实现 agentic RAG，
# Agent 自主决定何时检索用户个人知识库与全平台公开文档。
#
# 嵌入模型：默认本地 Ollama qwen3-embedding:8b（中英双语，4096 维），需先 `ollama pull qwen3-embedding:8b`。
# 若 Ollama 或该模型不可用，知识库功能优雅降级（不注册 search_knowledge，KB 接口返回 503），
# 其余对话/办公能力不受影响。
KB_EMBEDDING_PROVIDER = os.environ.get("KB_EMBEDDING_PROVIDER", "ollama")
KB_OLLAMA_HOST = os.environ.get("KB_OLLAMA_HOST", "http://localhost:11434")
KB_EMBEDDING_MODEL = os.environ.get("KB_EMBEDDING_MODEL", "qwen3-embedding:8b")
KB_EMBEDDING_DIM = int(os.environ.get("KB_EMBEDDING_DIM", "4096"))

# 向量库：Qdrant 本地持久化（进程内 on-disk，无需额外服务）
KB_QDRANT_PATH = SERVICE_ROOT / "kb_qdrant"
KB_COLLECTION = os.environ.get("KB_COLLECTION", "office_kb")

# 知识库元数据 SQLite（文档清单 / 共享状态 / 索引状态 / 全文缓存）
KB_DB_PATH = SERVICE_ROOT / "kb.db"
# 原始文件存放目录（用户上传文档原件，便于复检；删除文档时一并清除，不自动清理）
KB_FILES_DIR = SERVICE_ROOT / "kb_files"

# 分块与检索参数
KB_CHUNK_SIZE = int(os.environ.get("KB_CHUNK_SIZE", "512"))
KB_CHUNK_OVERLAP = int(os.environ.get("KB_CHUNK_OVERLAP", "64"))
KB_SEARCH_TOP_K = int(os.environ.get("KB_SEARCH_TOP_K", "5"))
KB_SCORE_THRESHOLD = float(os.environ.get("KB_SCORE_THRESHOLD", "0.3"))

# ── Skill 系统（Markdown 指令集 + 内网共享市场）─────────────────────
# 基于 AgentScope SDK 的 Skill 机制（SkillLoaderBase），用户创建 Markdown
# 指令文件（SKILL.md），智能体在对话中通过 SDK 内置 Skill 查看器按需读取。
# 可公开到内网市场，其他用户安装后获得独立副本（快照拷贝），不受原作者删除影响。
SKILL_DIR = SERVICE_ROOT / "skills"
SKILL_DB_PATH = SERVICE_ROOT / "skill.db"

# ── 飞书会议（自动接收 / 子 agent 分析 / 待办提醒）──────────────────
# 每个用户在「飞书会议」页配置自己的飞书自建应用凭证（App ID/App Secret）
# 与本人 open_id：应用凭证按用户隔离，且检索按参会人过滤，双重保证只
# 接收属于自己的会议数据。后台定时轮询已结束会议，自动拉取妙记/智能纪要，
# 由会议分析子 agent 生成摘要与待办，正文写入独立的会议知识库集合。
FEISHU_BASE_URL = os.environ.get("FEISHU_BASE_URL", "https://open.feishu.cn")

# 用户授权（user_access_token，OAuth）回调地址：本地/内网部署默认走网关回调，
# 浏览器授权后自动跳回 /agent/meetings/oauth/callback 完成换 token（无需公网，
# 因回调由用户浏览器发起而非飞书服务器）。须在飞书应用「安全设置 → 重定向 URL」
# 登记同一地址；若飞书拒绝 http://localhost，可改用「手动授权码」并在前端粘贴 code。
FEISHU_OAUTH_REDIRECT_URI = os.environ.get(
    "FEISHU_OAUTH_REDIRECT_URI",
    "http://localhost:8080/agent/meetings/oauth/callback",
)

# 会议模块元数据 SQLite（账号配置 / 会议 / 待办 / 通知）
MEETING_DB_PATH = SERVICE_ROOT / "meetings.db"
# 会议知识库向量存储（与个人知识库 kb_qdrant 物理隔离，互不混杂数据）
MEETING_QDRANT_PATH = SERVICE_ROOT / "meetings_qdrant"
MEETING_COLLECTION = os.environ.get("MEETING_COLLECTION", "office_meetings")
# 复用 KB 的 Ollama 嵌入模型配置（保证会议库与个人库嵌入一致可检索）
MEETING_SEARCH_TOP_K = int(os.environ.get("MEETING_SEARCH_TOP_K", "5"))

# 同步轮询：间隔秒数与回看天数（会议记录 API 支持最近 90 天，回看窗口
# 用于补齐服务停机期间错过的已结束会议）
MEETING_SYNC_INTERVAL = float(os.environ.get("MEETING_SYNC_INTERVAL", "300"))
MEETING_SYNC_LOOKBACK_DAYS = int(os.environ.get("MEETING_SYNC_LOOKBACK_DAYS", "3"))
# 待办提醒检查间隔（秒）与提前提醒分钟数
MEETING_REMINDER_INTERVAL = float(os.environ.get("MEETING_REMINDER_INTERVAL", "60"))
MEETING_REMIND_LEAD_MINUTES = int(os.environ.get("MEETING_REMIND_LEAD_MINUTES", "30"))
# 会议结束后多久仍无妙记正文即判定为「无纪要」并标记 empty（分钟）。
# 飞书智能纪要会后约 1 分钟内生成；10~15 分钟仍为空基本意味着该会议未
# 生成纪要（未开 AI 纪要/录制、无有效发言、或额度用尽）。默认 30 分钟
# 留足余量，避免对生成稍慢的长会议误判；此前一直显示「待分析」会让人
# 误以为卡死。设大可更保守，但不宜再用旧的 24h（那样无纪要的会议会
# 白白停在「待分析」一整天）。
MEETING_EMPTY_AFTER_MINUTES = int(os.environ.get("MEETING_EMPTY_AFTER_MINUTES", "30"))

# ── 外部通知渠道（可选，用户在设置中按需启用）────────────────────
# 邮件：全局 SMTP 服务器配置（服务管理员在 .env 配置），用户只填收件地址
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "") or os.environ.get("SMTP_USER", "")
SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "true").lower() != "false"

# 微信：Server酱（https://sct.ftqq.com）SendKey，用户在设置中自行填入，
# 推送到个人微信「Server酱」服务号。
WECHAT_SEND_API = "https://sctapi.ftqq.com"

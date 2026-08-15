"""AI 办公搭子 Agent Service。

基于 AgentScope 2.0 框架，通过 Agent + MCP 工具实现智能办公助手。
对外暴露:
  - POST /chat                 : 与 Agent 对话（SSE 流式响应，含思维链）
  - POST /chat/stop            : 停止当前会话的 Agent 输出
  - POST /upload               : 上传 PDF 文件到文档抽取与比对服务
  - DELETE /sessions/{sid}     : 删除指定会话的持久化上下文
  - GET  /health               : 健康检查

上下文管理:
  - 每个会话拥有独立的 AgentState（工作记忆），包含对话上下文与压缩摘要。
  - AgentState 序列化为 JSON 存入 SQLite 数据库，重新打开历史会话时自动恢复。
  - 感知环境：通过 InjectionConfig 在每次推理前注入运行时状态（时间、任务、上下文用量），
    让智能体持续感知环境变化。
  - 上下文压缩：通过 ContextConfig 配置，长对话自动摘要以保持在模型窗口内。
  - 上下文卸载：通过 LocalWorkspace 作为 offloader，被压缩的消息与截断的工具结果
    持久化到磁盘，智能体可按需回查。
  - 会话以 (user_id, session_id) 复合主键隔离，用户间互不可见。

长期记忆:
  - 通过 AgenticMemoryMiddleware 实现：智能体自主将用户偏好、历史决策与知识
    沉淀为 Markdown 文件，跨会话复用。
  - 每个用户拥有独立的记忆工作目录（MEMORY_DIR/<user_id>），用户间互不可见。
  - 中间件将 MEMORY.md 索引注入系统提示，并在每次回复前异步检索相关记忆文件
    以 HintBlock 形式插入上下文；检索使用独立的非流式/非思维链模型，避免与主
    推理流式连接冲突。
  - 智能体通过 Read/Write/Edit 工具自主创建、读取与修订记忆文件。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiosqlite
import httpx
import jwt as pyjwt
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import uvicorn

from agentscope.agent import (
    Agent,
    ReActConfig,
    ContextConfig,
    InjectionConfig,
)
from agentscope.message import Msg, UserMsg
from agentscope.mcp import MCPClient, HttpMCPConfig
from agentscope.middleware import AgenticMemoryMiddleware, MiddlewareBase
from agentscope.state import AgentState
from agentscope.permission import PermissionContext, PermissionMode
from agentscope.event import (
    RequireExternalExecutionEvent,
    ExternalExecutionResultEvent,
)
from agentscope.message import TextBlock, ToolResultBlock, ToolResultState
from agentscope.tool import (
    Toolkit,
    TaskCreate,
    TaskGet,
    TaskList,
    TaskUpdate,
    Read,
    Write,
    Edit,
)
from agentscope.workspace import LocalWorkspace

from config import (
    AGENT_MAX_ITERS,
    CONTEXT_RESERVE_RATIO,
    CONTEXT_TRIGGER_RATIO,
    DOC_COMPARE_URL,
    DOC_EXTRACT_URL,
    INJECTION_CONTEXT_BUFFER_RATIO,
    INJECTION_TIME_INTERVAL,
    INJECTION_TIMEZONE,
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
    LLM_PROVIDER,
    LLM_THINKING_ENABLE,
    MEMORY_DIR,
    OFFICE_MCP_URL,
    PORT,
    SERVICE_ACCOUNT_PASSWORD,
    SERVICE_ACCOUNT_USERNAME,
    SESSION_DB_PATH,
    TOOL_RESULT_LIMIT,
    UPLOAD_DIR,
    WORKSPACE_DIR,
)
from llm_config import get_model_and_formatter, get_memory_model
import cleanup  # 定时清理（上传图片/过期会话/工作区，不含 memory）
from ask_user import AskUser  # human-in-loop 外部工具（检索前追问补全信息）

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(handler)
logger.propagate = False

SYSTEM_PROMPT = """你是"AI办公搭子"，一个专业的智能办公助手。你可以与用户进行日常对话，也可以调用工具完成具体的办公任务。

你拥有以下工具能力：

文档处理：
- read_document：读取已上传文档的全文文本（PDF 走 OCR；Word .docx/.doc 走结构化解析；Excel .xlsx/.xls 按工作表输出 Markdown 表格）。适用于用户对上传文档的一般性请求：解释、总结、问答、翻译、提取要点等。调用后由你基于全文直接作答。
- read_image：识别已上传图片中的文字（OCR），返回 Markdown。适用于用户上传图片后要求「识别图片文字、把图转文字、看图里写了什么」等。调用后由你基于识别出的文本直接作答。
- extract_document：从已上传的 PDF/图片 文档中抽取指定字段信息（如合同名称、签订日期、甲乙方等）（PDF/图片）
- compare_documents：比对两份 PDF 文档的文本和印章差异，输出相似度分数（仅 PDF）
- extract_to_excel：从已上传目标文档提取指定字段并生成 Excel 下载链接。传 fields→生成默认「字段|值」表；传 template_filename→按已上传 Excel 模板「字段名+右侧空格」识别字段并填充值到对应位置。目标文档支持 PDF/Word(.docx)/Excel(.xlsx)/图片。

多媒体检索：
- search_images_by_text：通过文字描述在图像库中搜索相似图片（图像索引默认 index_name=global）
- search_images_by_image：通过上传的图片搜索相似图片（以图搜图，图像索引默认 global）
- search_audios_by_text：通过文字描述在音频库中搜索匹配的音频片段（音频索引默认 index_name=base，注意音频不是 global）
- list_image_libraries / list_audio_libraries：查看可用的图像/音频库索引（不确定索引名时先调用查看）

任务管理与文件操作：
- TaskCreate / TaskUpdate / TaskList / TaskGet：创建和跟踪任务计划，适合复杂多步任务
- Read / Write / Edit：读写文件，可用于记录笔记和管理长期记忆

文件上传：
用户可以在对话框中上传 PDF、Word(.docx/.doc)、Excel(.xlsx/.xls) 或图片。上传成功后，消息会附带文件信息：
- PDF 文件：包含 extract_filename（用于 read_document / extract_document）和 compare_filename（用于 compare_documents）
- Word/Excel 文档：包含 extract_filename（用于 read_document）；若该 Excel 是用户提供的字段模板，还可作为 extract_to_excel 的 template_filename
- 图片文件：包含 file_path（用于 read_image 识别文字，或 search_images_by_image 以图搜图）和 extract_filename（用于 extract_document / extract_to_excel 抽取字段；上传成功即已转发到文档抽取服务）
如果用户需要文档操作或图搜图但未上传文件，提示用户先上传。

工具调用原则（重要）：
- 只在用户明确请求需要工具支持的具体操作时才调用工具。例如用户说"提取合同日期"才调用 extract_document，用户说"比对这两份文件"才调用 compare_documents。
- 用户上传文档（PDF/Word/Excel）后，根据其意图选择处理方式，不要一刀切：
  · 一般性请求（解释一下、总结、问答、翻译、提取要点、看看这个文件讲什么等）→ 调用 read_document 获取全文，由你直接作答；
  · 明确要抽取文档特定字段（如"合同名称/签订日期/甲方"，PDF/图片均可）→ 调用 extract_document，调用前需确认用户要提取哪些字段；
  · 明确要比对两份 PDF 文档 → 调用 compare_documents（仅 PDF）。
- 用户要求「把文档里的字段提取出来并输出/下载成 Excel/表格」时 → 调用 extract_to_excel：用户指定了字段就传 fields；用户上传了 Excel 模板就把模板的 extract_filename 作为 template_filename、目标文档的 extract_filename 作为 filename。未上传目标文档时先提示用户上传。
- extract_document / extract_to_excel 的 filename 参数必须是 extract_filename，绝不能传 file_path。若目标文档（含图片）仅有 file_path 而无 extract_filename，说明该文件未成功入库到文档抽取服务，应提示用户重新上传该文件，不要用 file_path 当 filename 盲目重试。
- 用户上传图片要求识别图片中的文字时 → 调用 read_image 获取 OCR 文本后作答；要按图搜图才用 search_images_by_image。
- 不要为了使用工具而使用工具。很多问题（如闲聊、知识问答、建议）可以直接回答，无需调用任何工具。
- 不要编造工具参数。如果工具需要特定参数（如 extract_document 需要 fields 列表），但用户没有提供，先询问用户要提取哪些字段。
- 工具调用失败时，向用户说明失败原因，不要盲目重试。
- 若工具返回「文件不存在或已过期」「可能已被定时清理」等提示，说明用户先前上传的文件因长期未使用被定时清理。请向用户说明该文件已过期并请其重新上传，不要用原文件名（extract_filename/file_path/compare_filename）反复重试。
- 多媒体检索（search_images_by_text / search_images_by_image / search_audios_by_text）的 human-in-loop：若用户已明确「搜索关键词」和「期望返回数量」，直接调用对应检索工具（数量作为 top_k）；若二者之一缺失（如只说"找几张起重机的图"但没说几张），先调用 ask_user 工具向用户追问（例如 question="请补充：搜索关键词，以及想要返回多少条结果", options=["3 条","5 条","10 条"]），拿到用户作答后再调用检索工具。检索结果（图片/音频）会以画廊形式自动展示给用户，你只需用一句话概述检索结果，不要复述文件路径。

工作原则：
- 始终使用中文回复，保持简洁专业。
- 遇到复杂多步任务时，先用 TaskCreate 拆解步骤，再逐步执行。
- 工具调用后，将结果整理为易读的格式呈现给用户，不要直接输出原始 JSON。
- extract_to_excel 返回下载链接时，将其整理为 markdown 下载链接呈现给用户（如 [📥 下载提取结果](链接)），并可附上各字段提取值摘要。
- 信息不足时主动询问，不确定时如实告知，不编造信息。
"""


# ── 鉴权 ──────────────────────────────────────────────────────
_security = HTTPBearer()


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> str:
    """验证 JWT token，返回用户名（作为 user_id）。"""
    try:
        payload = pyjwt.decode(
            credentials.credentials,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="无效的认证信息")
        return username
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="认证信息已失效")


def _ms(ts: str | None) -> int:
    """把存储的时间戳解析为数值毫秒，兼容旧的 ISO 字符串。"""
    if not ts:
        return 0
    try:
        return int(ts)
    except (TypeError, ValueError):
        try:
            return int(datetime.fromisoformat(ts).timestamp() * 1000)
        except Exception:
            return 0


# 会话状态持久化
class SessionStore:
    """基于 SQLite 的会话存储（用户隔离）。

    以 (user_id, session_id) 为复合主键，确保不同用户的会话互不可见。
    每行同时保存：
      - state_json:    序列化后的 AgentState（LLM 工作记忆/压缩摘要）
      - title:         会话标题（取自首条用户消息）
      - messages_json: 用户可见的消息列表（用户消息与助手回复，含思维链/工具调用）
    后端为会话历史的唯一真源，前端仅作缓存展示。
    """

    def __init__(self, db_path):
        self.db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """打开数据库连接并建表/迁移。"""
        self._db = await aiosqlite.connect(self.db_path)

        cursor = await self._db.execute("PRAGMA table_info(sessions)")
        columns = {row[1] for row in await cursor.fetchall()}
        await cursor.close()

        # 旧版表无 user_id 列：无用户隔离，不可用，删除重建
        if columns and "user_id" not in columns:
            await self._db.execute("DROP TABLE sessions")
            logger.info("检测到旧版 sessions 表（无 user_id 列），已删除重建")
            columns = set()

        # 增量迁移：为旧表补充新列（ALTER TABLE ADD COLUMN，数据保留）
        for col in ("title", "messages_json", "created_at"):
            if columns and col not in columns:
                await self._db.execute(f"ALTER TABLE sessions ADD COLUMN {col} TEXT")
                logger.info(f"已为 sessions 表补充列: {col}")

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                user_id        TEXT NOT NULL,
                session_id     TEXT NOT NULL,
                title          TEXT,
                messages_json  TEXT,
                state_json     TEXT NOT NULL,
                created_at     TEXT,
                updated_at     TEXT NOT NULL,
                PRIMARY KEY (user_id, session_id)
            )
        """)
        await self._db.commit()

    async def close(self) -> None:
        """关闭数据库连接。"""
        if self._db:
            await self._db.close()
            self._db = None

    async def load_state(self, user_id: str, session_id: str) -> AgentState | None:
        """加载指定会话的 AgentState，若不存在则返回 None。"""
        if not self._db:
            return None
        try:
            cursor = await self._db.execute(
                "SELECT state_json FROM sessions WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is None:
                return None
            return AgentState.model_validate_json(row[0])
        except Exception as e:
            logger.warning(f"加载会话状态失败 {user_id}/{session_id}: {e}")
            return None

    async def save_state(self, user_id: str, session_id: str, state: AgentState) -> None:
        """持久化 AgentState（upsert，不影响 title/messages_json）。"""
        if not self._db:
            return
        try:
            state_json = state.model_dump_json()
            now = str(int(time.time() * 1000))
            await self._db.execute(
                "INSERT INTO sessions (user_id, session_id, state_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, session_id) DO UPDATE SET "
                "state_json = excluded.state_json, updated_at = excluded.updated_at",
                (user_id, session_id, state_json, now, now),
            )
            await self._db.commit()
        except Exception as e:
            logger.warning(f"保存会话状态失败 {user_id}/{session_id}: {e}")

    async def load_session(
        self, user_id: str, session_id: str
    ) -> dict | None:
        """加载会话元数据与消息列表，不存在则返回 None。"""
        if not self._db:
            return None
        try:
            cursor = await self._db.execute(
                "SELECT title, messages_json FROM sessions "
                "WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is None:
                return None
            title, messages_json = row
            messages = json.loads(messages_json) if messages_json else []
            return {"title": title, "messages": messages}
        except Exception as e:
            logger.warning(f"加载会话消息失败 {user_id}/{session_id}: {e}")
            return None

    async def save_messages(
        self, user_id: str, session_id: str, title: str | None, messages: list
    ) -> None:
        """持久化消息列表与标题（upsert，不影响 state_json）。

        新建行时 state_json 用占位空对象，随后由 save_state 写入真实状态。
        """
        if not self._db:
            return
        try:
            messages_json = json.dumps(messages, ensure_ascii=False)
            now = str(int(time.time() * 1000))
            await self._db.execute(
                "INSERT INTO sessions "
                "(user_id, session_id, title, messages_json, state_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, '{}', ?, ?) "
                "ON CONFLICT(user_id, session_id) DO UPDATE SET "
                "title = excluded.title, messages_json = excluded.messages_json, "
                "updated_at = excluded.updated_at",
                (user_id, session_id, title, messages_json, now, now),
            )
            await self._db.commit()
        except Exception as e:
            logger.warning(f"保存会话消息失败 {user_id}/{session_id}: {e}")

    async def list_sessions(self, user_id: str) -> list[dict]:
        """列出用户的所有会话（按 updated_at 倒序）。"""
        if not self._db:
            return []
        try:
            cursor = await self._db.execute(
                "SELECT session_id, title, updated_at FROM sessions "
                "WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            return [
                {"id": sid, "title": title or "新会话", "updatedAt": _ms(updated_at)}
                for sid, title, updated_at in rows
            ]
        except Exception as e:
            logger.warning(f"列出会话失败 {user_id}: {e}")
            return []

    async def delete_state(self, user_id: str, session_id: str) -> bool:
        """删除指定会话（含状态与消息），返回是否删除成功。"""
        if not self._db:
            return False
        cursor = await self._db.execute(
            "DELETE FROM sessions WHERE user_id = ? AND session_id = ?",
            (user_id, session_id),
        )
        await self._db.commit()
        deleted = cursor.rowcount > 0
        await cursor.close()
        return deleted


# 全局共享资源（在 lifespan 中初始化）
# 这些资源在所有会话间共享，Agent 实例按请求创建（携带各自的 state）
_model = None
_memory_model = None
_toolkit: Toolkit | None = None
_react_config: ReActConfig | None = None
_context_config: ContextConfig | None = None
_injection_config: InjectionConfig | None = None
_workspace: LocalWorkspace | None = None
_session_store: SessionStore | None = None
_cleanup_task = None  # 定时清理后台任务句柄（lifespan 中创建/取消）

# 活跃回复任务注册表：key = "user_id:session_id"，用于支持停止输出
_active_reply_tasks: dict[str, asyncio.Task] = {}
# 中断哨兵：放入队列表示用户已取消
_CANCELLED = object()

# human-in-loop 追问注册表：key = reply_id，value = asyncio.Future[str]。
# agent 调 ask_user 外部工具 → RequireExternalExecutionEvent 暂停 → 此处登记 future；
# 前端 POST /chat/answer set_result(answer) → run_reply 用答案构造 ExternalExecutionResultEvent 恢复。
_pending_clarifies: dict[str, asyncio.Future] = {}
# 追问等待超时（秒）：超时则用兜底答案恢复，避免回复永久挂起。
_CLARIFY_TIMEOUT = float(os.environ.get("CLARIFY_TIMEOUT", "300"))

# 文档服务 HTTP 客户端（在 lifespan 中初始化）
_http_client: httpx.AsyncClient | None = None

# document_extract 服务 JWT token 缓存
_extract_token: str | None = None
_extract_token_expires: float = 0.0


async def _get_extract_token() -> str:
    """使用服务账号登录 document_extract 服务，获取 JWT token。"""
    global _extract_token, _extract_token_expires
    if _extract_token and time.time() < _extract_token_expires - 60:
        return _extract_token

    resp = await _http_client.post(
        f"{DOC_EXTRACT_URL}/login",
        json={
            "username": SERVICE_ACCOUNT_USERNAME,
            "password": SERVICE_ACCOUNT_PASSWORD,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    _extract_token = data["access_token"]
    _extract_token_expires = time.time() + data.get("expiresIn", 86400000) / 1000
    return _extract_token


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时创建共享资源，关闭时清理。"""
    global _model, _memory_model, _toolkit, _react_config, _context_config
    global _injection_config, _workspace, _session_store, _http_client, _cleanup_task

    logger.info("正在初始化 AI 办公搭子 Agent...")
    logger.info(f"LLM 提供商: {LLM_PROVIDER}, thinking_enable: {LLM_THINKING_ENABLE}")
    logger.info(f"MCP Server URL: {OFFICE_MCP_URL}")

    # 1. 创建统一 LLM 模型（formatter 已在模型内部设置）
    _model, _ = get_model_and_formatter()

    # 2. 创建长期记忆检索模型（非流式、非思维链，供 AgenticMemoryMiddleware
    #    异步选择相关记忆文件；与主推理模型分离以避免流式连接冲突）
    _memory_model = get_memory_model()

    # 3. 创建 MCP 客户端（无状态 HTTP，无需手动 connect/close）
    mcp_client = MCPClient(
        name="office_tools",
        is_stateful=False,
        mcp_config=HttpMCPConfig(
            url=OFFICE_MCP_URL,
            timeout=300.0,
        ),
    )

    # 3.1 对 MCPTool 打补丁：创建时即清理 input_schema
    #     DeepSeek 不支持 anyOf/exclusiveMinimum 等关键字，
    #     且 jsonschema 库校验时 exclusiveMinimum:True 会触发 SchemaError。
    #     在 __init__ 后立即清理，确保 LLM schema 和输入验证都用干净 schema。
    from agentscope.tool import MCPTool as _MCPTool
    _orig_mcp_init = _MCPTool.__init__

    def _sanitized_mcp_init(self, *args, **kwargs):
        _orig_mcp_init(self, *args, **kwargs)
        _ToolSchemaSanitizer._sanitize(self.input_schema)

    _MCPTool.__init__ = _sanitized_mcp_init

    # 4. 创建 Toolkit（MCP 工具 + 计划工具 + 文件读写工具）
    #    Read/Write/Edit 供智能体自主管理长期记忆 Markdown 文件
    _toolkit = Toolkit(
        tools=[
            TaskCreate(),
            TaskGet(),
            TaskList(),
            TaskUpdate(),
            Read(),
            Write(),
            Edit(),
            AskUser(),
        ],
        mcps=[mcp_client],
    )

    # 5. 配置 ReAct 循环与上下文压缩
    _react_config = ReActConfig(max_iters=AGENT_MAX_ITERS)
    _context_config = ContextConfig(
        trigger_ratio=CONTEXT_TRIGGER_RATIO,
        reserve_ratio=CONTEXT_RESERVE_RATIO,
        tool_result_limit=TOOL_RESULT_LIMIT,
    )
    logger.info(
        f"上下文压缩: trigger_ratio={CONTEXT_TRIGGER_RATIO}, "
        f"reserve_ratio={CONTEXT_RESERVE_RATIO}, "
        f"tool_result_limit={TOOL_RESULT_LIMIT}"
    )

    # 6. 配置感知环境（运行时状态注入：时间、任务、上下文用量）
    _injection_config = InjectionConfig(
        timezone=INJECTION_TIMEZONE,
        time_interval=INJECTION_TIME_INTERVAL,
        context_buffer_ratio=INJECTION_CONTEXT_BUFFER_RATIO,
    )
    logger.info(
        f"感知环境: timezone={INJECTION_TIMEZONE}, "
        f"time_interval={INJECTION_TIME_INTERVAL}h, "
        f"context_buffer_ratio={INJECTION_CONTEXT_BUFFER_RATIO}"
    )

    # 7. 初始化工作区（作为 offloader 持久化被压缩的消息与截断的工具结果）
    _workspace = LocalWorkspace(workdir=str(WORKSPACE_DIR))
    await _workspace.initialize()
    logger.info(f"上下文卸载工作区: {WORKSPACE_DIR}")

    # 8. 初始化长期记忆根目录（每用户子目录由中间件按需创建）
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"长期记忆根目录: {MEMORY_DIR}")

    # 9. 初始化会话状态存储（SQLite）
    _session_store = SessionStore(SESSION_DB_PATH)
    await _session_store.init()
    logger.info(f"会话状态数据库: {SESSION_DB_PATH}")

    # 10. 初始化文档服务 HTTP 客户端（用于文件上传转发）
    global _http_client
    _http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(300.0, connect=10.0),
    )

    # 11. 启动定时清理任务（上传图片/过期会话/工作区；不含 memory 长期记忆）
    _cleanup_task = await cleanup.start()

    logger.info("AI 办公搭子 Agent 初始化完成")

    yield

    # 关闭定时清理任务
    await cleanup.stop(_cleanup_task)
    _cleanup_task = None

    # 关闭文档服务 HTTP 客户端
    if _http_client:
        await _http_client.aclose()

    # 关闭工作区
    if _workspace:
        await _workspace.close()

    # 关闭数据库连接
    if _session_store:
        await _session_store.close()

    _model = None
    _memory_model = None
    _toolkit = None
    _react_config = None
    _context_config = None
    _injection_config = None
    _workspace = None
    _session_store = None
    _http_client = None
    logger.info("Agent 已关闭")


app = FastAPI(title="AI 办公搭子", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatAttachment(BaseModel):
    """用户上传文件的元信息，用于告知 Agent 可用的文件名/路径。"""
    original_name: str
    file_type: str = "pdf"  # "pdf" / "office" / "image"
    extract_filename: str | None = None
    compare_filename: str | None = None
    file_path: str | None = None


class ChatRequest(BaseModel):
    message: str
    session_id: str
    attachments: list[ChatAttachment] | None = None


class StopRequest(BaseModel):
    session_id: str


class ClarifyAnswerRequest(BaseModel):
    reply_id: str
    answer: str


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "agent_ready": (
            _model is not None
            and _memory_model is not None
            and _workspace is not None
            and _http_client is not None
        ),
    }


@app.get("/sessions")
async def list_sessions(user_id: str = Depends(verify_token)):
    """列出当前用户的所有历史会话（侧边栏数据源）。"""
    if _session_store is None:
        return JSONResponse(
            {"detail": "服务尚未初始化完成"}, status_code=503
        )
    return {"sessions": await _session_store.list_sessions(user_id)}


@app.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str, user_id: str = Depends(verify_token)
):
    """获取指定会话的消息列表（重新打开历史会话时调用）。"""
    if _session_store is None:
        return JSONResponse(
            {"detail": "服务尚未初始化完成"}, status_code=503
        )
    session = await _session_store.load_session(user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {
        "title": session["title"],
        "messages": session["messages"],
    }


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user_id: str = Depends(verify_token)):
    """删除指定会话的持久化上下文（含状态与消息）。"""
    if _session_store is None:
        return JSONResponse(
            {"detail": "服务尚未初始化完成"}, status_code=503
        )
    deleted = await _session_store.delete_state(user_id, session_id)
    return {"status": "ok", "deleted": deleted}


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    user_id: str = Depends(verify_token),
):
    """上传文件，支持 PDF、Word、Excel 和图片。

    - PDF：转发到文档抽取与文档比对服务，返回 extract_filename 和 compare_filename。
    - Word/Excel：转发到文档抽取服务，返回 extract_filename（供 read_document）。
    - 图片：保存到本地 uploads 目录，返回 file_path 供图搜图工具使用。

    Returns:
        dict: 包含 original_name、file_type 及对应的文件标识。
    """
    global _extract_token, _extract_token_expires

    if _http_client is None:
        return JSONResponse(
            {"detail": "服务尚未初始化完成"}, status_code=503
        )

    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名缺失")

    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    content = await file.read()

    if ext == "pdf":
        return await _upload_pdf(file.filename, content, user_id)
    elif ext in ("docx", "xlsx", "doc", "xls"):
        return await _upload_office_doc(file.filename, ext, content, user_id)
    elif ext in ("jpg", "jpeg", "png", "bmp", "webp"):
        return await _upload_image(file.filename, ext, content, user_id)
    else:
        raise HTTPException(
            status_code=400,
            detail="支持 PDF、Word(.docx/.doc)、Excel(.xlsx/.xls) 和图片（jpg/jpeg/png/bmp/webp）",
        )


# document_extract 启动需加载 OCR 模型（数十秒），上传若早于其就绪则连接被拒；
# 对 ConnectError 退避重试等待其就绪（连不上=未建立连接=无半上传，重试安全）。
_EXTRACT_CONNECT_RETRY_ATTEMPTS = 4
_EXTRACT_CONNECT_RETRY_DELAY = 3.0


async def _forward_to_extract(filename: str, content: bytes, content_type: str) -> str:
    """转发文件到 document_extract /doc_upload，返回 saved_name。

    含 JWT 鉴权、401 token 过期重试、ConnectError 退避重试。
    ConnectError 重试用于应对 document_extract 启动期加载 OCR 模型（数十秒）
    导致的短暂不可达——连不上即未建立连接、无半上传，重试安全。重试耗尽才抛 502，
    不再静默置空 extract_filename，避免后续 agent 拿不到文件名而盲目重试。
    PDF / Word / Excel / 图片 上传共用此函数。
    """
    global _extract_token, _extract_token_expires
    for attempt in range(1, _EXTRACT_CONNECT_RETRY_ATTEMPTS + 1):
        try:
            token = await _get_extract_token()
            resp = await _http_client.post(
                f"{DOC_EXTRACT_URL}/doc_upload",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": (filename, content, content_type)},
            )
            if resp.status_code == 401:
                # token 过期，清除全局缓存重登一次（旧实现误清局部变量，此处修正）
                _extract_token = None
                _extract_token_expires = 0.0
                token = await _get_extract_token()
                resp = await _http_client.post(
                    f"{DOC_EXTRACT_URL}/doc_upload",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": (filename, content, content_type)},
                )
            resp.raise_for_status()
            return resp.json()["saved_name"]
        except httpx.ConnectError:
            if attempt < _EXTRACT_CONNECT_RETRY_ATTEMPTS:
                logger.warning(
                    "文档抽取服务连接失败（第 %d/%d 次），%gs 后重试...",
                    attempt, _EXTRACT_CONNECT_RETRY_ATTEMPTS, _EXTRACT_CONNECT_RETRY_DELAY,
                )
                await asyncio.sleep(_EXTRACT_CONNECT_RETRY_DELAY)
                continue
            logger.exception("文档抽取服务连接失败（已重试 %d 次）", _EXTRACT_CONNECT_RETRY_ATTEMPTS)
            raise HTTPException(
                status_code=502,
                detail="文档抽取服务尚未就绪或不可达，请确认该服务已启动并完成模型加载后重试",
            )
        except httpx.TimeoutException:
            logger.exception("文档抽取服务请求超时")
            raise HTTPException(
                status_code=504,
                detail="文档抽取服务响应超时，请稍后重试",
            )
        except httpx.HTTPStatusError as e:
            logger.error(
                "文档抽取服务返回错误: status=%s, body=%s",
                e.response.status_code,
                e.response.text[:500],
            )
            raise HTTPException(
                status_code=502,
                detail=f"文档抽取服务返回错误 ({e.response.status_code})",
            )
        except Exception as e:
            logger.exception("转发到文档抽取服务时发生意外错误")
            raise HTTPException(
                status_code=502,
                detail=f"上传到文档抽取服务失败: {e}",
            )
    # 理论不可达：循环内每路径均 return/continue/raise
    raise HTTPException(status_code=502, detail="上传到文档抽取服务失败")


# Word/Excel 文件的标准 MIME（旧版 .doc/.xls 含在内）
_OFFICE_CONTENT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "doc": "application/msword",
    "xls": "application/vnd.ms-excel",
}

# 图片标准 MIME（转发到文档抽取服务 /doc_upload 时使用）
_IMAGE_CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "bmp": "image/bmp",
    "webp": "image/webp",
}


async def _upload_office_doc(filename: str, ext: str, content: bytes, user_id: str) -> dict:
    """将 Word/Excel 文件转发到文档抽取服务（供 read_document 解析全文）。

    Office 文档不做比对，故不转发到 document_compare。
    """
    content_type = _OFFICE_CONTENT_TYPES.get(ext, "application/octet-stream")
    extract_filename = await _forward_to_extract(filename, content, content_type)

    logger.info(
        f"Office 文档上传成功: user={user_id}, original={filename}, "
        f"extract={extract_filename}"
    )
    return {
        "original_name": filename,
        "file_type": "office",
        "extract_filename": extract_filename,
        "compare_filename": None,
    }


async def _upload_pdf(filename: str, content: bytes, user_id: str) -> dict:
    """将 PDF 转发到文档抽取与文档比对服务。"""
    extract_filename = await _forward_to_extract(filename, content, "application/pdf")

    # 上传到 document_compare 服务（无需认证）
    try:
        compare_resp = await _http_client.post(
            f"{DOC_COMPARE_URL}/upload",
            files={"file": (filename, content, "application/pdf")},
        )
        compare_resp.raise_for_status()
        compare_filename = compare_resp.json()["saved_name"]
    except httpx.ConnectError:
        logger.exception("文档比对服务连接失败")
        raise HTTPException(
            status_code=502,
            detail="文档比对服务不可达，请确认该服务已启动",
        )
    except httpx.TimeoutException:
        logger.exception("文档比对服务请求超时")
        raise HTTPException(
            status_code=504,
            detail="文档比对服务响应超时，请稍后重试",
        )
    except httpx.HTTPStatusError as e:
        logger.error(
            "文档比对服务返回错误: status=%s, body=%s",
            e.response.status_code,
            e.response.text[:500],
        )
        raise HTTPException(
            status_code=502,
            detail=f"文档比对服务返回错误 ({e.response.status_code})",
        )
    except Exception as e:
        logger.exception("上传到文档比对服务时发生意外错误")
        raise HTTPException(
            status_code=502,
            detail=f"上传到文档比对服务失败: {e}",
        )

    logger.info(
        f"PDF 上传成功: user={user_id}, original={filename}, "
        f"extract={extract_filename}, compare={compare_filename}"
    )
    return {
        "original_name": filename,
        "file_type": "pdf",
        "extract_filename": extract_filename,
        "compare_filename": compare_filename,
    }


async def _upload_image(filename: str, ext: str, content: bytes, user_id: str) -> dict:
    """将图片保存到本地 uploads（供图搜图）并转发到文档抽取服务（供字段提取/全文读取）。

    图片同时获得 file_path（图搜图 / read_image）与 extract_filename（extract_document /
    extract_to_excel / read_document），使其与 PDF/Word/Excel 一样可作为提取目标。
    转发经 _forward_to_extract 含 ConnectError 退避重试；重试耗尽抛 502（与 PDF/Word/Excel
    一致地 fail-fast），不再静默置空 extract_filename，避免 agent 拿不到文件名盲目重试。
    """
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved_name = f"{uuid.uuid4().hex}_{int(time.time())}.{ext}"
    file_path = UPLOAD_DIR / saved_name
    file_path.write_bytes(content)

    content_type = _IMAGE_CONTENT_TYPES.get(ext, "application/octet-stream")
    extract_filename = await _forward_to_extract(filename, content, content_type)

    logger.info(
        f"图片上传成功: user={user_id}, original={filename}, "
        f"path={file_path}, extract={extract_filename}"
    )
    return {
        "original_name": filename,
        "file_type": "image",
        "file_path": str(file_path),
        "extract_filename": extract_filename,
    }


def _user_memory_workdir(user_id: str) -> str:
    """返回用户专属长期记忆工作目录的绝对路径。

    对 user_id 做文件名安全化处理，防止路径穿越：仅保留字母、数字、
    ``._-``，其余字符替换为下划线，并剥离首尾的 ``._-`` 以避免
    ``..`` 等危险片段。
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", user_id).strip("._-")
    return str(MEMORY_DIR / (safe or "default"))


class _ToolSchemaSanitizer(MiddlewareBase):
    """清理工具 schema 中 DeepSeek 等 LLM 不支持的关键字。

    DeepSeek V4 仅支持 type/description/properties/required/items/enum/default，
    不支持 anyOf/oneOf/format/minLength/exclusiveMinimum/minItems/additionalProperties 等。
    此中间件在每次模型调用前用白名单方式递归清理所有工具 schema。
    """

    # 允许保留的 JSON Schema 关键字
    _ALLOWED_KEYS = frozenset({
        "type", "description", "properties", "required",
        "items", "enum", "default",
    })

    async def on_model_call(self, agent, input_kwargs, next_handler):
        tools = input_kwargs.get("tools")
        if tools:
            for tool in tools:
                func = tool.get("function", {})
                if "parameters" in func:
                    self._sanitize(func["parameters"])
        return await next_handler(**input_kwargs)

    @classmethod
    def _sanitize(cls, schema: dict) -> None:
        """递归清理 schema：移除不支持的关键字，展开 anyOf/oneOf。"""
        if not isinstance(schema, dict):
            return

        # 展开 anyOf/oneOf：用第一个选项替换
        for union_key in ("anyOf", "oneOf", "allOf"):
            if union_key in schema:
                options = schema.pop(union_key)
                if options and isinstance(options, list):
                    first = options[0]
                    if isinstance(first, dict):
                        for k, v in first.items():
                            schema.setdefault(k, v)

        # 移除不支持的关键字
        for key in list(schema.keys()):
            if key not in cls._ALLOWED_KEYS:
                schema.pop(key)

        # 递归处理 properties
        for prop in schema.get("properties", {}).values():
            cls._sanitize(prop)

        # 递归处理 items
        if "items" in schema:
            cls._sanitize(schema["items"])


def _create_agent(state: AgentState, user_id: str) -> Agent:
    """使用共享资源和给定状态创建 Agent 实例。

    每次请求创建新的 Agent，通过传入恢复的 AgentState 实现
    会话上下文的重新注入。模型、Toolkit 等重量级资源全局共享；
    长期记忆中间件按用户隔离（每用户独立记忆目录，跨会话复用）。
    """
    memory_middleware = AgenticMemoryMiddleware(
        workdir=_user_memory_workdir(user_id),
        parameters=AgenticMemoryMiddleware.Parameters(
            retrieval_model=_memory_model,
        ),
    )
    return Agent(
        name="office_assistant",
        system_prompt=SYSTEM_PROMPT,
        model=_model,
        toolkit=_toolkit,
        react_config=_react_config,
        context_config=_context_config,
        injection_config=_injection_config,
        offloader=_workspace,
        middlewares=[memory_middleware, _ToolSchemaSanitizer()],
        state=state,
    )


def _sse(data: dict) -> str:
    """格式化 SSE 事件。"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _assistant_tool(assistant: dict, call_id: str) -> dict:
    """按 tool_call_id 取回助手消息中的工具调用条目，不存在则新建。"""
    for t in assistant["toolCalls"]:
        if t["id"] == call_id:
            return t
    new = {"id": call_id, "name": "", "args": "", "result": "", "done": False}
    assistant["toolCalls"].append(new)
    return new


# 检索类工具：结果为结构化 JSON，前端以画廊渲染，故不下发原始 tool_result_delta，
# 改在 ToolResultEndEvent 解析 items 下发独立 retrieval 帧。
_RETRIEVAL_TOOLS = {
    "search_images_by_text",
    "search_images_by_image",
    "search_audios_by_text",
}


def _is_retrieval_tool(name: str) -> bool:
    """判断工具名是否属于检索类工具。

    agentscope 会把 MCP 工具改名为 `mcp__{server}__{tool}`（见
    tool/_adapters.py:219），故取末段（最后一个 `__` 之后）与检索工具集匹配，
    避免 server 名变化导致失配。
    """
    return (name or "").rsplit("__", 1)[-1] in _RETRIEVAL_TOOLS


def _process_event(event, assistant: dict) -> list[dict]:
    """将 AgentScope 事件映射为 SSE 负载，同时累积到助手消息。

    单一事件处理入口：SSE 下发与历史消息持久化共用同一份逻辑，
    避免此前"前端重建 / 后端重建"两处分支各写一遍的冗余与漂移。
    """
    event_type = type(event).__name__
    payloads: list[dict] = []

    if event_type == "ThinkingBlockDeltaEvent":
        delta = getattr(event, "delta", "") or ""
        if delta:
            assistant["thinking"] += delta
            payloads.append({"type": "thinking", "content": delta})

    elif event_type == "TextBlockDeltaEvent":
        delta = getattr(event, "delta", "") or ""
        if delta:
            assistant["content"] += delta
            payloads.append({"type": "token", "content": delta})

    elif event_type == "ToolCallStartEvent":
        cid = getattr(event, "tool_call_id", "")
        _assistant_tool(assistant, cid)["name"] = getattr(
            event, "tool_call_name", ""
        )
        payloads.append(
            {"type": "tool_call", "id": cid, "name": getattr(event, "tool_call_name", "")}
        )

    elif event_type == "ToolCallDeltaEvent":
        cid = getattr(event, "tool_call_id", "")
        delta = getattr(event, "delta", "") or ""
        _assistant_tool(assistant, cid)["args"] += delta
        payloads.append({"type": "tool_args", "id": cid, "content": delta})

    elif event_type == "ToolResultTextDeltaEvent":
        cid = getattr(event, "tool_call_id", "")
        delta = getattr(event, "delta", "") or ""
        _assistant_tool(assistant, cid)["result"] += delta
        # 检索工具结果为结构化 JSON：仍累积供结束时解析，但不下发增量，
        # 避免前端工具区显示原始 JSON（画廊帧已足够）。
        if not _is_retrieval_tool(_assistant_tool(assistant, cid)["name"]):
            payloads.append({"type": "tool_result_delta", "id": cid, "content": delta})

    elif event_type == "ToolResultDataDeltaEvent":
        cid = getattr(event, "tool_call_id", "")
        url = getattr(event, "url", "") or ""
        media = getattr(event, "media_type", "") or ""
        if url:
            _assistant_tool(assistant, cid)["result"] += f"[文件] {url}\n"
        payloads.append(
            {"type": "tool_result_data", "id": cid, "url": url, "media_type": media}
        )

    elif event_type == "ToolResultEndEvent":
        cid = getattr(event, "tool_call_id", "")
        tool = _assistant_tool(assistant, cid)
        tool["done"] = True
        # 检索工具：解析累积的结构化 JSON，下发 retrieval 画廊帧。
        if _is_retrieval_tool(tool["name"]):
            items = None
            try:
                parsed = json.loads(tool["result"]) if tool["result"] else None
                if isinstance(parsed, dict):
                    items = parsed.get("items")
            except (json.JSONDecodeError, TypeError):
                items = None
            if isinstance(items, list):
                # 累积到助手消息（随会话持久化，重开历史会话时恢复画廊），
                # 并把工具区结果替换为易读摘要，避免历史里显示原始 JSON。
                assistant.setdefault("results", []).extend(items)
                tool["result"] = str(parsed.get("summary") or "")
                payloads.append({"type": "retrieval", "id": cid, "items": items})
                payloads.append(
                    {"type": "tool_result", "id": cid, "state": str(getattr(event, "state", ""))}
                )
            else:
                # 解析失败：回退为普通工具结果展示。
                payloads.append(
                    {"type": "tool_result_delta", "id": cid, "content": tool["result"]}
                )
                payloads.append(
                    {"type": "tool_result", "id": cid, "state": str(getattr(event, "state", ""))}
                )
        else:
            payloads.append(
                {"type": "tool_result", "id": cid, "state": str(getattr(event, "state", ""))}
            )

    elif event_type == "HintBlockEvent":
        hint = getattr(event, "hint", "")
        if isinstance(hint, list):
            hint = "".join(getattr(b, "text", "") for b in hint)
        if hint:
            assistant["hint"] += hint
            payloads.append({"type": "hint", "content": hint})

    elif event_type == "ExceedMaxItersEvent":
        assistant["content"] = "已达最大推理轮数，请尝试简化问题或提供更多信息。"
        payloads.append({"type": "error", "content": assistant["content"]})

    elif event_type == "ReplyEndEvent":
        error = getattr(event, "error", None)
        if error:
            assistant["content"] = f"处理出错：{error}"
            payloads.append({"type": "error", "content": str(error)})
        else:
            payloads.append({"type": "done", "content": ""})

    elif event_type == "RequireExternalExecutionEvent":
        # human-in-loop：ask_user 外部工具调用 → 暂停，向前端下发追问帧。
        # 答案经 POST /chat/answer 回填 future 后，run_reply 用 ExternalExecutionResultEvent 恢复。
        reply_id = getattr(event, "reply_id", "") or ""
        tool_calls = getattr(event, "tool_calls", []) or []
        question = "请补充所需信息："
        options: list = []
        tool_call_id = ""
        if tool_calls:
            tc = tool_calls[0]
            tool_call_id = getattr(tc, "id", "") or ""
            try:
                inp = json.loads(getattr(tc, "input", "") or "{}")
                q = inp.get("question")
                if isinstance(q, str) and q.strip():
                    question = q.strip()
                opt = inp.get("options")
                if isinstance(opt, list):
                    options = [str(o) for o in opt]
            except Exception:
                pass
        payloads.append({
            "type": "clarify",
            "reply_id": reply_id,
            "tool_call_id": tool_call_id,
            "question": question,
            "options": options,
        })
        # 同步累积到助手消息：随会话持久化，重开历史会话时可恢复追问块
        assistant["clarify"] = {
            "reply_id": reply_id,
            "tool_call_id": tool_call_id,
            "question": question,
            "options": options,
            "answered": False,
            "answer": "",
        }

    return payloads


def _build_resume_event(event, answer: str) -> ExternalExecutionResultEvent:
    """把用户的追问作答封装为 ExternalExecutionResultEvent，供 reply_stream 续流。"""
    tool_calls = getattr(event, "tool_calls", []) or []
    return ExternalExecutionResultEvent(
        reply_id=getattr(event, "reply_id", "") or "",
        execution_results=[
            ToolResultBlock(
                id=getattr(tc, "id", "") or "",
                name=getattr(tc, "name", "ask_user") or "ask_user",
                output=[TextBlock(text=answer)],
                state=ToolResultState.SUCCESS,
            )
            for tc in tool_calls
        ] or [
            ToolResultBlock(
                id="",
                name="ask_user",
                output=[TextBlock(text=answer)],
                state=ToolResultState.SUCCESS,
            )
        ],
    )


async def _await_clarify_answer(reply_id: str, user_id: str) -> str:
    """登记 future 等待用户作答（POST /chat/answer 回填）；超时返回兜底答案。

    future 与 /chat/answer 同处一个事件循环，set_result 安全。按 user_id+reply_id
    隔离，避免跨用户作答。
    """
    key = f"{user_id}:{reply_id}"
    future = asyncio.get_running_loop().create_future()
    _pending_clarifies[key] = future
    try:
        return await asyncio.wait_for(future, _CLARIFY_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning(f"追问超时未作答 user={user_id} reply_id={reply_id}")
        return "（用户未及时作答，已取消本次追问，请重新提问）"
    finally:
        _pending_clarifies.pop(key, None)


@app.post("/chat/stop")
async def stop_chat(req: StopRequest, user_id: str = Depends(verify_token)):
    """停止指定会话的 Agent 输出。

    通过 task.cancel() 触发 asyncio.CancelledError，
    AgentScope 框架会干净地展开当前推理-行动步骤，上下文保持一致。
    """
    task_key = f"{user_id}:{req.session_id}"
    task = _active_reply_tasks.get(task_key)
    if task and not task.done():
        task.cancel()
        logger.info(f"停止 Agent 输出: user={user_id}, session={req.session_id}")
        return {"status": "ok", "stopped": True}
    return {"status": "ok", "stopped": False}


@app.post("/chat/answer", summary="回答 human-in-loop 追问")
async def chat_answer(req: ClarifyAnswerRequest, user_id: str = Depends(verify_token)):
    """回填 ask_user 追问的答案，恢复被暂停的回复流。

    按 user_id+reply_id 取回 future；不存在或已过期（超时/取消）返回 404。
    """
    key = f"{user_id}:{req.reply_id}"
    future = _pending_clarifies.get(key)
    if future is None or future.done():
        return JSONResponse(
            {"detail": "追问已过期或不存在"}, status_code=404
        )
    future.set_result(req.answer)
    return {"ok": True}


@app.post("/chat")
async def chat(req: ChatRequest, user_id: str = Depends(verify_token)):
    """与 Agent 对话，返回 SSE 流式响应。

    每次请求：
    1. 加载该 session 的持久化 AgentState（若不存在则新建）与历史消息列表
    2. 追加用户消息并立即落盘（流式中断也不丢失用户输入）
    3. 用恢复的状态创建 Agent，实现上下文重新注入
    4. 将 reply_stream 放入独立 Task，通过队列传递事件（支持外部取消）
    5. 流式返回 Agent 回复，事件同时累积为助手消息
    6. 回复结束后将助手消息与更新后的 AgentState 持久化保存

    事件类型:
      - thinking:          思维链增量文本
      - tool_call:         工具调用开始（含 id 和 name）
      - tool_args:         工具调用参数增量
      - tool_result_delta: 工具返回文本结果增量
      - tool_result_data:  工具返回非文本数据（含 url 和 media_type）
      - tool_result:       工具调用结束（含 id 和 state）
      - hint:              运行时状态注入提示（感知环境）
      - token:             最终回答增量文本
      - done:              流正常结束
      - stopped:           用户主动停止
      - error:             出错（含超迭代上限）
    """
    if (
        _model is None
        or _memory_model is None
        or _toolkit is None
        or _session_store is None
        or _workspace is None
    ):
        return JSONResponse(
            {"detail": "Agent 尚未初始化完成"}, status_code=503
        )

    # 若该会话有正在运行的回复任务，先取消
    task_key = f"{user_id}:{req.session_id}"
    old_task = _active_reply_tasks.get(task_key)
    if old_task and not old_task.done():
        old_task.cancel()

    # 加载或创建会话状态（工作记忆）
    state = await _session_store.load_state(user_id, req.session_id)
    if state is None:
        state = AgentState(session_id=req.session_id)
        logger.info(f"创建新会话: user={user_id}, session={req.session_id}")
    else:
        logger.info(f"恢复历史会话上下文: user={user_id}, session={req.session_id}")

    # 设置 BYPASS 权限模式，允许 MCP 工具自动执行（无需用户确认）
    state.permission_context = PermissionContext(mode=PermissionMode.BYPASS)

    # 用恢复的状态创建 Agent，注入历史上下文
    agent = _create_agent(state, user_id)

    # 构建用户消息：如有附件，将文件信息追加到消息文本中
    if req.attachments:
        file_list = []
        for a in req.attachments:
            if a.file_type == "image":
                line = f"  - {a.original_name}（file_path: {a.file_path}"
                if a.extract_filename:
                    line += f", extract_filename: {a.extract_filename}"
                line += "）"
                file_list.append(line)
            else:
                # PDF 与 Office 文档均提供 extract_filename；
                # compare_filename 仅 PDF 有，Office 文档为空时不展示
                line = f"  - {a.original_name}（extract_filename: {a.extract_filename}"
                if a.compare_filename:
                    line += f", compare_filename: {a.compare_filename}"
                line += "）"
                file_list.append(line)
        message_text = f"{req.message}\n\n[已上传文件]\n" + "\n".join(file_list)
    else:
        message_text = req.message
    user_msg = UserMsg("user", message_text)

    # 加载历史消息列表与标题（后端为唯一真源）
    session = await _session_store.load_session(user_id, req.session_id)
    messages_list: list[dict] = session["messages"] if session else []
    title = session["title"] if session else None

    # 追加用户消息并立即持久化（流式中断时用户输入仍保留）
    user_seq = len(messages_list) + 1
    messages_list.append({
        "id": user_seq,
        "role": "user",
        "content": req.message,
        "attachments": (
            [{"original_name": a.original_name} for a in req.attachments]
            if req.attachments else []
        ),
        "createdAt": int(time.time() * 1000),
    })
    if not title:
        title = (req.message or "新会话")[:30]
    await _session_store.save_messages(
        user_id, req.session_id, title, messages_list
    )

    # 助手消息累积器：流式事件通过 _process_event 写入此处。
    # results/clarify 一并持久化，重新打开历史会话时可恢复检索画廊与追问作答。
    assistant = {
        "id": user_seq + 1,
        "role": "assistant",
        "content": "",
        "thinking": "",
        "hint": "",
        "toolCalls": [],
        "createdAt": int(time.time() * 1000),
        "results": [],    # 检索画廊 items（图片/音频）
        "clarify": None,  # human-in-loop 追问 {question, options, answered, answer}
    }

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def run_reply():
            """在独立 Task 中消费 reply_stream，将事件放入队列。

            遇 RequireExternalExecutionEvent（ask_user 追问）时暂停，等待
            POST /chat/answer 回填答案后，用 ExternalExecutionResultEvent 续流——
            新开一段 reply_stream(resume_event) 继续推理，实现单次会话内 human-in-loop。
            """
            try:
                iterator = agent.reply_stream(user_msg, yield_final_msg=True)
                while True:
                    paused = False
                    async for event in iterator:
                        await queue.put(event)
                        if isinstance(event, RequireExternalExecutionEvent):
                            answer = await _await_clarify_answer(
                                getattr(event, "reply_id", "") or "", user_id
                            )
                            # 记录作答到助手消息（随会话持久化，重开时恢复"问题->回答"折叠行）
                            clar = assistant.get("clarify")
                            if not isinstance(clar, dict):
                                clar = assistant["clarify"] = {
                                    "reply_id": getattr(event, "reply_id", "") or "",
                                    "tool_call_id": "",
                                    "question": "",
                                    "options": [],
                                    "answered": False,
                                    "answer": "",
                                }
                            clar["answered"] = True
                            clar["answer"] = answer
                            resume_event = _build_resume_event(event, answer)
                            iterator = agent.reply_stream(
                                resume_event, yield_final_msg=True
                            )
                            paused = True
                            break
                    if not paused:
                        break  # 迭代器正常耗尽
            except asyncio.CancelledError:
                queue.put_nowait(_CANCELLED)
            except Exception as e:
                queue.put_nowait(e)
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(run_reply())
        _active_reply_tasks[task_key] = task

        try:
            while True:
                event = await queue.get()

                # None = 流结束
                if event is None:
                    break

                # 用户取消
                if event is _CANCELLED:
                    if not assistant["content"]:
                        assistant["content"] = "（已停止生成）"
                    yield _sse({"type": "stopped", "content": ""})
                    break

                # 异常
                if isinstance(event, Exception):
                    logger.exception("Agent 处理出错", exc_info=event)
                    assistant["content"] = f"处理请求时出错：{event}"
                    yield _sse({
                        "type": "error",
                        "content": f"处理出错: {str(event)}",
                    })
                    break

                # 单一事件处理：下发 SSE + 累积到 assistant
                for payload in _process_event(event, assistant):
                    yield _sse(payload)

        finally:
            _active_reply_tasks.pop(task_key, None)
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            # 持久化助手消息（含本轮思维链/工具调用/回复）与 AgentState
            messages_list.append(assistant)
            await _session_store.save_messages(
                user_id, req.session_id, title, messages_list
            )
            await _session_store.save_state(user_id, req.session_id, agent.state)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_level="info")

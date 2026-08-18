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
    KB_EMBEDDING_MODEL,
    LLM_PROVIDER,
    LLM_THINKING_ENABLE,
    MEMORY_DIR,
    OFFICE_MCP_URL,
    PORT,
    SERVICE_ACCOUNT_PASSWORD,
    SERVICE_ACCOUNT_USERNAME,
    SESSION_DB_PATH,
    SERVICE_ROOT,
    SKILL_DIR,
    TOOL_RESULT_LIMIT,
    UPLOAD_DIR,
    WORKSPACE_DIR,
)
from llm_config import get_model_and_formatter, get_memory_model
import cleanup  # 定时清理（上传图片/过期会话/工作区，不含 memory）
import skill as skill_module  # Skill 系统（Markdown 指令集 + 内网共享市场）
from ask_user import AskUser  # human-in-loop 外部工具（检索前追问补全信息）
import kb  # 个人知识库 RAG（嵌入/向量库/检索；未就绪时优雅降级）

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

个人知识库（RAG）：
- 当用户开启「知识库检索」开关时，系统会在每次回复前自动检索用户个人知识库（本人上传的全部文档）与全平台已公开文档中与问题相关的片段，作为上下文提示注入。你应基于这些自动注入的检索结果作答，并在回答中注明出处文档名。
- search_knowledge：如果你需要更精确地检索特定内容（如追问中需要重新检索、或自动注入的结果不够具体），可以主动调用此工具进行补充检索。该工具由用户在对话框的「知识库检索」开关控制：开关关闭时调用会被拒绝（返回「未启用」提示），此时不要重试，直接据通用知识作答，并提示用户可开启该开关后再问。开关开启时正常调用。
- 对于不涉及用户文档的通用问题，即使开关开启，自动检索也可能无结果，此时直接据通用知识作答即可。

Skill 系统（技能指令）：
- 你拥有一个基于 Markdown 指令集的 Skill 系统，系统会在每次对话时将已启用的 skill 列表（名称+描述）注入到你的上下文中。
- 当用户的请求匹配某个 skill 的描述时，调用 Skill 查看器工具读取该 skill 的完整指令，然后按指令使用已有工具执行操作。
- Skill 不是工具——不能直接"调用"一个 skill，而是先读取其指令再按步骤执行。
- 用户可通过「Skill 市场」页面创建、管理、共享自己的 skill，也可以安装他人公开的 skill。

任务管理与文件操作：
- TaskCreate / TaskUpdate / TaskList / TaskGet：创建和跟踪任务计划，适合复杂多步任务
- Read / Write / Edit：读写文件，用于管理长期记忆（详见下方"长期记忆"部分）

文件上传：
用户可以在对话框中上传 PDF、Word(.docx/.doc)、Excel(.xlsx/.xls) 或图片。上传成功后，消息会附带文件信息：
- PDF 文件：包含 extract_filename（用于 read_document / extract_document）和 compare_filename（用于 compare_documents）
- Word/Excel 文档：包含 extract_filename（用于 read_document）；若该 Excel 是用户提供的字段模板，还可作为 extract_to_excel 的 template_filename
- 图片文件：包含 file_path（用于 read_image 识别文字，或 search_images_by_image 以图搜图）和 extract_filename（用于 extract_document / extract_to_excel 抽取字段；上传成功即已转发到文档抽取服务）
如果用户需要文档操作或图搜图但未上传文件，提示用户先上传。

工具调用原则（重要）：
- 只在用户明确请求需要工具支持的具体操作时才调用工具。例如用户说"提取合同日期"才调用 extract_document，用户说"比对这两份文件"才调用 compare_documents。
- 例外：长期记忆的保存属于你的主动职责，不需要用户明确请求（详见下方"长期记忆"部分）。
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

长期记忆（重要）：
你拥有一个基于 Markdown 文件的长期记忆系统，跨会话持久保存。系统已在每次对话时将记忆索引（MEMORY.md）注入到你的上下文中，并在回复前异步检索相关记忆文件作为提示。
- 何时保存：当你从对话中学到以下信息时，应**主动**用 Write 工具保存记忆（无需用户要求）：
  · 用户偏好：如"我喜欢简洁的回复"、"用中文回答"、"不要加 emoji"等
  · 用户角色：如用户的职业、技术背景、所在行业等
  · 工作反馈：如用户纠正你的做法（"不要这样做"）或确认你的做法（"对，就这样"）
  · 项目背景：如用户提到的项目目标、截止日期、关键约束等
- 何时不保存：不要保存当前对话的临时状态、可通过工具直接获取的信息、或用户明确说"不要记"的内容。
- 如何保存（两步）：
  1. 用 Write 工具将记忆写入独立的 .md 文件（如 user_preference.md），文件开头使用 frontmatter 格式：
     ---
     name: 记忆名称
     description: 一句话描述何时应检索此记忆
     type: user/feedback/project/reference
     ---
     （正文为记忆内容；feedback/project 类型应包含 **Why:** 和 **How to apply:** 行）
  2. 用 Edit 工具在 MEMORY.md 中添加一行索引：- [标题](文件名.md) — 一句话描述
- 用户明确要求"记住"某事时，立即保存；要求"忘记"某事时，找到并删除对应记忆文件和索引行。
- 记忆文件保存在系统提示中注入的记忆目录下，直接写入即可，无需创建目录。

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

    # 4. 创建 Toolkit（MCP 工具 + 计划工具 + 文件读写工具 + Skill 系统）
    #    Read/Write/Edit 供智能体自主管理长期记忆 Markdown 文件。
    #    search_knowledge 注册在 "basic" 组（始终可见），由权限系统按
    #    /chat 的 use_kb 开关决定是否放行（关闭时 check_permissions 返回 DENY），
    #    而非用工具组激活——避免智能体用 reset_tools 自激活绕过开关。
    #    SharedSkillLoader 按 contextvar 解析当前用户，返回其启用的 skill
    #    （自建 + 已安装），SDK 自动注册 Skill 查看器并注入系统提示。
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
        skills_or_loaders=[skill_module.SharedSkillLoader()],
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

    # 11. 初始化个人知识库 RAG：复用上面的 HTTP 客户端与 document_extract token
    #     获取器；注入 _forward_to_extract 复用其带 token/退避的上传逻辑。
    #     Ollama 嵌入模型或向量库不可用时优雅降级（is_ready()=False），
    #     KB 接口返回 503，其余能力正常。
    kb.set_upload_fn(_forward_to_extract)
    await kb.init_kb(_http_client, _get_extract_token)
    # 始终注册 search_knowledge 工具到 "kb" 组：未就绪时 call() 返回友好提示。
    # 该组默认不激活，仅当 /chat 收到 use_kb=True 时激活，LLM 才可见该工具——
    # 实现「关闭检索时不启用 RAG」。注册后用 get_tool 实际校验工具真在 Toolkit 中。
    await _toolkit.add_tool(kb.SearchKnowledge())
    # 直接检查 "basic" 组是否含 search_knowledge（不触发 MCP 工具枚举，避免在 MCP
    # 服务未启动时报 TaskGroup 错误）。MCP 工具在 agent 实际执行 get_tool 时才枚举。
    _has_kb_tool = any(
        getattr(t, "name", "") == "search_knowledge"
        for g in _toolkit.tool_groups if g.name == "basic"
        for t in g.tools
    )
    logger.info(
        "search_knowledge 工具注册%s（kb_ready=%s）",
        "并校验通过" if _has_kb_tool else "校验未通过",
        kb.is_ready(),
    )

    # 12. 启动定时清理任务（上传图片/过期会话/工作区；不含 memory 长期记忆）
    _cleanup_task = await cleanup.start()

    # 13. 初始化 Skill 系统（Markdown 指令集 + 内网共享市场）
    await skill_module.init_skills()

    logger.info("AI 办公搭子 Agent 初始化完成")

    yield

    # 关闭定时清理任务
    await cleanup.stop(_cleanup_task)
    _cleanup_task = None

    # 关闭 Skill 系统
    await skill_module.close_skills()

    # 关闭知识库（向量库客户端与元数据库）
    await kb.close_kb()

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
    use_kb: bool = True  # 是否启用知识库检索（RAG）；False 时 search_knowledge 被权限拒绝


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
        "kb_ready": kb.is_ready(),
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


# ── 个人知识库（RAG）接口 ─────────────────────────────────────
# 上传文档→异步抽取全文→分块→嵌入→入库（status: pending/processing/ready/failed）；
# 可切换文档公开状态供他人检索；对话中 Agent 通过 RAGMiddleware 自动检索。
# 知识库未就绪（嵌入模型/向量库不可用）时返回 503，便于前端给出明确提示。

class KBSearchRequest(BaseModel):
    query: str
    top_k: int | None = None


class KBSharedRequest(BaseModel):
    shared: bool


class KBEnabledRequest(BaseModel):
    enabled: bool


def _kb_unavailable():
    return JSONResponse(
        {"detail": f"知识库功能未就绪（需本地 Ollama 嵌入模型 {KB_EMBEDDING_MODEL}，请执行 `ollama pull {KB_EMBEDDING_MODEL}` 后重启服务）"},
        status_code=503,
    )


@app.get("/kb/documents", summary="列出当前用户的知识库文档")
async def kb_list_documents(user_id: str = Depends(verify_token)):
    if not kb.is_ready():
        return _kb_unavailable()
    return {"documents": await kb.list_documents(user_id)}


@app.post("/kb/documents", summary="上传文档到个人知识库（异步索引）")
async def kb_upload_document(
    file: UploadFile = File(...),
    user_id: str = Depends(verify_token),
):
    if not kb.is_ready():
        return _kb_unavailable()
    if not file.filename or "." not in file.filename:
        raise HTTPException(status_code=400, detail="文件名缺失或无扩展名")
    ext = file.filename.lower().rsplit(".", 1)[-1]
    if ext not in set(kb.supported_exts()):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: .{ext}，支持 PDF/Word/Excel/图片/TXT/MD/CSV",
        )
    content = await file.read()
    result = await kb.create_document(user_id, file.filename, ext, content)
    logger.info(f"知识库文档上传: user={user_id}, file={file.filename}, doc={result['doc_id']}")
    return result


@app.get("/kb/documents/{doc_id}", summary="获取文档索引状态与全文")
async def kb_get_document(doc_id: str, user_id: str = Depends(verify_token)):
    if not kb.is_ready():
        return _kb_unavailable()
    doc = await kb.get_document(user_id, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


@app.patch("/kb/documents/{doc_id}", summary="切换文档是否公开供他人检索")
async def kb_set_shared(
    doc_id: str, req: KBSharedRequest, user_id: str = Depends(verify_token)
):
    if not kb.is_ready():
        return _kb_unavailable()
    try:
        updated = await kb.set_shared(user_id, doc_id, req.shared)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("切换共享失败 doc=%s", doc_id)
        raise HTTPException(status_code=500, detail=f"切换共享失败: {e}")
    if not updated:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"doc_id": doc_id, "shared": req.shared}


@app.patch("/kb/documents/{doc_id}/enabled", summary="切换文档是否参与检索")
async def kb_set_enabled(
    doc_id: str, req: KBEnabledRequest, user_id: str = Depends(verify_token)
):
    if not kb.is_ready():
        return _kb_unavailable()
    try:
        updated = await kb.set_enabled(user_id, doc_id, req.enabled)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("切换启用失败 doc=%s", doc_id)
        raise HTTPException(status_code=500, detail=f"切换启用失败: {e}")
    if not updated:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"doc_id": doc_id, "enabled": req.enabled}


@app.delete("/kb/documents/{doc_id}", summary="删除知识库文档")
async def kb_delete_document(doc_id: str, user_id: str = Depends(verify_token)):
    if not kb.is_ready():
        return _kb_unavailable()
    deleted = await kb.delete_document(user_id, doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"doc_id": doc_id, "deleted": True}


@app.post("/kb/search", summary="检索个人知识库（本人 + 全平台公开文档）")
async def kb_search(req: KBSearchRequest, user_id: str = Depends(verify_token)):
    if not kb.is_ready():
        return _kb_unavailable()
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="检索词不能为空")
    top_k = req.top_k or kb.KB_SEARCH_TOP_K  # noqa
    items = await kb.search(user_id, req.query, top_k)
    return {"query": req.query, "items": items}


# ── Skill 系统 API ────────────────────────────────────────────────────────
class SkillCreateRequest(BaseModel):
    name: str
    description: str
    tags: str = ""
    body: str


class SkillUpdateRequest(BaseModel):
    name: str
    description: str
    tags: str = ""
    body: str


class SkillSharedRequest(BaseModel):
    shared: bool


class SkillEnabledRequest(BaseModel):
    enabled: bool


class SkillInstallRequest(BaseModel):
    author_id: str
    author_skill_id: str


@app.get("/skills", summary="列出本人 skill（自建 + 已安装）")
async def list_skills(user_id: str = Depends(verify_token)):
    skills = await skill_module.list_skills(user_id)
    return {"skills": skills}


@app.post("/skills", summary="创建新 skill")
async def create_skill(req: SkillCreateRequest, user_id: str = Depends(verify_token)):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="skill 名称不能为空")
    try:
        result = await skill_module.create_skill(
            user_id, req.name.strip(), req.description.strip(),
            req.tags.strip(), req.body,
        )
        return result
    except Exception as e:
        logger.exception("创建 skill 失败")
        raise HTTPException(status_code=500, detail=f"创建失败: {e}")


@app.post("/skills/upload", summary="上传 SKILL.md 或 zip 包创建 skill")
async def upload_skill(
    file: UploadFile = File(...),
    user_id: str = Depends(verify_token),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名为空")
    content = await file.read()

    if file.filename.endswith(".md"):
        if len(content) > 100_000:
            raise HTTPException(status_code=400, detail="文件过大，请控制在 100KB 以内")
        text = content.decode("utf-8", errors="replace")
        result, error = await skill_module.create_skill_from_upload(user_id, text)
    elif file.filename.endswith(".zip"):
        if len(content) > 50_000_000:
            raise HTTPException(status_code=400, detail="zip 包过大，请控制在 50MB 以内")
        result, error = await skill_module.create_skill_from_zip(user_id, content)
    else:
        raise HTTPException(status_code=400, detail="请上传 .md 或 .zip 格式的 skill 文件")

    if error:
        raise HTTPException(status_code=400, detail=error)
    return result


@app.put("/skills/{skill_id}", summary="编辑自己的 skill 内容")
async def update_skill(
    skill_id: str, req: SkillUpdateRequest, user_id: str = Depends(verify_token),
):
    result = await skill_module.update_skill(
        user_id, skill_id, req.name.strip(), req.description.strip(),
        req.tags.strip(), req.body,
    )
    if not result:
        raise HTTPException(status_code=404, detail="skill 不存在或非自建")
    return result


@app.get("/skills/market", summary="浏览 skill 市场（全平台公开）")
async def market_skills(
    tag: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
    user_id: str = Depends(verify_token),
):
    return await skill_module.list_market_skills(user_id, tag, keyword, page, size)


@app.get("/skills/market/growth", summary="市场技能累计增长曲线")
async def market_growth(user_id: str = Depends(verify_token)):
    return {"points": await skill_module.market_growth()}


@app.get("/skills/{skill_id}", summary="获取 skill 详情")
async def get_skill(skill_id: str, user_id: str = Depends(verify_token)):
    result = await skill_module.get_skill(user_id, skill_id)
    if not result:
        raise HTTPException(status_code=404, detail="skill 不存在")
    return result


@app.patch("/skills/{skill_id}", summary="切换 skill 公开状态")
async def set_skill_shared(
    skill_id: str, req: SkillSharedRequest, user_id: str = Depends(verify_token),
):
    updated = await skill_module.set_shared(user_id, skill_id, req.shared)
    if not updated:
        raise HTTPException(status_code=404, detail="skill 不存在或非自建")
    return {"skill_id": skill_id, "shared": req.shared}


@app.patch("/skills/{skill_id}/enabled", summary="切换 skill 启用状态")
async def set_skill_enabled(
    skill_id: str, req: SkillEnabledRequest, user_id: str = Depends(verify_token),
):
    updated = await skill_module.set_enabled(user_id, skill_id, req.enabled)
    if not updated:
        raise HTTPException(status_code=404, detail="skill 不存在")
    return {"skill_id": skill_id, "enabled": req.enabled}


@app.delete("/skills/{skill_id}", summary="删除 skill")
async def delete_skill(skill_id: str, user_id: str = Depends(verify_token)):
    deleted = await skill_module.delete_skill(user_id, skill_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="skill 不存在")
    return {"skill_id": skill_id, "deleted": True}


@app.post("/skills/install", summary="从市场安装 skill（快照拷贝）")
async def install_skill(req: SkillInstallRequest, user_id: str = Depends(verify_token)):
    try:
        result = await skill_module.install_skill(
            user_id, req.author_id, req.author_skill_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("安装 skill 失败")
        raise HTTPException(status_code=500, detail=f"安装失败: {e}")


@app.post("/skills/check-updates", summary="检查已安装 skill 是否有更新")
async def check_skill_updates(user_id: str = Depends(verify_token)):
    updates = await skill_module.check_updates(user_id)
    return {"updates": updates}


@app.post("/skills/{skill_id}/sync", summary="同步原作者最新版到本地副本")
async def sync_skill(skill_id: str, user_id: str = Depends(verify_token)):
    try:
        result = await skill_module.sync_skill(user_id, skill_id)
        if not result:
            raise HTTPException(status_code=404, detail="skill 不存在或非已安装")
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("同步 skill 失败")
        raise HTTPException(status_code=500, detail=f"同步失败: {e}")


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

    RAG 采用 combined 模式（SDK 文档推荐）：
    - static 模式（MultiTenantRAGMiddleware）：每次回复首个推理步骤前自动检索，
      确保即使用户未显式提问也能获得知识库上下文。多租户隔离通过 contextvar
      在 on_reasoning 时动态构造带 metadata_filter 的知识库句柄实现。
    - agentic 模式（SearchKnowledge 工具）：Agent 自主决定何时额外检索，
      适合后续追问或需要更精确查询的场景。
    二者共用同一套 contextvar（user_id + use_kb），开关关闭时均跳过检索。
    """
    memory_middleware = AgenticMemoryMiddleware(
        workdir=_user_memory_workdir(user_id),
        parameters=AgenticMemoryMiddleware.Parameters(
            retrieval_model=_memory_model,
        ),
    )
    # 知识库 RAG（static 模式）：search_knowledge 工具（agentic 模式）已全局
    # 注册到 _toolkit，通过 contextvar 按请求解析当前用户。static 中间件确保
    # 每次回复自动检索，agentic 工具允许 Agent 按需追加检索。
    middlewares = [memory_middleware, _ToolSchemaSanitizer()]
    if kb.is_ready():
        middlewares.insert(0, kb.MultiTenantRAGMiddleware())
    return Agent(
        name="office_assistant",
        system_prompt=SYSTEM_PROMPT,
        model=_model,
        toolkit=_toolkit,
        react_config=_react_config,
        context_config=_context_config,
        injection_config=_injection_config,
        offloader=_workspace,
        middlewares=middlewares,
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


def _sanitize_path(text: str) -> str:
    """清除文本中的服务器绝对路径，防止向前端泄露。

    将 SERVICE_ROOT 及其子路径、以及 /opt/conda 等服务器专属路径
    替换为可读的占位标记，保留文件名部分供用户辨识。
    """
    if not text:
        return text

    # 延迟初始化：首次调用时构造正则（路径在运行时才确定）
    if not hasattr(_sanitize_path, "_pattern"):
        roots = [
            str(MEMORY_DIR),
            str(WORKSPACE_DIR),
            str(UPLOAD_DIR),
            str(SERVICE_ROOT),
        ]
        # 按长度降序排列，确保最长路径先匹配（子路径优先于父路径）
        roots.sort(key=len, reverse=True)
        # 构造合并正则：匹配任一 root 后可选跟文件路径
        combined = "|".join(re.escape(r) for r in roots)
        _sanitize_path._pattern = re.compile(
            rf"(?:{combined})(/[^\s\)\]\"']*)?"
        )

    def _replacer(m: re.Match) -> str:
        suffix = m.group(1)
        return f"<server>{suffix}" if suffix else "<server>"

    result = _sanitize_path._pattern.sub(_replacer, text)

    # 清除 /opt/conda 环境路径
    result = re.sub(
        r"/opt/conda/envs/[^\s/]+(?:/[^\s\)\]\"']*)?",
        "<server>",
        result,
    )

    return result


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
            cleaned = _sanitize_path(delta)
            assistant["thinking"] += cleaned
            payloads.append({"type": "thinking", "content": cleaned})

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
        cleaned = _sanitize_path(delta)
        _assistant_tool(assistant, cid)["args"] += cleaned
        payloads.append({"type": "tool_args", "id": cid, "content": cleaned})

    elif event_type == "ToolResultTextDeltaEvent":
        cid = getattr(event, "tool_call_id", "")
        delta = getattr(event, "delta", "") or ""
        cleaned = _sanitize_path(delta)
        _assistant_tool(assistant, cid)["result"] += cleaned
        # 检索工具结果为结构化 JSON：仍累积供结束时解析，但不下发增量，
        # 避免前端工具区显示原始 JSON（画廊帧已足够）。
        if not _is_retrieval_tool(_assistant_tool(assistant, cid)["name"]):
            payloads.append({"type": "tool_result_delta", "id": cid, "content": cleaned})

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
            cleaned = _sanitize_path(hint)
            assistant["hint"] += cleaned
            payloads.append({"type": "hint", "content": cleaned})

    elif event_type == "ExceedMaxItersEvent":
        assistant["content"] = "已达最大推理轮数，请尝试简化问题或提供更多信息。"
        payloads.append({"type": "error", "content": assistant["content"]})

    elif event_type == "ReplyEndEvent":
        error = getattr(event, "error", None)
        if error:
            msg = _sanitize_path(str(error))
            assistant["content"] = f"处理出错：{msg}"
            payloads.append({"type": "error", "content": msg})
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

    # 注入当前用户与知识库检索开关到 contextvar（search_knowledge 工具据此
    # 解析属主、决定是否放行；asyncio.create_task 拷贝上下文，回复任务能继承此值）。
    # 关闭检索时 check_permissions 返回 DENY，工具不返回任何知识库内容。
    kb.set_kb_context(user_id, req.use_kb)
    # Skill 系统同样通过 contextvar 按请求解析当前用户
    skill_module.set_skill_context(user_id)

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
                    err_msg = _sanitize_path(str(event))
                    assistant["content"] = f"处理请求时出错：{err_msg}"
                    yield _sse({
                        "type": "error",
                        "content": f"处理出错: {err_msg}",
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

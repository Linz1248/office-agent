"""个人知识库 RAG 模块。

复用 document_extract 的 ``/doc_text`` 抽取全文（已含 PDF / Word / Excel / 图片 OCR
与文本缓存），本地 ``ApproxTokenChunker`` 分块 → Ollama 嵌入 → Qdrant 本地
持久化索引；``search_knowledge`` 工具全局注册到 Agent Toolkit，对话中 Agent 自主
决定何时检索用户个人知识库与全平台公开文档（agentic RAG）。

多租户与共享：单一 collection，每个 chunk 的 ``metadata`` 带 ``owner``（属主）与
``shared``（是否公开）。检索时构造两个 ``KnowledgeBase`` 句柄：

  - ``kb_own``    filter={"owner": <user>}      → 本人全部文档（无论是否共享）
  - ``kb_shared`` filter={"shared": True}       → 全平台已公开文档（含本人公开的，
    与 kb_own 的重叠按 (document_id, chunk_index) 去重）

切换文档共享：Qdrant 本地模式 set_payload 不支持嵌套路径原地改值，故采用
「删除旧点 + 按新 shared 重新入库」的确定性方式（切换操作低频，可接受）。

工具按请求解析当前用户：``/chat`` 在创建 Agent 前将 user_id 写入 contextvar，
``SearchKnowledge.call`` 读取之，故同一 Toolkit 可跨用户共享、无需为每个用户重建
（避免重复枚举 MCP 工具）。

依赖：``qdrant-client``（已随实现安装）；嵌入模型使用 AgentScope 内置
``OllamaEmbeddingModel``（自动批处理/重试/合并），需先 ``ollama pull <model>``。
Ollama 或模型不可用时优雅降级（``is_ready()`` 返回 False，
不注册 search_knowledge 工具，KB 接口返回 503，其余能力正常）。
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from contextvars import ContextVar
from typing import Any, Awaitable, Callable

import aiosqlite
import httpx
from agentscope.credential import OllamaCredential
from agentscope.embedding import OllamaEmbeddingModel
from agentscope.message import TextBlock, ToolResultState
from agentscope.middleware import RAGMiddleware
from agentscope.rag import (
    ApproxTokenChunker,
    KnowledgeBase,
    QdrantStore,
    TextParser,
)
from agentscope.tool import ToolBase, ToolChunk
from config import (
    DOC_EXTRACT_URL,
    KB_CHUNK_OVERLAP,
    KB_CHUNK_SIZE,
    KB_COLLECTION,
    KB_DB_PATH,
    KB_EMBEDDING_DIM,
    KB_EMBEDDING_MODEL,
    KB_OLLAMA_HOST,
    KB_FILES_DIR,
    KB_QDRANT_PATH,
    KB_SCORE_THRESHOLD,
    KB_SEARCH_TOP_K,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(_h)
logger.propagate = False


# ── 文件名安全化（与 main._user_memory_workdir 一致，防路径穿越）────────────
def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", s).strip("._-") or "default"


# ── 全局资源（lifespan 中初始化）──────────────────────────────────────────
_embedding_model = None
_vector_store: QdrantStore | None = None
_chunker: ApproxTokenChunker | None = None
_text_parser: TextParser | None = None
_kb_ready = False
_db: aiosqlite.Connection | None = None
# 由 main.py lifespan 注入（复用其 httpx 客户端与 document_extract token 获取器，
# 避免重复维护一份 token 缓存与连接池）
_http_client: httpx.AsyncClient | None = None
_get_extract_token: Callable[[], Awaitable[str]] | None = None

# 异步处理任务注册表：key = doc_id，避免同一文档并发重复处理
_processing: dict[str, asyncio.Task] = {}


def is_ready() -> bool:
    """知识库功能是否就绪（嵌入模型 + 向量库 + DB 均已初始化）。"""
    return _kb_ready


# ── 元数据 DB ─────────────────────────────────────────────────────────────
async def _init_db() -> None:
    global _db
    _db = await aiosqlite.connect(str(KB_DB_PATH))
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute(
        """
        CREATE TABLE IF NOT EXISTS kb_documents (
            user_id      TEXT NOT NULL,
            doc_id       TEXT NOT NULL,
            filename     TEXT NOT NULL,
            file_ext     TEXT,
            shared       INTEGER NOT NULL DEFAULT 0,
            enabled      INTEGER NOT NULL DEFAULT 1,
            chars        INTEGER NOT NULL DEFAULT 0,
            chunk_count  INTEGER NOT NULL DEFAULT 0,
            status       TEXT NOT NULL,        -- pending / processing / ready / failed
            error        TEXT,
            text         TEXT,                -- 全文缓存（重新索引/预览用）
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL,
            PRIMARY KEY (user_id, doc_id)
        )
        """
    )
    # 增量迁移：为旧表补充 enabled 列（默认 1，即启用）
    cursor = await _db.execute("PRAGMA table_info(kb_documents)")
    columns = {row[1] for row in await cursor.fetchall()}
    await cursor.close()
    if columns and "enabled" not in columns:
        await _db.execute(
            "ALTER TABLE kb_documents ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1"
        )
        logger.info("已为 kb_documents 表补充列: enabled")
    await _db.execute(
        """
        CREATE TABLE IF NOT EXISTS kb_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    await _db.commit()


async def _meta_get(key: str) -> str | None:
    if _db is None:
        return None
    cur = await _db.execute("SELECT value FROM kb_meta WHERE key=?", (key,))
    r = await cur.fetchone()
    await cur.close()
    return r[0] if r else None


async def _meta_set(key: str, value: str) -> None:
    if _db is None:
        return
    await _db.execute(
        "INSERT INTO kb_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    await _db.commit()


async def _close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


def _now() -> str:
    return str(int(time.time() * 1000))


async def _get_collection_dim() -> int | None:
    """读取已存在 collection 的向量维度；不存在或读取失败返回 None。

    用作嵌入模型变更的 ground-truth 探测：维度与当前模型不符即需迁移重建，
    不依赖可能失同步的元数据，可自愈（此前曾出现元数据先于迁移被写入、
    导致后续启动误判「无需迁移」的半状态）。
    """
    if _vector_store is None:
        return None
    try:
        from qdrant_client.models import VectorParams

        client = _vector_store.get_client()
        info = await client.get_collection(collection_name=KB_COLLECTION)
        vectors = info.config.params.vectors
        if isinstance(vectors, VectorParams):
            return vectors.size
        if isinstance(vectors, dict) and vectors:
            for v in vectors.values():
                return getattr(v, "size", None)
    except Exception:
        return None
    return None


# ── 初始化 ─────────────────────────────────────────────────────────────────
async def init_kb(
    http_client: httpx.AsyncClient,
    get_extract_token: Callable[[], Awaitable[str]],
) -> bool:
    """初始化嵌入模型 / 向量库 / 分块器 / 元数据库。

    注入 main.py 已有的 httpx 客户端与 document_extract token 获取器，
    复用其连接池与 token 缓存，不重复维护。任一致命依赖不可用时优雅降级，
    返回 False（不注册 search_knowledge 工具，KB 接口返回 503，其余能力不受影响）。
    """
    global _embedding_model, _vector_store, _chunker, _kb_ready
    global _http_client, _get_extract_token, _text_parser

    _http_client = http_client
    _get_extract_token = get_extract_token

    KB_QDRANT_PATH.mkdir(parents=True, exist_ok=True)
    KB_FILES_DIR.mkdir(parents=True, exist_ok=True)

    await _init_db()

    try:
        _embedding_model = OllamaEmbeddingModel(
            credential=OllamaCredential(host=KB_OLLAMA_HOST),
            model=KB_EMBEDDING_MODEL,
            dimensions=KB_EMBEDDING_DIM,
        )
        _vector_store = QdrantStore(path=str(KB_QDRANT_PATH), distance="Cosine")
        _chunker = ApproxTokenChunker(
            chunk_size=KB_CHUNK_SIZE, overlap=KB_CHUNK_OVERLAP
        )
        _text_parser = TextParser()

        # 嵌入模型变更检测：旧向量与新模型向量空间不兼容。
        # 触发条件（满足其一即迁移：删旧 collection 重建 + 用缓存全文重索引）：
        #   ① 实际 collection 向量维度 ≠ 当前模型维度（维度变更，ground truth，可自愈）；
        #   ② 元数据记录的模型名 ≠ 当前模型（同维度但换模型的情况）。
        # 首启（无 collection、无文档）时维度探测返回 None、无模型记录，不触发。
        existing_dim = await _get_collection_dim()
        stored_model = await _meta_get("embedding_model")
        model_changed = (
            (existing_dim is not None and existing_dim != KB_EMBEDDING_DIM)
            or (stored_model is not None and stored_model != KB_EMBEDDING_MODEL)
        )
        if model_changed:
            logger.info(
                "嵌入模型/维度变更（dim %s→%s, model %s→%s），重建集合并重索引已有文档",
                existing_dim, KB_EMBEDDING_DIM,
                stored_model, KB_EMBEDDING_MODEL,
            )
            try:
                client = _vector_store.get_client()
                await client.delete_collection(collection_name=KB_COLLECTION)
            except Exception as e:
                logger.warning("删除旧 collection 失败（可能本就不存在）: %s", e)

        # 预建 collection（幂等），并在此时探测嵌入服务是否可用：
        # ensure_collection 会调用嵌入模型取维度，Ollama 不可用即抛异常
        handle = KnowledgeBase(
            name="office-kb",
            description="office-agent 个人知识库",
            embedding_model=_embedding_model,
            vector_store=_vector_store,
            collection=KB_COLLECTION,
        )
        await handle.ensure_collection()

        # 模型变更后用缓存全文重索引所有 ready 文档（恢复向量）
        if model_changed:
            await _reindex_all_ready()

        await _meta_set("embedding_model", KB_EMBEDDING_MODEL)
        _kb_ready = True
        logger.info(
            "知识库就绪: collection=%s, embedding=%s(%dD), chunk=%d/%d",
            KB_COLLECTION, KB_EMBEDDING_MODEL, KB_EMBEDDING_DIM,
            KB_CHUNK_SIZE, KB_CHUNK_OVERLAP,
        )
    except Exception as e:
        _kb_ready = False
        logger.warning(
            "知识库初始化失败，已优雅降级（KB 功能不可用，其余能力正常）: %s", e
        )
    return _kb_ready


async def close_kb() -> None:
    """关闭向量库客户端与元数据库。

    OllamaEmbeddingModel 内部使用 ollama.AsyncClient（每次调用即建即关，
    无长连接需关闭），故仅关闭向量库客户端与元数据库。
    """
    global _vector_store, _embedding_model
    if _vector_store is not None:
        try:
            await _vector_store.__aexit__(None, None, None)
        except Exception:
            pass
        _vector_store = None
    _embedding_model = None
    await _close_db()


# ── KnowledgeBase 句柄工厂 ──────────────────────────────────────────────────
def _insert_handle(user_id: str) -> KnowledgeBase:
    """构造插入句柄：metadata_filter 仅含 owner（不含 enabled），
    避免插入时 enabled 被 filter 覆盖为 True（SDK 中 metadata_filter
    优先级最高，会盖过 document_metadata 中的 enabled=False）。
    """
    return KnowledgeBase(
        name="office-kb",
        description="office-agent 个人知识库",
        embedding_model=_embedding_model,
        vector_store=_vector_store,
        collection=KB_COLLECTION,
        metadata_filter={"owner": user_id},
    )


def _search_handle(user_id: str, *, owner_filter: bool, shared_filter: bool) -> KnowledgeBase:
    """构造检索句柄：metadata_filter 含 owner/shared + enabled=True，
    确保禁用的文档不出现在检索结果中。
    """
    flt: dict[str, Any]
    if owner_filter:
        flt = {"owner": user_id, "enabled": True}
    elif shared_filter:
        flt = {"shared": True, "enabled": True}
    else:
        flt = {"enabled": True}
    return KnowledgeBase(
        name="office-kb",
        description="office-agent 个人知识库",
        embedding_model=_embedding_model,
        vector_store=_vector_store,
        collection=KB_COLLECTION,
        metadata_filter=flt,
    )


def search_handles(user_id: str) -> list[KnowledgeBase]:
    """检索句柄：[本人已启用文档, 全平台已公开且已启用文档]，供 search() 与工具共用。"""
    return [
        _search_handle(user_id, owner_filter=True, shared_filter=False),
        _search_handle(user_id, owner_filter=False, shared_filter=True),
    ]


# ── 当前请求上下文（供共享 search_knowledge 工具按请求解析属主与开关）────────
# /chat 在创建 Agent 前调用 set_kb_context(user_id, use_kb)；工具 call() 与
# check_permissions() 时读取之。同一 Toolkit 在所有会话间共享，工具按 contextvar
# 区分当前用户与检索开关，避免为每个用户/每条请求重建 Toolkit（含 MCP 工具枚举，
# 开销大）。asyncio.create_task 会拷贝上下文，故请求协程内创建的回复任务能继承本值。
_current_user: ContextVar[str] = ContextVar("kb_current_user", default="")
_use_kb: ContextVar[bool] = ContextVar("kb_use_kb", default=False)


def set_kb_context(user_id: str, use_kb: bool) -> None:
    _current_user.set(user_id)
    _use_kb.set(bool(use_kb))


class MultiTenantRAGMiddleware(RAGMiddleware):
    """支持多租户动态隔离的 RAG 中间件（static 模式）。

    继承 SDK 的 ``RAGMiddleware``，在 static 模式下于每次回复的首个推理步骤前
    自动检索，确保即使用户未显式提问也能获得知识库上下文。

    与 SDK 原版 ``RAGMiddleware`` 的区别：知识库句柄不在构造时固定，而是
    在 ``on_reasoning`` 时从 contextvar 解析当前用户，动态构造带
    ``metadata_filter`` 的句柄实现多租户隔离。这与项目的 ``SearchKnowledge``
    工具（agentic 模式）共用同一套 contextvar，二者协同工作。

    知识库未就绪或用户关闭检索开关时，``on_reasoning`` 跳过检索，不注入 hint。
    """

    def __init__(
        self,
        top_k: int = KB_SEARCH_TOP_K,
        score_threshold: float = KB_SCORE_THRESHOLD,
    ) -> None:
        super().__init__(
            knowledge_bases=[],  # 不在构造时绑定，on_reasoning 时动态构造
            parameters=RAGMiddleware.Parameters(
                mode="static",
                top_k=top_k,
                score_threshold=score_threshold,
                emit_hint_event=True,
            ),
        )

    async def on_reasoning(
        self, agent, input_kwargs, next_handler
    ):
        """在首个推理步骤前自动检索用户知识库并注入 HintBlock。

        重写父类方法：不使用构造时绑定的 ``self._knowledge_bases``，
        而是从 contextvar 解析当前用户，动态构造检索句柄。
        """
        from agentscope.event import HintBlockEvent
        from agentscope.message import HintBlock

        hint = None

        if (
            agent.state.cur_iter == 0
            and self._cached_inputs
            and _use_kb.get()
            and _kb_ready
        ):
            user_id = _current_user.get()
            if user_id:
                try:
                    results = await _search_across(
                        search_handles(user_id),
                        self._cached_inputs,
                        top_k=self._parameters.top_k,
                        score_threshold=self._parameters.score_threshold,
                    )
                except Exception:
                    logger.exception(
                        "知识库 static 模式检索失败，跳过注入"
                    )
                    results = []

                blocks = _format_results(results)
                if blocks:
                    hint = HintBlock(
                        hint=blocks[0].text,
                        source="kb",
                    )
                    agent.state.append_context(agent.name, [hint])
                    if self._parameters.emit_hint_event:
                        yield HintBlockEvent(
                            reply_id=agent.state.reply_id,
                            block_id=hint.id,
                            source=hint.source,
                            hint=hint.hint,
                        )

        try:
            async for evt in next_handler(**input_kwargs):
                yield evt
        finally:
            if hint is not None and not self._parameters.persist_hint:
                for msg in reversed(agent.state.context):
                    if msg.id != agent.state.reply_id:
                        continue
                    msg.content = [
                        b for b in msg.content if b.id != hint.id
                    ]
                    break


class SearchKnowledge(ToolBase):
    """在用户个人知识库（本人文档 + 全平台公开文档）中检索相关片段。

    Agent 自主决定是否调用（agentic RAG）：用户问题涉及已上传文档内容时检索，
    普通闲聊/通用问答无需调用。检索结果以文本形式返回，Agent 据此作答并注明出处。
    当前用户由 contextvar 解析（/chat 注入），故本工具可全局共享注册一次。
    """

    name = "search_knowledge"
    description = (
        "在用户个人知识库与全平台公开文档中，按语义检索与问题相关的文档片段。"
        "用户在「知识库」页上传文档后会自动抽取全文并建立索引。"
        "当用户的问题涉及已上传文档的内容（如「根据我的资料…」"
        "「我上传的文档里提到…」「找一下资料中关于 X 的内容」）时调用此工具，"
        "检索结果作为上下文片段返回，据此作答并注明出处文档。"
        "不涉及用户文档的通用问题无需调用。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "检索用的自然语言问题或关键词。",
            },
            "top_k": {
                "type": "integer",
                "description": "返回的最相关片段数量，默认 5。",
                "default": 5,
            },
        },
        "required": ["query"],
    }
    is_external_tool = False
    is_concurrency_safe = True
    is_read_only = True

    async def check_permissions(self, tool_input: dict, context):
        # 只读检索，无副作用；放行。（开关控制在 call() 内做：agent 运行于
        # BYPASS 权限模式以放行 MCP 工具，该模式会跳过 check_permissions，
        # 故开关须在 call() 里判定，不能依赖权限 DENY。）
        from agentscope.permission import PermissionBehavior, PermissionDecision

        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="search_knowledge 仅做只读检索，无副作用。",
        )

    async def call(self, **kwargs: Any) -> ToolChunk:
        # 硬开关：用户未开启「知识库检索」时不检索、不返回任何知识库内容。
        # 在 call() 而非 check_permissions 判定，因 agent 用 BYPASS 模式放行
        # MCP 工具会跳过权限检查。
        if not _use_kb.get():
            return ToolChunk(
                content=[TextBlock(
                    text="知识库检索未启用（用户已关闭「知识库检索」开关），本次不使用 RAG。"
                    "请勿重试本工具，直接据通用知识作答，并提示用户："
                    "如需检索其上传文档，可在对话框开启「知识库检索」开关后再问。"
                )],
                state=ToolResultState.SUCCESS,
                is_last=True,
            )
        query = (kwargs.get("query") or "").strip()
        if not query:
            return ToolChunk(
                content=[TextBlock(text="检索词为空。")],
                state=ToolResultState.SUCCESS,
                is_last=True,
            )
        user_id = _current_user.get()
        if not _kb_ready or not user_id:
            return ToolChunk(
                content=[TextBlock(text="知识库未就绪或当前用户未知，无法检索。")],
                state=ToolResultState.SUCCESS,
                is_last=True,
            )
        top_k = int(kwargs.get("top_k") or KB_SEARCH_TOP_K)
        try:
            results = await _search_across(
                search_handles(user_id),
                [query],
                top_k=top_k,
                score_threshold=KB_SCORE_THRESHOLD,
            )
        except Exception as e:
            logger.warning("search_knowledge 检索失败: %s", e)
            return ToolChunk(
                content=[TextBlock(text=f"检索失败：{e}")],
                state=ToolResultState.ERROR,
                is_last=True,
            )
        blocks = _format_results(results)
        if not blocks:
            return ToolChunk(
                content=[TextBlock(text="未检索到相关文档片段。")],
                state=ToolResultState.SUCCESS,
                is_last=True,
            )
        return ToolChunk(
            content=blocks,
            state=ToolResultState.SUCCESS,
            is_last=True,
        )


async def _search_across(
    knowledge_bases: list[KnowledgeBase],
    queries: list,
    top_k: int,
    score_threshold: float | None,
) -> list:
    """并发检索所有知识库并合并去重（复用 SDK _search_across 的逻辑）。

    各 KnowledgeBase 句柄自带 metadata_filter 实现多租户隔离，
    并发检索后按分数倒序、截断到 top_k。
    """
    if not queries or not knowledge_bases:
        return []
    per_kb = await asyncio.gather(
        *(
            kb.search(
                queries=queries,
                top_k=top_k,
                score_threshold=score_threshold,
            )
            for kb in knowledge_bases
        ),
    )
    # 去重：同一 (document_id, chunk_index) 保留最高分
    seen: dict[tuple, float] = {}
    merged: list = []
    for r in (r for sub in per_kb for r in sub):
        key = (r.document_id, r.chunk.chunk_index)
        if key in seen:
            if r.score <= seen[key]:
                continue
            merged = [x for x in merged if (x.document_id, x.chunk.chunk_index) != key]
        seen[key] = r.score
        merged.append(r)
    merged.sort(key=lambda r: r.score, reverse=True)
    return merged[:top_k]


def _format_results(results: list) -> list:
    """将检索结果格式化为带编号与来源的 TextBlock 列表（复用 SDK 模式）。

    每条结果格式为 ``[N] (source: filename)\\n<content>``，
    相邻文本片段合并为单个 TextBlock。
    """
    if not results:
        return []
    parts: list[str] = []
    for i, r in enumerate(results, 1):
        md = r.chunk.metadata or {}
        filename = md.get("filename", "") or "未命名"
        tag = "公开" if md.get("shared") else "私有"
        owner = md.get("owner", "")
        content = getattr(r.chunk.content, "text", "") or str(r.chunk.content)
        parts.append(
            f"[{i}] 来源：{filename}（{tag}，属主：{owner}）"
            f" 相似度 {round(float(r.score), 4)}\n{content}"
        )
    return [TextBlock(text="\n\n".join(parts))]


# ── 文档处理：抽取全文 → 分块 → 嵌入入库 ───────────────────────────────────
_EXTRACT_RETRY = 4
_EXTRACT_DELAY = 3.0


async def _extract_text(saved_name: str) -> str:
    """调用 document_extract /doc_text 取全文（含 401 重试与连接退避，复用注入的 token 获取器）。"""
    token = await _get_extract_token()
    url = f"{DOC_EXTRACT_URL}/doc_text"
    for attempt in range(1, _EXTRACT_RETRY + 1):
        try:
            resp = await _http_client.post(
                url,
                json={"filename": saved_name},
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 401:
                token = await _get_extract_token()
                continue
            resp.raise_for_status()
            return resp.json().get("text", "")
        except httpx.ConnectError:
            if attempt < _EXTRACT_RETRY:
                await asyncio.sleep(_EXTRACT_DELAY)
                continue
            raise
    raise RuntimeError("document_extract 不可达，无法抽取全文")


# 不直接依赖 main._forward_to_extract（其返回 saved_name 后即用），但上传需要它。
# 为复用已封装的「带 token/退避的上传」，由 main 注入该函数更省事；这里提供兼容入口。
_upload_fn: Callable[[str, bytes, str], Awaitable[str]] | None = None


def set_upload_fn(fn: Callable[[str, bytes, str], Awaitable[str]]) -> None:
    """注入 main._forward_to_extract（带 token/退避的 document_extract 上传）。"""
    global _upload_fn
    _upload_fn = _upload_fn or fn


async def _index_text(
    user_id: str, doc_id: str, filename: str, text: str,
    shared: bool, enabled: bool = True,
) -> int:
    """分块 + 嵌入入库（用 owner_filter 句柄自动盖 owner；shared/enabled 写入 chunk.metadata）。

    返回分块数。供首次索引与「切换共享/启用时重建索引」共用，保证 shared/enabled
    字段一定正确写入向量库（Qdrant 本地模式 set_payload 不支持嵌套路径原地改值，
    故切换采用「删除旧点 + 重新入库」的确定性方式）。
    """
    sections = await _text_parser.parse(file=text, filename=filename)
    chunks = await _chunker.chunk(sections)
    if not chunks:
        raise ValueError("分块结果为空")
    handle = _insert_handle(user_id)
    await handle.insert_document(
        chunks,
        document_id=doc_id,
        document_metadata={
            "shared": bool(shared),
            "enabled": bool(enabled),
            "filename": filename,
        },
    )
    return len(chunks)


async def _reindex_all_ready() -> None:
    """模型变更后，用缓存全文重新索引所有 ready 文档，恢复向量。

    旧 collection 已删除重建，故每篇文档先删残留点（空操作）再重新入库。
    失败的文档置 failed 态，避免遗留「ready 但无向量」的半状态。
    """
    if _db is None:
        return
    cur = await _db.execute(
        "SELECT user_id, doc_id, filename, text, shared, enabled "
        "FROM kb_documents "
        "WHERE status='ready' AND text IS NOT NULL AND text!=''"
    )
    rows = await cur.fetchall()
    await cur.close()
    if not rows:
        return
    logger.info("迁移重索引：共 %d 篇 ready 文档", len(rows))
    for user_id, doc_id, filename, text, shared, enabled in rows:
        try:
            try:
                await _insert_handle(
                    user_id
                ).delete_document(doc_id)
            except Exception:
                pass
            await _index_text(
                user_id, doc_id, filename, text,
                shared=bool(shared), enabled=bool(enabled),
            )
        except Exception as e:
            logger.warning("迁移重索引失败 doc=%s: %s", doc_id, e)
            await _db.execute(
                "UPDATE kb_documents SET status='failed', error=?, updated_at=? "
                "WHERE user_id=? AND doc_id=?",
                (f"嵌入模型变更后重索引失败: {e}"[:500], _now(), user_id, doc_id),
            )
    await _db.commit()
    logger.info("迁移重索引完成")


async def _process_document(user_id: str, doc_id: str, ext: str, filename: str) -> None:
    """后台处理一篇文档：上传抽取服务 → 取全文 → 分块 → 嵌入入库 → 更新元数据。"""
    if _db is None:
        return
    file_path = KB_FILES_DIR / _safe(user_id) / f"{doc_id}.{ext}"
    try:
        await _db.execute(
            "UPDATE kb_documents SET status='processing', updated_at=? "
            "WHERE user_id=? AND doc_id=?",
            (_now(), user_id, doc_id),
        )
        await _db.commit()

        content = file_path.read_bytes()
        if ext in ("txt", "md", "csv"):
            # 纯文本：document_extract 不支持，直接本地读取
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                text = content.decode("utf-8", errors="replace")
        else:
            # 1) 转发到 document_extract 取 saved_name（复用 main 的 token/退避逻辑）
            saved_name = await _upload_fn(filename, content, _content_type(ext))
            # 2) 取全文
            text = await _extract_text(saved_name)
        if not text.strip():
            raise ValueError("文档全文为空，无法建立索引")

        # 3) 分块 + 嵌入入库（shared=False，仅本人可见）
        chunk_count = await _index_text(user_id, doc_id, filename, text, shared=False)

        # 4) 更新元数据
        await _db.execute(
            "UPDATE kb_documents SET status='ready', chars=?, chunk_count=?, "
            "text=?, error=NULL, updated_at=? WHERE user_id=? AND doc_id=?",
            (len(text), chunk_count, text, _now(), user_id, doc_id),
        )
        await _db.commit()
        logger.info(
            "文档入库成功 user=%s doc=%s chunks=%d chars=%d",
            user_id, doc_id, chunk_count, len(text),
        )
    except Exception as e:
        logger.exception("文档入库失败 user=%s doc=%s", user_id, doc_id)
        await _db.execute(
            "UPDATE kb_documents SET status='failed', error=?, updated_at=? "
            "WHERE user_id=? AND doc_id=?",
            (str(e)[:500], _now(), user_id, doc_id),
        )
        await _db.commit()
    finally:
        _processing.pop(doc_id, None)


def schedule_process(user_id: str, doc_id: str, ext: str, filename: str) -> None:
    """异步处理一篇文档（若该文档尚未在处理则创建任务）。"""
    if doc_id in _processing:
        return
    task = asyncio.create_task(_process_document(user_id, doc_id, ext, filename))
    _processing[doc_id] = task


# ── 文件类型 ───────────────────────────────────────────────────────────────
_EXTS = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "doc": "application/msword",
    "xls": "application/vnd.ms-excel",
    "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png", "bmp": "image/bmp", "webp": "image/webp",
    "txt": "text/plain", "md": "text/markdown", "csv": "text/csv",
}


def supported_exts() -> list[str]:
    return sorted(_EXTS.keys())


def _content_type(ext: str) -> str:
    return _EXTS.get(ext, "application/octet-stream")


# ── CRUD ───────────────────────────────────────────────────────────────────
async def list_documents(user_id: str) -> list[dict]:
    if _db is None:
        return []
    cur = await _db.execute(
        "SELECT doc_id, filename, file_ext, shared, enabled, chars, "
        "chunk_count, status, error, created_at, updated_at "
        "FROM kb_documents WHERE user_id=? ORDER BY updated_at DESC",
        (user_id,),
    )
    rows = await cur.fetchall()
    await cur.close()
    return [
        {
            "doc_id": r[0], "filename": r[1], "file_ext": r[2],
            "shared": bool(r[3]), "enabled": bool(r[4]),
            "chars": r[5], "chunk_count": r[6],
            "status": r[7], "error": r[8],
            "created_at": int(r[9]) if r[9] else 0,
            "updated_at": int(r[10]) if r[10] else 0,
        }
        for r in rows
    ]


async def get_document(user_id: str, doc_id: str) -> dict | None:
    if _db is None:
        return None
    cur = await _db.execute(
        "SELECT doc_id, filename, file_ext, shared, enabled, chars, "
        "chunk_count, status, error, text, created_at, updated_at "
        "FROM kb_documents WHERE user_id=? AND doc_id=?",
        (user_id, doc_id),
    )
    r = await cur.fetchone()
    await cur.close()
    if not r:
        return None
    return {
        "doc_id": r[0], "filename": r[1], "file_ext": r[2],
        "shared": bool(r[3]), "enabled": bool(r[4]),
        "chars": r[5], "chunk_count": r[6],
        "status": r[7], "error": r[8], "text": r[9] or "",
        "created_at": int(r[10]) if r[10] else 0,
        "updated_at": int(r[11]) if r[11] else 0,
    }


async def create_document(
    user_id: str, filename: str, ext: str, content: bytes
) -> dict:
    """登记文档并启动后台索引。返回 doc_id（pending 状态）。"""
    doc_id = uuid.uuid4().hex
    (KB_FILES_DIR / _safe(user_id)).mkdir(parents=True, exist_ok=True)
    file_path = KB_FILES_DIR / _safe(user_id) / f"{doc_id}.{ext}"
    file_path.write_bytes(content)

    now = _now()
    await _db.execute(
        "INSERT INTO kb_documents "
        "(user_id, doc_id, filename, file_ext, shared, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 0, 'pending', ?, ?)",
        (user_id, doc_id, filename, ext, now, now),
    )
    await _db.commit()

    schedule_process(user_id, doc_id, ext, filename)
    return {"doc_id": doc_id, "status": "pending"}


async def set_shared(user_id: str, doc_id: str, shared: bool) -> bool:
    """切换文档公开状态：删除旧向量点 → 按新 shared 重建索引 → 更新元数据。

    Qdrant 本地模式 set_payload 不支持嵌套路径原地改 chunk.metadata.shared，
    故采用「删除 + 重新入库」的确定性方式（切换操作低频，重建可接受）。
    文档须处于 ready 状态（需有全文缓存）才能切换。
    """
    if _db is None:
        return False
    doc = await get_document(user_id, doc_id)
    if doc is None:
        return False
    if doc["status"] != "ready" or not doc["text"]:
        raise ValueError("文档尚未就绪，无法切换共享状态，请等待索引完成")

    # 1) 删除旧向量点（按 document_id）
    try:
        await _insert_handle(
            user_id
        ).delete_document(doc_id)
    except Exception as e:
        logger.warning("切换共享：删除旧向量点失败 doc=%s: %s", doc_id, e)

    # 2) 按新 shared 重建索引。失败则置 failed 态（旧点已删，避免留「就绪但无向量」
    #    的半状态），向上抛出由接口返回错误；用户可删除后重新上传。
    try:
        chunk_count = await _index_text(
            user_id, doc_id, doc["filename"], doc["text"],
            shared=shared, enabled=doc["enabled"],
        )
    except Exception as e:
        await _db.execute(
            "UPDATE kb_documents SET status='failed', error=?, updated_at=? "
            "WHERE user_id=? AND doc_id=?",
            (f"切换共享重建索引失败: {e}"[:500], _now(), user_id, doc_id),
        )
        await _db.commit()
        raise

    # 3) 更新元数据
    await _db.execute(
        "UPDATE kb_documents SET shared=?, chunk_count=?, status='ready', "
        "error=NULL, updated_at=? WHERE user_id=? AND doc_id=?",
        (1 if shared else 0, chunk_count, _now(), user_id, doc_id),
    )
    await _db.commit()
    logger.info("切换共享完成 user=%s doc=%s shared=%s", user_id, doc_id, shared)
    return True


async def set_enabled(user_id: str, doc_id: str, enabled: bool) -> bool:
    """切换文档启用状态：删除旧向量点 → 按新 enabled 重建索引 → 更新元数据。

    禁用的文档不参与检索（metadata_filter={"enabled": True} 过滤）。
    采用与 set_shared 相同的「删除 + 重新入库」方式保证确定性。
    文档须处于 ready 状态（需有全文缓存）才能切换。
    """
    if _db is None:
        return False
    doc = await get_document(user_id, doc_id)
    if doc is None:
        return False
    if doc["status"] != "ready" or not doc["text"]:
        raise ValueError("文档尚未就绪，无法切换启用状态，请等待索引完成")

    # 1) 删除旧向量点
    try:
        await _insert_handle(
            user_id
        ).delete_document(doc_id)
    except Exception as e:
        logger.warning("切换启用：删除旧向量点失败 doc=%s: %s", doc_id, e)

    # 2) 按新 enabled 重建索引
    try:
        chunk_count = await _index_text(
            user_id, doc_id, doc["filename"], doc["text"],
            shared=doc["shared"], enabled=enabled,
        )
    except Exception as e:
        await _db.execute(
            "UPDATE kb_documents SET status='failed', error=?, updated_at=? "
            "WHERE user_id=? AND doc_id=?",
            (f"切换启用重建索引失败: {e}"[:500], _now(), user_id, doc_id),
        )
        await _db.commit()
        raise

    # 3) 更新元数据
    await _db.execute(
        "UPDATE kb_documents SET enabled=?, chunk_count=?, status='ready', "
        "error=NULL, updated_at=? WHERE user_id=? AND doc_id=?",
        (1 if enabled else 0, chunk_count, _now(), user_id, doc_id),
    )
    await _db.commit()
    logger.info("切换启用完成 user=%s doc=%s enabled=%s", user_id, doc_id, enabled)
    return True


async def delete_document(user_id: str, doc_id: str) -> bool:
    """删除文档：向量点 + 元数据行 + 原始文件。"""
    if _db is None:
        return False
    # 取 ext 以删文件
    cur = await _db.execute(
        "SELECT file_ext FROM kb_documents WHERE user_id=? AND doc_id=?",
        (user_id, doc_id),
    )
    row = await cur.fetchone()
    await cur.close()
    if not row:
        return False

    # 删向量点（按 document_id，delete_document 不过滤属主，doc_id 全局唯一故安全）
    if _kb_ready and _vector_store is not None:
        try:
            handle = _insert_handle(user_id)
            await handle.delete_document(doc_id)
        except Exception as e:
            logger.warning("删除向量点失败 doc=%s: %s", doc_id, e)

    cur = await _db.execute(
        "DELETE FROM kb_documents WHERE user_id=? AND doc_id=?",
        (user_id, doc_id),
    )
    await _db.commit()
    deleted = cur.rowcount > 0
    await cur.close()

    ext = row[0] or ""
    file_path = KB_FILES_DIR / _safe(user_id) / f"{doc_id}.{ext}"
    try:
        if file_path.exists():
            file_path.unlink()
    except Exception:
        pass
    return deleted


# ── 显式检索（供前端「知识检索」页与调试用）──────────────────────────────
async def search(user_id: str, query: str, top_k: int = KB_SEARCH_TOP_K) -> list[dict]:
    """检索本人 + 全平台公开文档，去重后按分数倒序返回。

    复用 ``_search_across`` 的并发检索与去重逻辑，仅做 dict 序列化供前端。
    """
    if not _kb_ready:
        return []
    try:
        results = await _search_across(
            search_handles(user_id),
            [query],
            top_k=top_k,
            score_threshold=KB_SCORE_THRESHOLD,
        )
    except Exception as e:
        logger.warning("知识库检索失败: %s", e)
        return []
    merged: list[dict] = []
    for r in results:
        chunk = r.chunk
        md = chunk.metadata or {}
        content = getattr(chunk.content, "text", "") or str(chunk.content)
        merged.append({
            "doc_id": r.document_id,
            "filename": md.get("filename", ""),
            "owner": md.get("owner", ""),
            "shared": bool(md.get("shared", False)),
            "chunk_index": chunk.chunk_index,
            "total_chunks": chunk.total_chunks,
            "score": round(float(r.score), 4),
            "content": content,
        })
    return merged

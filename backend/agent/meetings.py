"""飞书会议模块：自动接收 -> 子 agent 分析 -> 待办提醒 -> 会议知识库。

整体链路（对应用户需求 1-5）：

  自动接收（需求 1）：后台定时轮询（MEETING_SYNC_INTERVAL）每个已启用飞书
  账号，按「参会人 = 本人 open_id」搜索最近回看窗口内的已结束会议，拉取
  妙记/智能纪要正文，无需用户手动上传。

  子 agent 处理（需求 2）：每场会议由「会议分析师」子 agent（AgentScope
  Agent + structured_schema 结构化输出）生成摘要、要点与待办；主对话
  agent 通过 process_meeting / list_my_meetings 工具委派子 agent 并收集
  结果（Orchestrator-Workers 模式）。

  我的待办（需求 3）：子 agent 结合长期记忆（memory_graph）召回的用户画像
  判断每条待办是否属于本人（is_mine = yes / unsure）；不确定的保留为
  pending_confirm 状态，由用户在「飞书会议」页手动确认或拒绝。

  定时提醒（需求 4）：待办确认后按截止时间提前提醒（应用内通知为默认通道，
  用户可在设置中启用邮件 SMTP / 微信 Server酱 通知）。

  会议知识库（需求 5）：会议正文写入独立 Qdrant 集合（office_meetings），
  与个人知识库（kb_qdrant / office_kb）物理隔离；对话框的「会议检索」开关
  （/chat use_meeting_kb）控制 search_meeting_knowledge 工具是否可用。

模块可拔插：飞书未配置的账号自动跳过；Ollama 嵌入不可用时会议知识库优雅
降级（其余能力正常）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import smtplib
import time
import uuid
from contextvars import ContextVar
from email.mime.text import MIMEText
from typing import Any

import aiosqlite
import httpx
from agentscope.agent import Agent
from agentscope.credential import OllamaCredential
from agentscope.embedding import OllamaEmbeddingModel
from agentscope.message import TextBlock, ToolResultState, UserMsg
from agentscope.rag import (
    ApproxTokenChunker,
    KnowledgeBase,
    QdrantStore,
    TextParser,
)
from agentscope.tool import ToolBase, ToolChunk
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from typing import Literal

import feishu
import memory_graph
from config import (
    FEISHU_OAUTH_REDIRECT_URI,
    KB_EMBEDDING_DIM,
    KB_EMBEDDING_MODEL,
    KB_OLLAMA_HOST,
    MEETING_COLLECTION,
    MEETING_DB_PATH,
    MEETING_EMPTY_AFTER_MINUTES,
    MEETING_QDRANT_PATH,
    MEETING_REMIND_LEAD_MINUTES,
    MEETING_REMINDER_INTERVAL,
    MEETING_SEARCH_TOP_K,
    MEETING_SYNC_INTERVAL,
    MEETING_SYNC_LOOKBACK_DAYS,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USE_SSL,
    SMTP_USER,
    WECHAT_SEND_API,
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

# 会议正文截断上限（字符）：过长逐字稿只保留前段，分析摘要场景足够
_CONTENT_LIMIT = 24_000


# ── 全局资源（main.py lifespan 注入）─────────────────────────────────
_db: aiosqlite.Connection | None = None
_http_client: httpx.AsyncClient | None = None
_chat_model = None  # 会议分析子 agent 模型（非流式/低温度）
_embedding_model: OllamaEmbeddingModel | None = None
_vector_store: QdrantStore | None = None
_chunker: ApproxTokenChunker | None = None
_text_parser: TextParser | None = None
_meeting_kb_ready = False
_sync_task: asyncio.Task | None = None
_reminder_task: asyncio.Task | None = None


def is_kb_ready() -> bool:
    """会议知识库是否就绪（嵌入模型 + 向量库可用）。"""
    return _meeting_kb_ready


# ── 请求上下文（共享 Toolkit 按请求解析当前用户与会议检索开关）──────
_current_user: ContextVar[str] = ContextVar("meeting_current_user", default="")
_use_meeting_kb: ContextVar[bool] = ContextVar("meeting_use_kb", default=False)


def set_meeting_context(user_id: str, use_meeting_kb: bool) -> None:
    """由 /chat 在创建 Agent 前注入当前用户与「会议检索」开关。"""
    _current_user.set(user_id)
    _use_meeting_kb.set(bool(use_meeting_kb))


# ── 初始化 / 关闭 ─────────────────────────────────────────────────────
async def init_meetings(http_client: httpx.AsyncClient, chat_model) -> None:
    """初始化会议模块：元数据库 + 会议知识库（嵌入不可用时优雅降级）。"""
    global _db, _http_client, _chat_model
    global _embedding_model, _vector_store, _chunker, _text_parser, _meeting_kb_ready

    _http_client = http_client
    _chat_model = chat_model

    MEETING_QDRANT_PATH.mkdir(parents=True, exist_ok=True)
    _db = await aiosqlite.connect(str(MEETING_DB_PATH))
    await _db.execute("PRAGMA journal_mode=WAL")
    await _init_tables()

    # 会议知识库：独立 Qdrant collection，与个人知识库物理隔离
    try:
        _embedding_model = OllamaEmbeddingModel(
            credential=OllamaCredential(host=KB_OLLAMA_HOST),
            model=KB_EMBEDDING_MODEL,
            dimensions=KB_EMBEDDING_DIM,
        )
        _vector_store = QdrantStore(path=str(MEETING_QDRANT_PATH), distance="Cosine")
        _chunker = ApproxTokenChunker(chunk_size=512, overlap=64)
        _text_parser = TextParser()
        handle = KnowledgeBase(
            name="meeting-kb",
            description="office-agent 会议知识库",
            embedding_model=_embedding_model,
            vector_store=_vector_store,
            collection=MEETING_COLLECTION,
        )
        await handle.ensure_collection()
        _meeting_kb_ready = True
        logger.info(
            "会议知识库就绪: collection=%s, embedding=%s", MEETING_COLLECTION, KB_EMBEDDING_MODEL
        )
    except Exception as e:
        _meeting_kb_ready = False
        logger.warning(
            "会议知识库初始化失败，已优雅降级（会议分析/待办/提醒不受影响）: %s", e
        )

    logger.info("飞书会议模块初始化完成")


async def close_meetings() -> None:
    """关闭后台任务、向量库与元数据库。"""
    global _db, _embedding_model, _vector_store
    await stop_background()
    if _vector_store is not None:
        try:
            await _vector_store.__aexit__(None, None, None)
        except Exception:
            pass
        _vector_store = None
    _embedding_model = None
    if _db:
        await _db.close()
        _db = None


def _now() -> str:
    return str(int(time.time() * 1000))


# ── 元数据库 ───────────────────────────────────────────────────────────
async def _init_tables() -> None:
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS feishu_accounts (
            user_id       TEXT PRIMARY KEY,
            app_id        TEXT NOT NULL,
            app_secret    TEXT NOT NULL,
            open_id       TEXT NOT NULL,
            my_name       TEXT,
            enabled       INTEGER NOT NULL DEFAULT 1,
            last_sync_at  TEXT,
            last_sync_error TEXT,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        )
    """)
    # 增量迁移：为旧表补充 user_access_token 相关列（OAuth 用户授权，见下文）
    cur = await _db.execute("PRAGMA table_info(feishu_accounts)")
    cols = {row[1] for row in await cur.fetchall()}
    await cur.close()
    for col, ddl in (
        ("user_access_token", "TEXT"),
        ("refresh_token", "TEXT"),
        ("user_token_expires", "INTEGER"),   # epoch 秒，user_access_token 过期时间
        ("refresh_token_expires", "INTEGER"),  # epoch 秒，refresh_token 过期时间（约 30 天）
    ):
        if col not in cols:
            await _db.execute(f"ALTER TABLE feishu_accounts ADD COLUMN {col} {ddl}")
            logger.info("已为 feishu_accounts 表补充列: %s", col)
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS meetings (
            user_id       TEXT NOT NULL,
            meeting_id    TEXT NOT NULL,
            meeting_no    TEXT,
            topic         TEXT,
            start_time    INTEGER,
            end_time      INTEGER,
            status        INTEGER,
            host          TEXT,
            participants  TEXT,
            content_text  TEXT,
            analyze_status TEXT NOT NULL DEFAULT 'pending',  -- pending/processing/done/failed/empty
            analysis_json TEXT,
            error         TEXT,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            PRIMARY KEY (user_id, meeting_id)
        )
    """)
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS meeting_todos (
            user_id     TEXT NOT NULL,
            todo_id     TEXT NOT NULL,
            meeting_id  TEXT NOT NULL,
            content     TEXT NOT NULL,
            assignee    TEXT,
            is_mine     TEXT NOT NULL DEFAULT 'unsure',   -- yes / unsure
            reason      TEXT,
            due_hint    TEXT,
            due_time    TEXT,
            status      TEXT NOT NULL DEFAULT 'pending_confirm',
                        -- pending_confirm / confirmed / rejected / done
            reminded    INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            PRIMARY KEY (user_id, todo_id)
        )
    """)
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            user_id    TEXT NOT NULL,
            notif_id   TEXT NOT NULL,
            kind       TEXT NOT NULL,   -- meeting / todo_reminder / test
            title      TEXT NOT NULL,
            content    TEXT,
            ref_id     TEXT,
            read       INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, notif_id)
        )
    """)
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS notify_settings (
            user_id        TEXT PRIMARY KEY,
            email          TEXT,
            email_enabled  INTEGER NOT NULL DEFAULT 0,
            wechat_key     TEXT,
            wechat_enabled INTEGER NOT NULL DEFAULT 0,
            updated_at     TEXT NOT NULL
        )
    """)
    await _db.commit()


# ── 飞书账号配置 ───────────────────────────────────────────────────────
async def get_account(user_id: str) -> dict | None:
    cur = await _db.execute(
        "SELECT app_id, app_secret, open_id, my_name, enabled, last_sync_at, "
        "last_sync_error FROM feishu_accounts WHERE user_id=?",
        (user_id,),
    )
    row = await cur.fetchone()
    await cur.close()
    if not row:
        return None
    return {
        "app_id": row[0],
        "app_secret": row[1],
        "open_id": row[2],
        "my_name": row[3] or "",
        "enabled": bool(row[4]),
        "last_sync_at": int(row[5]) if row[5] else 0,
        "last_sync_error": row[6],
    }


async def save_account(
    user_id: str, app_id: str, app_secret: str, open_id: str,
    my_name: str, enabled: bool,
) -> dict:
    """保存/更新飞书账号配置，并即时校验凭证可用性。

    app_secret 留空且已有配置时沿用旧密钥（前端回显脱敏占位，编辑其他
    字段无需重新输入密钥）。
    """
    if not re.match(r"^cli_[A-Za-z0-9]+$", app_id or ""):
        raise ValueError("App ID 格式不正确（应以 cli_ 开头）")
    existing = await get_account(user_id)
    if not app_secret:
        if existing and existing["app_id"] == app_id:
            app_secret = existing["app_secret"]
        else:
            raise ValueError("App Secret 不能为空")
    if not open_id:
        raise ValueError("Open ID 不能为空")
    if not open_id.startswith("ou_"):
        raise ValueError("Open ID 格式不正确（应以 ou_ 开头）")

    # 即时连通性校验：凭证换 token 失败直接报给前端
    client = feishu.FeishuClient(_http_client, app_id, app_secret)
    try:
        await client._get_token()
    except feishu.FeishuError as e:
        raise ValueError(str(e)) from e

    now = _now()
    await _db.execute(
        "INSERT INTO feishu_accounts "
        "(user_id, app_id, app_secret, open_id, my_name, enabled, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET app_id=excluded.app_id, "
        "app_secret=excluded.app_secret, open_id=excluded.open_id, "
        "my_name=excluded.my_name, enabled=excluded.enabled, updated_at=excluded.updated_at",
        (user_id, app_id, app_secret, open_id, my_name, 1 if enabled else 0, now, now),
    )
    await _db.commit()
    return await get_account(user_id)


async def delete_account(user_id: str) -> bool:
    cur = await _db.execute(
        "DELETE FROM feishu_accounts WHERE user_id=?", (user_id,)
    )
    await _db.commit()
    deleted = cur.rowcount > 0
    await cur.close()
    return deleted


async def _enabled_accounts() -> list[tuple[str, dict]]:
    """列出全部已启用的（user_id, 账号配置），供同步循环遍历。"""
    cur = await _db.execute(
        "SELECT user_id, app_id, app_secret, open_id, my_name FROM feishu_accounts "
        "WHERE enabled=1"
    )
    rows = await cur.fetchall()
    await cur.close()
    return [
        (
            r[0],
            {"app_id": r[1], "app_secret": r[2], "open_id": r[3], "my_name": r[4] or ""},
        )
        for r in rows
    ]


# ── 用户授权（user_access_token）管理 ──────────────────────────────────
# 搜索/获取「归属于用户本人」的会议必须以用户身份调用，故同步前需完成
# 一次 OAuth 授权；refresh_token 约 30 天有效，user_access_token 约 2 小时，
# 同步前自动用 refresh_token 续期，对调用方透明。
async def save_user_token(user_id: str, token_data: dict) -> None:
    """持久化 user_access_token / refresh_token 及其过期时间。"""
    now = int(time.time())
    await _db.execute(
        "UPDATE feishu_accounts SET user_access_token=?, refresh_token=?, "
        "user_token_expires=?, refresh_token_expires=?, updated_at=? WHERE user_id=?",
        (
            token_data.get("access_token"),
            token_data.get("refresh_token"),
            now + int(token_data.get("expires_in") or 0),
            now + int(token_data.get("refresh_expires_in") or 0),
            _now(),
            user_id,
        ),
    )
    await _db.commit()


async def get_user_access_token(user_id: str) -> str | None:
    """取当前用户有效的 user_access_token；过期则用 refresh_token 自动刷新。

    返回 None 表示未授权或 refresh_token 也已失效（需重新授权）。
    """
    cur = await _db.execute(
        "SELECT user_access_token, refresh_token, user_token_expires, "
        "refresh_token_expires, app_id, app_secret FROM feishu_accounts WHERE user_id=?",
        (user_id,),
    )
    row = await cur.fetchone()
    await cur.close()
    if not row:
        return None
    access, refresh, access_exp, refresh_exp, app_id, app_secret = row
    now = int(time.time())
    if access and access_exp and now < access_exp - 60:
        return access  # 仍有效
    if not refresh or (refresh_exp and now >= refresh_exp):
        return None  # refresh_token 也失效，需重新授权
    try:
        token_data = await feishu.refresh_access_token(
            _http_client, app_id, app_secret, refresh
        )
    except feishu.FeishuError as e:
        logger.warning("[meetings] 刷新 user_access_token 失败 user=%s: %s", user_id, e)
        return None
    await save_user_token(user_id, token_data)
    return token_data.get("access_token")


async def is_authorized(user_id: str) -> bool:
    cur = await _db.execute(
        "SELECT refresh_token, refresh_token_expires FROM feishu_accounts WHERE user_id=?",
        (user_id,),
    )
    row = await cur.fetchone()
    await cur.close()
    if not row:
        return False
    refresh, refresh_exp = row
    return bool(refresh) and (not refresh_exp or int(time.time()) < int(refresh_exp or 0))


# ── 会议同步（自动接收）────────────────────────────────────────────────
async def sync_user_meetings(user_id: str) -> dict:
    """拉取当前用户最近回看窗口内的会议并入库；对已结束且拿到正文的会议
    触发子 agent 分析。返回 {new, analyzed} 统计。

    幂等：meeting_id 已存在则跳过（含 analyze_status 更新场景）。
    以 user_access_token（用户身份）调用搜索/详情接口——这是搜到「归属于
    本人」的会议的前提（tenant 身份只能看到归属于应用的会议，返回空）。
    """
    account = await get_account(user_id)
    if account is None or not account["enabled"]:
        raise ValueError("尚未配置飞书账号或账号未启用")

    user_token = await get_user_access_token(user_id)
    if not user_token:
        raise ValueError(
            "尚未完成飞书用户授权（user_access_token）。请到「飞书会议 → 接收设置」"
            "点击「授权飞书账号」完成一次授权后重试。"
        )

    client = feishu.FeishuClient(
        _http_client, account["app_id"], account["app_secret"],
        user_access_token=user_token,
    )
    end_ts = int(time.time())
    start_ts = end_ts - MEETING_SYNC_LOOKBACK_DAYS * 86400
    new_count = 0
    analyzed = 0
    error: str | None = None

    try:
        meeting_ids = await client.search_meeting_ids(
            account["open_id"], start_ts, end_ts
        )
        for mid in meeting_ids:
            try:
                meeting = await client.get_meeting(mid)
            except feishu.FeishuError as e:
                logger.warning("[meetings] 获取会议详情失败 id=%s: %s", mid, e)
                continue
            if not meeting:
                continue
            created = await _upsert_meeting(user_id, meeting)
            if created:
                new_count += 1
        # 将回看窗口内被误判为 empty 的会议重置为 pending，使其在
        # 正文拉取链路修复后（如新增录制 API 路径）能被重新分析。
        reset = await _db.execute(
            "UPDATE meetings SET analyze_status='pending', error=NULL "
            "WHERE user_id=? AND analyze_status='empty' "
            "AND start_time IS NOT NULL AND start_time >= ?",
            (user_id, start_ts),
        )
        if reset.rowcount:
            logger.info("[meetings] 重置 %d 场 empty 会议为 pending user=%s", reset.rowcount, user_id)
        await _db.commit()
        # 对「已结束 + 未分析」的会议补齐正文并分析（妙记生成有延迟，
        # 每轮同步重试，24 小时后放弃标记 empty）
        analyzed = await _analyze_pending_meetings(user_id, client, account)
        error = None
    except feishu.FeishuError as e:
        error = str(e)
        logger.warning("[meetings] 同步失败 user=%s: %s", user_id, e)
    except Exception as e:  # noqa: BLE001 同步循环兜底，避免单用户异常影响他人
        error = str(e)
        logger.exception("[meetings] 同步异常 user=%s", user_id)

    await _db.execute(
        "UPDATE feishu_accounts SET last_sync_at=?, last_sync_error=? WHERE user_id=?",
        (_now(), error, user_id),
    )
    await _db.commit()
    return {"new": new_count, "analyzed": analyzed, "error": error}


async def _upsert_meeting(user_id: str, meeting: dict) -> bool:
    """会议入库（不存在则插入，pending 等待正文与分析）。返回是否新建。"""
    meeting_id = str(meeting.get("id") or "")
    if not meeting_id:
        return False
    cur = await _db.execute(
        "SELECT 1 FROM meetings WHERE user_id=? AND meeting_id=?",
        (user_id, meeting_id),
    )
    exists = await cur.fetchone() is not None
    await cur.close()
    if exists:
        return False

    host = (meeting.get("host_user") or {})
    participants = [
        {
            "id": p.get("id"),
            "user_type": p.get("user_type"),
            "first_join_time": p.get("first_join_time"),
            "final_leave_time": p.get("final_leave_time"),
        }
        for p in (meeting.get("participants") or [])
    ]
    now = _now()
    await _db.execute(
        "INSERT INTO meetings (user_id, meeting_id, meeting_no, topic, start_time, "
        "end_time, status, host, participants, analyze_status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
        (
            user_id, meeting_id,
            str(meeting.get("meeting_no") or ""),
            str(meeting.get("topic") or "未命名会议"),
            _to_int(meeting.get("start_time")),
            _to_int(meeting.get("end_time")),
            _to_int(meeting.get("status")),
            json.dumps(host, ensure_ascii=False),
            json.dumps(participants, ensure_ascii=False),
            now, now,
        ),
    )
    await _db.commit()
    logger.info("[meetings] 新会议入库 user=%s id=%s topic=%s",
                user_id, meeting_id, meeting.get("topic"))
    return True


def _to_int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def _analyze_pending_meetings(
    user_id: str, client: feishu.FeishuClient, account: dict
) -> int:
    """拉取 pending 会议正文并派发子 agent 分析。

    会议须已结束（status=3 或 end_time 已过）；正文为空且结束未超 24h 的
    保持 pending（妙记可能仍在生成，等下一轮），超 24h 标记 empty。
    """
    cur = await _db.execute(
        "SELECT meeting_id, status, end_time FROM meetings "
        "WHERE user_id=? AND analyze_status='pending'",
        (user_id,),
    )
    rows = await cur.fetchall()
    await cur.close()

    now = time.time()
    analyzed = 0
    for meeting_id, status, end_time in rows:
        ended = status == 3 or (end_time is not None and end_time < now)
        if not ended:
            continue

        try:
            artifact_tokens = await client.get_meeting_artifacts(meeting_id)
            detail = await client.get_meeting(meeting_id)
            content = await client.collect_meeting_content(detail, artifact_tokens)
        except feishu.FeishuError as e:
            logger.warning("[meetings] 拉取会议正文失败 id=%s: %s", meeting_id, e)
            content = ""

        if not content.strip():
            # 飞书智能纪要会后约 1 分钟内生成；超过 MEETING_EMPTY_AFTER_MINUTES
            # 仍无正文（无 note_id 且 related_artifacts 为空且录制逐字稿也为空），
            # 基本意味着该会议未生成纪要（未开 AI 纪要/录制、无有效发言、额度用尽），
            # 或飞书应用未开通「获取智能纪要信息」「获取逐字稿信息」
            # 「获取会议录制信息」「导出妙记转写的文字内容」权限——
            # 此时明确标记 empty 并写入原因，否则会一直停在「待分析」让用户误判卡死。
            if end_time and now - end_time > MEETING_EMPTY_AFTER_MINUTES * 60:
                await _set_meeting_state(
                    user_id, meeting_id, "empty", None,
                    "未检测到妙记/智能纪要（会议可能未开启 AI 纪要或录制，"
                    "或飞书应用未开通「获取智能纪要信息」「获取逐字稿信息」"
                    "「获取会议录制信息」「导出妙记转写的文字内容」权限）。"
                    "在飞书中开启并确保应用权限后，重新同步可接收正文。",
                )
            else:
                logger.info(
                    "[meetings] 会议暂无正文，等待妙记生成 id=%s "
                    "(ended %ds 前，%dmin 后判定无纪要)",
                    meeting_id,
                    int(now - end_time) if end_time else -1,
                    MEETING_EMPTY_AFTER_MINUTES,
                )
            continue

        await _db.execute(
            "UPDATE meetings SET content_text=?, updated_at=? "
            "WHERE user_id=? AND meeting_id=?",
            (content[:_CONTENT_LIMIT * 2], _now(), user_id, meeting_id),
        )
        await _db.commit()
        try:
            await analyze_meeting(user_id, meeting_id)
            analyzed += 1
        except Exception as e:  # noqa: BLE001 分析失败标记 failed，不阻断其余会议
            logger.exception("[meetings] 会议分析失败 id=%s", meeting_id)
            await _set_meeting_state(user_id, meeting_id, "failed", None, str(e)[:500])
    return analyzed


async def _set_meeting_state(
    user_id: str, meeting_id: str, status: str, analysis_json: str | None,
    error: str | None,
) -> None:
    await _db.execute(
        "UPDATE meetings SET analyze_status=?, analysis_json=?, error=?, updated_at=? "
        "WHERE user_id=? AND meeting_id=?",
        (status, analysis_json, error, _now(), user_id, meeting_id),
    )
    await _db.commit()


# ── 会议分析子 agent（需求 2/3）────────────────────────────────────────
class MeetingTodoItem(BaseModel):
    """一条待办事项（子 agent 结构化输出的原子单元）。"""

    content: str = Field(description="待办事项内容，一句话、动词开头")
    assignee: str = Field(
        default="", description="待办指向的负责人（原话中的名字或称谓），未指明则为空"
    )
    is_mine: Literal["yes", "unsure", "no"] = Field(
        description="是否与当前用户有关：明确属于（点名本人/本人职责/本人承诺）为 yes；"
        "明确指派给他人或他人承诺的为 no；不确定（未指明负责人、泛指团队/大家）为 unsure"
    )
    reason: str = Field(default="", description="判断依据，一句话")
    due_hint: str = Field(
        default="", description="会议中的原始时间表述（如「周五前」），无则为空"
    )
    due_time: str = Field(
        default="",
        description="解析出的截止时间，格式 YYYY-MM-DD HH:MM；会议未提及或无法解析则为空",
    )


class MeetingAnalysis(BaseModel):
    """会议分析结果（子 agent structured_schema 输出）。"""

    summary: str = Field(description="会议摘要，200 字以内")
    key_points: list[str] = Field(default_factory=list, description="关键结论与要点")
    speakers: list[str] = Field(default_factory=list, description="发言人列表")
    todos: list[MeetingTodoItem] = Field(default_factory=list, description="会议中的全部待办")


_MEETING_ANALYST_PROMPT = """你是「会议分析师」，一个专职的会议纪要分析子智能体。主智能体把一场会议的资料委派给你，你只需要给出结构化分析结果，不与用户对话。

分析原则：
1. 摘要提炼会议目的、关键结论与决定；要点按重要性排列。
2. 待办识别：把会议中所有行动项（谁、做什么、何时完成）整理为待办列表，包括明确指派的和笼统提及的。
3. 「是否与我有关」依据用户画像与本人身份信息三分类：被点名（名字/称呼/职务）、属于本人负责的领域或项目、或本人主动承诺的事项为 yes；明确指派给他人或他人承诺的为 no；未指明负责人、泛指团队/大家的为 unsure（交给用户人工确认）。
4. due_time 尽量从原话解析为 YYYY-MM-DD HH:MM（24 小时制）；解析不出就留空，不要编造。会议未给年份时按会议日期之后的最近一个该日期。
5. 只依据会议内容，不推测会议未提及的信息。"""


async def _profile_context(user_id: str) -> str:
    """从长期记忆召回用户画像（身份/职责/项目/关系），供子 agent 判定「我的待办」。"""
    if not memory_graph.is_ready():
        return "（长期记忆未启用，暂无用户画像）"
    try:
        from memory_graph.core.retrieval.searcher import (
            format_memory_context,
            search_memory,
        )
        from memory_graph.runtime import get_clients

        _, embed_client = get_clients()
        if embed_client is None:
            return "（长期记忆未就绪，暂无用户画像）"
        hits = await search_memory(
            embed_client=embed_client,
            user_id=user_id,
            query="用户身份 职位 角色 负责的项目 工作职责 同事 团队",
            top_k=10,
        )
        text = format_memory_context(hits)
        return text or "（未召回相关用户画像）"
    except Exception as e:  # noqa: BLE001 画像缺失不阻断分析
        logger.warning("[meetings] 用户画像召回失败: %s", e)
        return "（用户画像召回失败）"


async def analyze_meeting(user_id: str, meeting_id: str) -> dict:
    """创建「会议分析师」子 agent 分析指定会议并落库。

    - 会议正文写入会议知识库（独立集合）
    - 待办入库：is_mine=yes -> confirmed；unsure -> pending_confirm（用户手动确认）
    - 生成一条应用内通知（会议已接收 + 摘要）
    返回分析结果 dict（同时供 process_meeting 工具回传主 agent）。
    """
    cur = await _db.execute(
        "SELECT topic, start_time, end_time, content_text, analyze_status "
        "FROM meetings WHERE user_id=? AND meeting_id=?",
        (user_id, meeting_id),
    )
    row = await cur.fetchone()
    await cur.close()
    if not row:
        raise ValueError("会议不存在")
    topic, start_time, end_time, content_text, analyze_status = row

    if analyze_status == "done":
        cur = await _db.execute(
            "SELECT analysis_json FROM meetings WHERE user_id=? AND meeting_id=?",
            (user_id, meeting_id),
        )
        prev = await cur.fetchone()
        await cur.close()
        return json.loads(prev[0]) if prev and prev[0] else {}

    if not (content_text or "").strip():
        raise ValueError("该会议暂无正文（妙记可能尚未生成），请稍后同步重试")

    account = await get_account(user_id) or {}
    await _set_meeting_state(user_id, meeting_id, "processing", None, None)

    # 子 agent 输入：会议元信息 + 本人身份 + 用户画像 + 会议正文
    def _fmt(ts) -> str:
        if not ts:
            return "未知"
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))

    identity = "；".join(
        x for x in [
            f"称呼：{account.get('my_name')}" if account.get("my_name") else "",
            f"飞书 Open ID：{account.get('open_id')}",
        ] if x
    ) or "（未提供）"
    profile = await _profile_context(user_id)
    prompt = (
        f"# 会议信息\n主题：{topic}\n开始：{_fmt(start_time)}\n结束：{_fmt(end_time)}\n\n"
        f"# 当前用户（待办归属判定对象）\n{identity}\n\n"
        f"# 用户画像（长期记忆）\n{profile}\n\n"
        f"# 会议正文（智能纪要与逐字稿）\n{(content_text or '')[:_CONTENT_LIMIT]}\n\n"
        "请输出结构化分析结果。"
    )

    analyst = Agent(
        name="meeting_analyst",
        system_prompt=_MEETING_ANALYST_PROMPT,
        model=_chat_model,
    )
    result = await analyst.reply(
        UserMsg("user", prompt), structured_schema=MeetingAnalysis
    )
    analysis = result.structured_output
    if not isinstance(analysis, dict):
        await _set_meeting_state(user_id, meeting_id, "failed", None, "子 agent 未返回结构化结果")
        raise ValueError("会议分析子 agent 未返回结构化结果")

    analysis["meeting_id"] = meeting_id
    await _set_meeting_state(user_id, meeting_id, "done", json.dumps(analysis, ensure_ascii=False), None)

    # 待办入库（同一会议重分析时先清旧待办，保持幂等）；
    # is_mine=no（明确属于他人）不入待办列表，仅保留在 analysis_json 中备查
    await _db.execute(
        "DELETE FROM meeting_todos WHERE user_id=? AND meeting_id=?",
        (user_id, meeting_id),
    )
    for todo in analysis.get("todos") or []:
        if todo.get("is_mine") == "no":
            continue
        due_time = _normalize_due(todo.get("due_time") or "", start_time)
        status = "confirmed" if todo.get("is_mine") == "yes" else "pending_confirm"
        now = _now()
        await _db.execute(
            "INSERT INTO meeting_todos (user_id, todo_id, meeting_id, content, assignee, "
            "is_mine, reason, due_hint, due_time, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id, uuid.uuid4().hex, meeting_id,
                str(todo.get("content") or "").strip(),
                str(todo.get("assignee") or ""),
                "yes" if todo.get("is_mine") == "yes" else "unsure",
                str(todo.get("reason") or ""),
                str(todo.get("due_hint") or ""),
                due_time, status, now, now,
            ),
        )
    await _db.commit()

    # 会议正文写入会议知识库（独立集合，与个人知识库隔离）
    if _meeting_kb_ready:
        try:
            await _index_meeting(user_id, meeting_id, topic, content_text)
        except Exception as e:  # noqa: BLE001 索引失败不影响分析结果
            logger.warning("[meetings] 会议知识库入库失败 id=%s: %s", meeting_id, e)

    # 应用内通知：会议已接收并完成分析
    todo_n = len(analysis.get("todos") or [])
    await create_notification(
        user_id, "meeting",
        f"已接收会议「{topic}」",
        f"摘要：{analysis.get('summary', '')}\n识别待办 {todo_n} 条"
        f"（确定属于我 {sum(1 for t in analysis.get('todos') or [] if t.get('is_mine') == 'yes')} 条）。",
        meeting_id,
    )
    logger.info("[meetings] 会议分析完成 user=%s id=%s todos=%d",
                user_id, meeting_id, todo_n)
    return analysis


def _normalize_due(due: str, meeting_start: int | None) -> str | None:
    """把子 agent 输出的截止时间归一化为 'YYYY-MM-DD HH:MM'。

    支持纯日期（补 09:00）；无法解析返回 None（不提醒）。
    """
    due = (due or "").strip()
    if not due:
        return None
    base_year = time.localtime(meeting_start or time.time()).tm_year
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            import datetime as _dt

            parsed = _dt.datetime.strptime(due, fmt)
            if parsed.year != base_year and "-" not in due[:5]:
                pass  # 年份缺失场景基本不出现，保持解析值
            if fmt == "%Y-%m-%d":
                parsed = parsed.replace(hour=9)
            return parsed.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return None


# ── 会议知识库（需求 5：独立集合 + 检索开关）──────────────────────────
def _kb_handle(user_id: str, owner_filter: bool) -> KnowledgeBase:
    flt = {"owner": user_id} if owner_filter else None
    return KnowledgeBase(
        name="meeting-kb",
        description="office-agent 会议知识库",
        embedding_model=_embedding_model,
        vector_store=_vector_store,
        collection=MEETING_COLLECTION,
        **({"metadata_filter": flt} if flt else {}),
    )


async def _index_meeting(
    user_id: str, meeting_id: str, topic: str, content: str
) -> int:
    """会议正文分块嵌入入库（document_metadata 带 owner/meeting_id/topic）。"""
    sections = await _text_parser.parse(file=content, filename=f"{topic}.txt")
    chunks = await _chunker.chunk(sections)
    if not chunks:
        return 0
    handle = _kb_handle(user_id, owner_filter=True)
    await handle.insert_document(
        chunks,
        document_id=meeting_id,
        document_metadata={"topic": topic, "meeting_id": meeting_id},
    )
    return len(chunks)


async def search_meeting_kb(user_id: str, query: str, top_k: int = MEETING_SEARCH_TOP_K) -> list[dict]:
    """检索当前用户的会议知识库（独立集合，绝不混入个人知识库数据）。"""
    if not _meeting_kb_ready or not query.strip():
        return []
    try:
        handle = _kb_handle(user_id, owner_filter=True)
        results = await handle.search(
            queries=[query], top_k=top_k, score_threshold=0.3
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[meetings] 会议知识库检索失败: %s", e)
        return []
    items: list[dict] = []
    for r in results:
        md = r.chunk.metadata or {}
        items.append({
            "meeting_id": r.document_id,
            "topic": md.get("topic", ""),
            "score": round(float(r.score), 4),
            "content": getattr(r.chunk.content, "text", "") or str(r.chunk.content),
        })
    return items


class SearchMeetingKnowledge(ToolBase):
    """在当前用户的会议知识库中检索相关片段（对话 agentic 检索）。

    由 /chat 的「会议检索」开关（use_meeting_kb）控制：关闭时返回提示，
    不泄露任何会议数据。当前用户经 contextvar 解析，全局注册一次。
    """

    name = "search_meeting_knowledge"
    description = (
        "在用户的会议知识库（飞书会议妙记/智能纪要正文，独立于个人文档知识库）中"
        "按语义检索相关片段。当用户询问某场会议讲了什么、会上提到某话题、"
        "会议结论/待办等内容时调用。检索结果注明来源会议主题。"
        "不涉及会议内容的普通问题无需调用。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索用的自然语言问题或关键词。"},
            "top_k": {"type": "integer", "description": "返回的最相关片段数量，默认 5。", "default": 5},
        },
        "required": ["query"],
    }
    is_external_tool = False
    is_concurrency_safe = True
    is_read_only = True

    async def check_permissions(self, tool_input: dict, context):
        from agentscope.permission import PermissionBehavior, PermissionDecision

        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="search_meeting_knowledge 仅做只读检索，无副作用。",
        )

    async def call(self, **kwargs: Any) -> ToolChunk:
        # 硬开关：用户未开启「会议检索」时不返回任何会议数据
        if not _use_meeting_kb.get():
            return ToolChunk(
                content=[TextBlock(
                    text="会议知识库检索未启用（用户已关闭「会议检索」开关）。"
                    "请勿重试本工具，直接据已知信息作答，并提示用户："
                    "如需检索会议内容，可在对话框「+」菜单开启「会议检索」开关。"
                )],
                state=ToolResultState.SUCCESS,
                is_last=True,
            )
        user_id = _current_user.get()
        query = (kwargs.get("query") or "").strip()
        if not user_id or not _meeting_kb_ready:
            return ToolChunk(
                content=[TextBlock(text="会议知识库未就绪或当前用户未知，无法检索。")],
                state=ToolResultState.SUCCESS,
                is_last=True,
            )
        if not query:
            return ToolChunk(
                content=[TextBlock(text="检索词为空。")],
                state=ToolResultState.SUCCESS,
                is_last=True,
            )
        top_k = int(kwargs.get("top_k") or MEETING_SEARCH_TOP_K)
        items = await search_meeting_kb(user_id, query, top_k)
        if not items:
            return ToolChunk(
                content=[TextBlock(text="未检索到相关会议内容。")],
                state=ToolResultState.SUCCESS,
                is_last=True,
            )
        parts = [
            f"[{i}] 来源会议：{it['topic']}（相似度 {it['score']}）\n{it['content']}"
            for i, it in enumerate(items, 1)
        ]
        return ToolChunk(
            content=[TextBlock(text="\n\n".join(parts))],
            state=ToolResultState.SUCCESS,
            is_last=True,
        )


# ── 主 agent 委派工具（需求 2：主 agent 负责委派与收集结果）──────────
class ProcessMeetingTool(ToolBase):
    """主 agent 的委派工具：把一场会议交给「会议分析师」子 agent 处理。"""

    name = "process_meeting"
    description = (
        "把用户的飞书会议委派给「会议分析师」子智能体处理：生成会议摘要、关键要点"
        "与待办事项（并区分哪些属于该用户）。meeting_id 省略时自动处理最近一场"
        "尚未分析的会议。用户询问「处理/分析我的会议」「帮我看看最近的会」"
        "「总结会议并提取待办」等时调用。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "meeting_id": {
                "type": "string",
                "description": "要处理的会议 ID（来自 list_my_meetings），省略则处理最近一场未分析会议。",
            },
        },
    }
    is_external_tool = False
    is_concurrency_safe = False
    is_read_only = False

    async def check_permissions(self, tool_input: dict, context):
        from agentscope.permission import PermissionBehavior, PermissionDecision

        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="process_meeting 委派子 agent 分析当前用户自己的会议。",
        )

    async def call(self, **kwargs: Any) -> ToolChunk:
        user_id = _current_user.get()
        if not user_id:
            return ToolChunk(
                content=[TextBlock(text="当前用户未知，无法处理会议。")],
                state=ToolResultState.SUCCESS, is_last=True,
            )
        meeting_id = (kwargs.get("meeting_id") or "").strip()
        if not meeting_id:
            cur = await _db.execute(
                "SELECT meeting_id FROM meetings WHERE user_id=? "
                "AND analyze_status='pending' ORDER BY start_time DESC LIMIT 1",
                (user_id,),
            )
            row = await cur.fetchone()
            await cur.close()
            if not row:
                cur = await _db.execute(
                    "SELECT meeting_id FROM meetings WHERE user_id=? "
                    "ORDER BY start_time DESC LIMIT 1",
                    (user_id,),
                )
                row = await cur.fetchone()
                await cur.close()
            if not row:
                return ToolChunk(
                    content=[TextBlock(
                        text="用户还没有已接收的会议。请提示用户到「飞书会议」页配置飞书账号并同步会议。"
                    )],
                    state=ToolResultState.SUCCESS, is_last=True,
                )
            meeting_id = row[0]
        try:
            analysis = await analyze_meeting(user_id, meeting_id)
        except Exception as e:  # noqa: BLE001
            return ToolChunk(
                content=[TextBlock(text=f"会议处理失败：{e}")],
                state=ToolResultState.ERROR, is_last=True,
            )
        # 收集子 agent 结果，整理为主 agent 可直接汇报的文本
        todos = analysis.get("todos") or []
        mine = [t for t in todos if t.get("is_mine") == "yes"]
        unsure = [t for t in todos if t.get("is_mine") != "yes"]
        report = (
            f"摘要：{analysis.get('summary', '')}\n"
            f"关键要点：{'；'.join(analysis.get('key_points') or [])}\n"
            f"属于用户的待办 {len(mine)} 条：\n"
            + "\n".join(
                f"- {t.get('content')}（截止：{t.get('due_time') or t.get('due_hint') or '未明确'}）"
                for t in mine
            )
            + f"\n待用户确认的待办 {len(unsure)} 条：\n"
            + "\n".join(f"- {t.get('content')}" for t in unsure)
        )
        return ToolChunk(
            content=[TextBlock(text=report)],
            state=ToolResultState.SUCCESS, is_last=True,
        )


class ListMyMeetingsTool(ToolBase):
    """主 agent 的查询工具：列出用户已接收的飞书会议。"""

    name = "list_my_meetings"
    description = (
        "列出用户已自动接收的飞书会议（主题、时间、分析状态）。用户问"
        "「我最近有哪些会议」「上次那个会总结了吗」等时调用；需要处理具体会议时"
        "先用本工具拿 meeting_id 再调用 process_meeting。"
    )
    input_schema = {"type": "object", "properties": {}}
    is_external_tool = False
    is_concurrency_safe = True
    is_read_only = True

    async def check_permissions(self, tool_input: dict, context):
        from agentscope.permission import PermissionBehavior, PermissionDecision

        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="list_my_meetings 仅读取当前用户自己的会议列表。",
        )

    async def call(self, **kwargs: Any) -> ToolChunk:
        user_id = _current_user.get()
        if not user_id:
            return ToolChunk(
                content=[TextBlock(text="当前用户未知。")],
                state=ToolResultState.SUCCESS, is_last=True,
            )
        meetings = await list_meetings(user_id, limit=10)
        if not meetings:
            return ToolChunk(
                content=[TextBlock(
                    text="用户还没有已接收的会议。请提示用户到「飞书会议」页配置飞书账号后自动接收。"
                )],
                state=ToolResultState.SUCCESS, is_last=True,
            )
        def _st(s: str) -> str:
            return {
                "pending": "待分析", "processing": "分析中", "done": "已分析",
                "failed": "分析失败", "empty": "无正文",
            }.get(s, s)
        lines = [
            f"- {m['topic']}（{m['start_time_text']}，{_st(m['analyze_status'])}，meeting_id: {m['meeting_id']}）"
            for m in meetings
        ]
        return ToolChunk(
            content=[TextBlock(text="\n".join(lines))],
            state=ToolResultState.SUCCESS, is_last=True,
        )


# ── 会议 / 待办查询 ────────────────────────────────────────────────────
async def list_meetings(user_id: str, limit: int = 50) -> list[dict]:
    cur = await _db.execute(
        "SELECT m.meeting_id, m.topic, m.start_time, m.end_time, m.analyze_status, "
        "(SELECT COUNT(*) FROM meeting_todos t WHERE t.user_id=m.user_id "
        " AND t.meeting_id=m.meeting_id AND t.status IN ('confirmed','pending_confirm')) AS todo_n "
        "FROM meetings m WHERE m.user_id=? ORDER BY COALESCE(m.start_time, 0) DESC LIMIT ?",
        (user_id, limit),
    )
    rows = await cur.fetchall()
    await cur.close()
    return [
        {
            "meeting_id": r[0],
            "topic": r[1],
            "start_time": r[2] or 0,
            "start_time_text": (
                time.strftime("%Y-%m-%d %H:%M", time.localtime(r[2])) if r[2] else "未知"
            ),
            "end_time": r[3] or 0,
            "analyze_status": r[4],
            "todo_count": r[5],
        }
        for r in rows
    ]


async def get_meeting_detail(user_id: str, meeting_id: str) -> dict | None:
    cur = await _db.execute(
        "SELECT meeting_id, meeting_no, topic, start_time, end_time, status, host, "
        "participants, content_text, analyze_status, analysis_json, error "
        "FROM meetings WHERE user_id=? AND meeting_id=?",
        (user_id, meeting_id),
    )
    r = await cur.fetchone()
    await cur.close()
    if not r:
        return None
    try:
        analysis = json.loads(r[10]) if r[10] else None
    except json.JSONDecodeError:
        analysis = None
    try:
        host = json.loads(r[6]) if r[6] else None
    except json.JSONDecodeError:
        host = None
    return {
        "meeting_id": r[0], "meeting_no": r[1], "topic": r[2],
        "start_time": r[3], "end_time": r[4], "status": r[5],
        "host": host, "content_text": r[8] or "",
        "analyze_status": r[9], "analysis": analysis, "error": r[11],
    }


async def list_todos(user_id: str, status: str | None = None) -> list[dict]:
    sql = (
        "SELECT t.todo_id, t.meeting_id, t.content, t.assignee, t.is_mine, t.reason, "
        "t.due_hint, t.due_time, t.status, t.reminded, m.topic "
        "FROM meeting_todos t LEFT JOIN meetings m "
        "ON m.user_id=t.user_id AND m.meeting_id=t.meeting_id "
        "WHERE t.user_id=?"
    )
    params: list = [user_id]
    if status:
        sql += " AND t.status=?"
        params.append(status)
    sql += " ORDER BY COALESCE(t.due_time, '') ASC, t.created_at DESC"
    cur = await _db.execute(sql, params)
    rows = await cur.fetchall()
    await cur.close()
    return [
        {
            "todo_id": r[0], "meeting_id": r[1], "content": r[2], "assignee": r[3],
            "is_mine": r[4], "reason": r[5], "due_hint": r[6], "due_time": r[7],
            "status": r[8], "reminded": bool(r[9]), "meeting_topic": r[10] or "",
        }
        for r in rows
    ]


async def update_todo(user_id: str, todo_id: str, action: str) -> dict | None:
    """待办状态流转：confirm / reject / done / reopen。"""
    status_map = {
        "confirm": "confirmed", "reject": "rejected",
        "done": "done", "reopen": "confirmed",
    }
    if action not in status_map:
        raise ValueError(f"不支持的操作: {action}")
    cur = await _db.execute(
        "UPDATE meeting_todos SET status=?, updated_at=? "
        "WHERE user_id=? AND todo_id=?",
        (status_map[action], _now(), user_id, todo_id),
    )
    await _db.commit()
    updated = cur.rowcount > 0
    await cur.close()
    if not updated:
        return None
    cur = await _db.execute(
        "SELECT todo_id, meeting_id, content, status FROM meeting_todos "
        "WHERE user_id=? AND todo_id=?",
        (user_id, todo_id),
    )
    r = await cur.fetchone()
    await cur.close()
    return {"todo_id": r[0], "meeting_id": r[1], "content": r[2], "status": r[3]}


# ── 通知（需求 4）──────────────────────────────────────────────────────
async def create_notification(
    user_id: str, kind: str, title: str, content: str, ref_id: str | None = None,
    *, dispatch_external: bool = False,
) -> str:
    """写入应用内通知；dispatch_external=True 时按用户设置外发邮件/微信。"""
    notif_id = uuid.uuid4().hex
    await _db.execute(
        "INSERT INTO notifications (user_id, notif_id, kind, title, content, ref_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, notif_id, kind, title, content, ref_id, _now()),
    )
    await _db.commit()
    if dispatch_external:
        await _dispatch_external(user_id, title, content)
    return notif_id


async def list_notifications(user_id: str, unread_only: bool = False) -> list[dict]:
    sql = (
        "SELECT notif_id, kind, title, content, ref_id, read, created_at "
        "FROM notifications WHERE user_id=?"
    )
    if unread_only:
        sql += " AND read=0"
    sql += " ORDER BY created_at DESC LIMIT 50"
    cur = await _db.execute(sql, (user_id,))
    rows = await cur.fetchall()
    await cur.close()
    return [
        {
            "notif_id": r[0], "kind": r[1], "title": r[2], "content": r[3] or "",
            "ref_id": r[4], "read": bool(r[5]),
            "created_at": int(r[6]) if r[6] else 0,
        }
        for r in rows
    ]


async def mark_notifications_read(user_id: str, notif_ids: list[str] | None = None) -> int:
    """标记通知已读；notif_ids 为空时标记全部。"""
    if notif_ids:
        placeholders = ",".join("?" for _ in notif_ids)
        cur = await _db.execute(
            f"UPDATE notifications SET read=1 WHERE user_id=? "
            f"AND notif_id IN ({placeholders})",
            [user_id, *notif_ids],
        )
    else:
        cur = await _db.execute(
            "UPDATE notifications SET read=1 WHERE user_id=?", (user_id,)
        )
    await _db.commit()
    n = cur.rowcount
    await cur.close()
    return n


# ── 通知外发渠道（邮件 / 微信，可选启用）──────────────────────────────
async def get_notify_settings(user_id: str) -> dict:
    cur = await _db.execute(
        "SELECT email, email_enabled, wechat_key, wechat_enabled FROM notify_settings "
        "WHERE user_id=?",
        (user_id,),
    )
    r = await cur.fetchone()
    await cur.close()
    if not r:
        return {"email": "", "email_enabled": False, "wechat_key": "", "wechat_enabled": False}
    return {
        "email": r[0] or "",
        "email_enabled": bool(r[1]),
        "wechat_key": r[2] or "",
        "wechat_enabled": bool(r[3]),
    }


async def save_notify_settings(
    user_id: str, email: str, email_enabled: bool, wechat_key: str, wechat_enabled: bool,
) -> dict:
    if email_enabled and not email.strip():
        raise ValueError("启用邮件通知需填写收件邮箱")
    if wechat_enabled and not wechat_key.strip():
        raise ValueError("启用微信通知需填写 Server酱 SendKey")
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ValueError("邮箱格式不正确")
    await _db.execute(
        "INSERT INTO notify_settings (user_id, email, email_enabled, wechat_key, wechat_enabled, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET email=excluded.email, "
        "email_enabled=excluded.email_enabled, wechat_key=excluded.wechat_key, "
        "wechat_enabled=excluded.wechat_enabled, updated_at=excluded.updated_at",
        (user_id, email.strip(), 1 if email_enabled else 0, wechat_key.strip(),
         1 if wechat_enabled else 0, _now()),
    )
    await _db.commit()
    return await get_notify_settings(user_id)


def _send_email_sync(to: str, title: str, content: str) -> None:
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = title
    msg["From"] = SMTP_FROM
    msg["To"] = to
    if SMTP_USE_SSL:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15)
    else:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15)
    try:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM, [to], msg.as_string())
    finally:
        server.quit()


async def _dispatch_external(user_id: str, title: str, content: str) -> dict:
    """按用户通知设置外发（邮件 + 微信 Server酱）；单渠道失败不影响另一渠道。"""
    settings = await get_notify_settings(user_id)
    results: dict = {"email": None, "wechat": None}
    if settings["email_enabled"] and settings["email"]:
        if not SMTP_HOST:
            results["email"] = "管理员未配置 SMTP（.env 中 SMTP_HOST 等），邮件未发送"
        else:
            try:
                await asyncio.to_thread(
                    _send_email_sync, settings["email"], title, content
                )
                results["email"] = "ok"
            except Exception as e:  # noqa: BLE001
                logger.warning("[meetings] 邮件通知失败: %s", e)
                results["email"] = f"发送失败: {e}"
    if settings["wechat_enabled"] and settings["wechat_key"]:
        try:
            resp = await _http_client.post(
                f"{WECHAT_SEND_API}/{settings['wechat_key']}.send",
                data={"title": title, "desp": content},
            )
            ok = resp.status_code == 200 and resp.json().get("code") == 0
            results["wechat"] = "ok" if ok else f"发送失败: {resp.text[:200]}"
        except Exception as e:  # noqa: BLE001
            logger.warning("[meetings] 微信通知失败: %s", e)
            results["wechat"] = f"发送失败: {e}"
    return results


# ── 定时提醒（需求 4：截止前提前提醒）─────────────────────────────────
async def _reminder_once() -> int:
    """扫描已确认待办，对到达提醒时间的创建应用内 + 外部通知。"""
    import datetime as _dt

    now = _dt.datetime.now()
    now_ms = int(now.timestamp() * 1000)
    cur = await _db.execute(
        "SELECT t.user_id, t.todo_id, t.meeting_id, t.content, t.due_time, m.topic "
        "FROM meeting_todos t LEFT JOIN meetings m "
        "ON m.user_id=t.user_id AND m.meeting_id=t.meeting_id "
        "WHERE t.status='confirmed' AND t.reminded=0 AND t.due_time IS NOT NULL "
        "AND t.due_time != ''"
    )
    rows = await cur.fetchall()
    await cur.close()
    sent = 0
    for user_id, todo_id, meeting_id, content, due_time, topic in rows:
        try:
            due = _dt.datetime.strptime(due_time, "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        lead = _dt.timedelta(minutes=MEETING_REMIND_LEAD_MINUTES)
        if now < due - lead or now > due + _dt.timedelta(hours=12):
            continue  # 未到提醒时间；或早已过期超过 12 小时不再打扰
        await create_notification(
            user_id, "todo_reminder",
            f"待办提醒：{content[:50]}",
            f"来自会议「{topic or ''}」，截止时间 {due_time}。",
            meeting_id,
            dispatch_external=True,
        )
        await _db.execute(
            "UPDATE meeting_todos SET reminded=1 WHERE user_id=? AND todo_id=?",
            (user_id, todo_id),
        )
        await _db.commit()
        sent += 1
    if sent:
        logger.info("[meetings] 待办提醒发送 %d 条（now=%s）", sent, now_ms)
    return sent


async def _reminder_loop() -> None:
    while True:
        try:
            await _reminder_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("[meetings] 提醒循环异常：{e}".format(e=e))
        await asyncio.sleep(MEETING_REMINDER_INTERVAL)


# ── 同步循环（需求 1：自动接收）────────────────────────────────────────
async def _sync_loop() -> None:
    while True:
        try:
            for user_id, _account in await _enabled_accounts():
                try:
                    stats = await sync_user_meetings(user_id)
                    if stats["new"] or stats["error"]:
                        logger.info(
                            "[meetings] 定时同步 user=%s new=%s analyzed=%s err=%s",
                            user_id, stats["new"], stats["analyzed"], stats["error"],
                        )
                except Exception as e:  # noqa: BLE001 单用户失败不影响其他用户
                    logger.warning("[meetings] 定时同步失败 user=%s: %s", user_id, e)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[meetings] 同步循环异常：{e}")
        await asyncio.sleep(MEETING_SYNC_INTERVAL)


async def start_background() -> None:
    """启动同步与提醒后台任务（lifespan 调用）。"""
    global _sync_task, _reminder_task
    if MEETING_SYNC_INTERVAL > 0:
        _sync_task = asyncio.create_task(_sync_loop())
    if MEETING_REMINDER_INTERVAL > 0:
        _reminder_task = asyncio.create_task(_reminder_loop())
    logger.info(
        "[meetings] 后台任务启动: sync=%ss, reminder=%ss",
        MEETING_SYNC_INTERVAL, MEETING_REMINDER_INTERVAL,
    )


async def stop_background() -> None:
    global _sync_task, _reminder_task
    for task in (_sync_task, _reminder_task):
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    _sync_task = None
    _reminder_task = None


# ── REST API（经网关 /agent/meetings/* 暴露）──────────────────────────
router = APIRouter(prefix="/meetings", tags=["meetings"])

_security = HTTPBearer()
_injected_auth = None


def set_auth_dependency(fn) -> None:
    """由 main.py 注入鉴权依赖（可选）；不注入则惰性复用 main.verify_token。"""
    global _injected_auth
    _injected_auth = fn


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> str:
    if _injected_auth is not None:
        return await _injected_auth(credentials)
    from main import verify_token  # 惰性导入，避免循环依赖
    return await verify_token(credentials)


class AccountRequest(BaseModel):
    app_id: str
    app_secret: str
    open_id: str
    my_name: str = ""
    enabled: bool = True


class OAuthExchangeRequest(BaseModel):
    code: str


class NotifySettingsRequest(BaseModel):
    email: str = ""
    email_enabled: bool = False
    wechat_key: str = ""
    wechat_enabled: bool = False


class TodoActionRequest(BaseModel):
    action: str  # confirm / reject / done / reopen


class NotificationsReadRequest(BaseModel):
    ids: list[str] | None = None


@router.get("/account", summary="获取飞书账号配置（密钥脱敏）")
async def api_get_account(user_id: str = Depends(get_current_user)):
    account = await get_account(user_id)
    if account is None:
        return {"configured": False, "authorized": False, "redirect_uri": FEISHU_OAUTH_REDIRECT_URI}
    account["app_secret"] = "•••••" if account["app_secret"] else ""
    return {
        "configured": True,
        "authorized": await is_authorized(user_id),
        "redirect_uri": FEISHU_OAUTH_REDIRECT_URI,
        "account": account,
    }


@router.put("/account", summary="保存飞书账号配置（含连通性校验）")
async def api_save_account(req: AccountRequest, user_id: str = Depends(get_current_user)):
    try:
        account = await save_account(
            user_id, req.app_id.strip(), req.app_secret.strip(),
            req.open_id.strip(), req.my_name.strip(), req.enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    account["app_secret"] = "•••••"
    return {"configured": True, "account": account}


@router.delete("/account", summary="删除飞书账号配置")
async def api_delete_account(user_id: str = Depends(get_current_user)):
    deleted = await delete_account(user_id)
    return {"deleted": deleted}


# ── 用户授权（OAuth user_access_token）───────────────────────────────
# 搜索/获取「归属于本人」的会议必须以用户身份调用。授权页 → 回调换 token
# 自动完成；也提供手动提交 code 的兜底（飞书拒绝 localhost 回调时用）。
@router.get("/oauth/url", summary="获取飞书用户授权页链接")
async def api_oauth_url(user_id: str = Depends(get_current_user)):
    account = await get_account(user_id)
    if account is None:
        raise HTTPException(status_code=400, detail="请先保存飞书账号配置后再授权")
    url = feishu.build_auth_url(
        account["app_id"], FEISHU_OAUTH_REDIRECT_URI, state=user_id
    )
    return {"url": url, "redirect_uri": FEISHU_OAUTH_REDIRECT_URI}


@router.get("/oauth/callback", summary="飞书授权回调（浏览器重定向，无鉴权）")
async def api_oauth_callback(code: str, state: str):
    """飞书授权后浏览器重定向至此。state=授权时注入的 user_id，据此换 token
    并落库。无鉴权依赖（浏览器重定向不带 Bearer），安全性来自 state 绑定用户。"""
    user_id = state
    account = await get_account(user_id)
    if account is None:
        return HTMLResponse("<h3>授权失败</h3><p>账号配置不存在。</p>", status_code=400)
    try:
        token_data = await feishu.exchange_code(
            _http_client, account["app_id"], account["app_secret"],
            code, FEISHU_OAUTH_REDIRECT_URI,
        )
    except feishu.FeishuError as e:
        return HTMLResponse(f"<h3>授权失败</h3><p>{e}</p>", status_code=400)
    await save_user_token(user_id, token_data)
    return HTMLResponse(
        "<h3>✅ 飞书授权成功</h3>"
        "<p>已获取用户访问凭证，可关闭此页，回到 office-agent 点「立即同步」。</p>"
    )


@router.post("/oauth/exchange", summary="手动提交授权码换 token（回调不可达时兜底）")
async def api_oauth_exchange(req: OAuthExchangeRequest, user_id: str = Depends(get_current_user)):
    account = await get_account(user_id)
    if account is None:
        raise HTTPException(status_code=400, detail="请先保存飞书账号配置")
    try:
        token_data = await feishu.exchange_code(
            _http_client, account["app_id"], account["app_secret"],
            req.code, FEISHU_OAUTH_REDIRECT_URI,
        )
    except feishu.FeishuError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await save_user_token(user_id, token_data)
    return {"authorized": True}


@router.get("/oauth/status", summary="用户授权状态")
async def api_oauth_status(user_id: str = Depends(get_current_user)):
    return {"authorized": await is_authorized(user_id)}


@router.post("/sync", summary="立即同步飞书会议（自动接收）")
async def api_sync(user_id: str = Depends(get_current_user)):
    try:
        stats = await sync_user_meetings(user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if stats["error"]:
        raise HTTPException(status_code=502, detail=f"同步失败: {stats['error']}")
    return stats


@router.get("", summary="已接收的会议列表")
async def api_list_meetings(user_id: str = Depends(get_current_user)):
    return {"meetings": await list_meetings(user_id)}


@router.get("/todos", summary="会议待办列表")
async def api_list_todos(
    status: str | None = None, user_id: str = Depends(get_current_user),
):
    if status and status not in ("pending_confirm", "confirmed", "rejected", "done"):
        raise HTTPException(status_code=400, detail="无效的待办状态")
    return {"todos": await list_todos(user_id, status)}


@router.patch("/todos/{todo_id}", summary="待办确认/拒绝/完成/重开")
async def api_update_todo(
    todo_id: str, req: TodoActionRequest, user_id: str = Depends(get_current_user),
):
    try:
        todo = await update_todo(user_id, todo_id, req.action)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if todo is None:
        raise HTTPException(status_code=404, detail="待办不存在")
    return todo


@router.get("/notifications", summary="应用内通知列表")
async def api_list_notifications(
    unread: bool = False, user_id: str = Depends(get_current_user),
):
    return {"notifications": await list_notifications(user_id, unread)}


@router.post("/notifications/read", summary="标记通知已读")
async def api_mark_read(
    req: NotificationsReadRequest, user_id: str = Depends(get_current_user),
):
    n = await mark_notifications_read(user_id, req.ids)
    return {"marked": n}


@router.get("/notify-settings", summary="获取通知渠道设置")
async def api_get_notify_settings(user_id: str = Depends(get_current_user)):
    settings = await get_notify_settings(user_id)
    settings["smtp_ready"] = bool(SMTP_HOST)
    return settings


@router.put("/notify-settings", summary="保存通知渠道设置")
async def api_save_notify_settings(
    req: NotifySettingsRequest, user_id: str = Depends(get_current_user),
):
    try:
        return await save_notify_settings(
            user_id, req.email, req.email_enabled,
            req.wechat_key, req.wechat_enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/notify-test", summary="发送测试通知（校验外发渠道）")
async def api_notify_test(user_id: str = Depends(get_current_user)):
    notif_id = await create_notification(
        user_id, "test", "测试通知", "这是一条来自 AI 办公搭子的测试通知。",
        dispatch_external=True,
    )
    return {"notif_id": notif_id}


@router.get("/kb/search", summary="检索会议知识库（独立集合）")
async def api_kb_search(
    query: str, top_k: int | None = None, user_id: str = Depends(get_current_user),
):
    if not is_kb_ready():
        raise HTTPException(status_code=503, detail="会议知识库未就绪（需本地 Ollama 嵌入模型）")
    if not query.strip():
        raise HTTPException(status_code=400, detail="检索词不能为空")
    items = await search_meeting_kb(user_id, query, top_k or MEETING_SEARCH_TOP_K)
    return {"query": query, "items": items}


@router.get("/{meeting_id}", summary="会议详情（正文与分析结果）")
async def api_meeting_detail(
    meeting_id: str, user_id: str = Depends(get_current_user),
):
    detail = await get_meeting_detail(user_id, meeting_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    detail["todos"] = await list_todos(user_id)
    detail["todos"] = [t for t in detail["todos"] if t["meeting_id"] == meeting_id]
    return detail

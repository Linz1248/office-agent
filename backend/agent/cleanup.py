"""agent 定时清理：回收上传图片、过期会话与工作区残留，避免长期占用存储。

清理对象：
- uploads/                用户上传图片副本（file_path，供 read_image / 以图搜图）
- sessions.db             过期会话行（按 updated_at，epoch 毫秒文本）
- workspace/sessions/<id>/ 仅清理「孤儿」（session_id 已不在 sessions.db 的目录）；
                           不按 mtime 删，避免破坏仍可恢复的活跃会话的卸载工具结果
- workspace/<task>/        非会话的任务草稿目录（如 gen_excel.py 等智能体自建产物），按 mtime 清理
- memory/<user>/          长期记忆 —— 永不清理（与 workspace 同级，本模块不访问它）

对 AI 问答上下文的影响（关键设计）：
1. 会话先于工作区清理：run_once 先 _prune_sessions（删过期会话行），再 _reap_workspace
   （此时被删会话的 workspace/sessions/<id>/ 已成孤儿，可安全回收）。
2. 活跃会话（updated_at 在保留期内）的 workspace/sessions/<id>/ 受保护，不删——
   其被截断卸载的工具结果仍可按需回查。
3. 用户在过期会话中引用的文件（extract_filename 在 document_extract 服务侧）若已被
   那侧清理，工具会返回 "文件不存在或已过期（可能已被定时清理），请重新上传后再试"
   （见 office_mcp._handle_error），由 agent 转告用户重新上传，不崩溃、不盲目重试。

保留期均可经环境变量覆盖（见 config.py）；置 0 关闭对应清理。
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sqlite3
import time
from pathlib import Path

import config

logger = logging.getLogger("cleanup")

_FILE_DAYS = config.CLEANUP_FILE_DAYS
_SESSION_DAYS = config.CLEANUP_SESSION_DAYS
_INTERVAL = config.CLEANUP_INTERVAL_SECONDS


# ── 纯函数（便于单测，显式接收路径/参数） ──────────────────────────────


def _remove_empty_dirs(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        p = Path(dirpath)
        if p == root:
            continue
        if not filenames and not dirnames:
            try:
                p.rmdir()
            except OSError:
                pass


def sweep_files(root: Path, retention_days: float) -> int:
    """删除 root 下 mtime 超过保留期的文件，并清理空目录。返回删除文件数。"""
    if retention_days <= 0 or not root.exists():
        return 0
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                pass
    _remove_empty_dirs(root)
    return removed


def prune_sessions(db_path: Path, retention_days: float) -> int:
    """删除 sessions.db 中 updated_at 早于保留期的会话行。

    updated_at 为写入时的 epoch 毫秒文本（str(int(time.time()*1000))），
    故用 CAST(... AS INTEGER) 与 cutoff 毫秒比较。
    """
    if retention_days <= 0 or not Path(db_path).exists():
        return 0
    cutoff_ms = str(int((time.time() - retention_days * 86400) * 1000))
    removed = 0
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA busy_timeout=5000")
        cur = conn.execute(
            "DELETE FROM sessions WHERE CAST(updated_at AS INTEGER) < ?",
            (cutoff_ms,),
        )
        removed = cur.rowcount
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"清理 sessions.db 失败：{e}")
    return removed


def _active_session_ids(db_path: Path) -> set[str]:
    """读取当前仍在 sessions.db 中的 session_id 集合（供工作区孤儿判定）。"""
    ids: set[str] = set()
    if not Path(db_path).exists():
        return ids
    try:
        conn = sqlite3.connect(str(db_path))
        for (sid,) in conn.execute("SELECT session_id FROM sessions"):
            if sid:
                ids.add(str(sid))
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"读取 sessions 失败：{e}")
    return ids


def reap_workspace(
    workspace_dir: Path,
    retention_days: float,
    active_ids: set[str],
) -> int:
    """清理 workspace：

    - workspace/sessions/<id>/：仅当 <id> 不在 active_ids（即会话已从 DB 删除，成孤儿）
      才整目录回收；否则保留（活跃会话的卸载工具结果需可按需回查）。
    - workspace/<name>/（非 sessions、非 memory）：按 mtime 超过保留期则回收（任务草稿）。
    - 绝不触碰 memory/（与 workspace 同级，本函数不访问）。
    返回回收的目录数。
    """
    ws = workspace_dir
    if not ws.exists():
        return 0
    cutoff = time.time() - retention_days * 86400
    removed = 0

    sessions_root = ws / "sessions"
    if sessions_root.exists():
        for sub in sessions_root.iterdir():
            if not sub.is_dir():
                continue
            if sub.name not in active_ids:  # 孤儿会话 → 回收
                shutil.rmtree(sub, ignore_errors=True)
                removed += 1

    # 非会话、非 memory 的任务草稿目录，按 mtime 清理
    for sub in ws.iterdir():
        if not sub.is_dir() or sub.name in ("sessions", "memory"):
            continue
        try:
            if sub.stat().st_mtime < cutoff:
                shutil.rmtree(sub, ignore_errors=True)
                removed += 1
        except OSError:
            pass
    return removed


# ── 编排 + 调度 ─────────────────────────────────────────────────────


def run_once() -> dict:
    """执行一次完整清理。注意顺序：先删过期会话行，再回收工作区——
    使本轮被删会话的 workspace/sessions/<id>/ 立即成为孤儿被一并回收。"""
    sessions_removed = prune_sessions(config.SESSION_DB_PATH, _SESSION_DAYS)
    result = {
        "sessions_rows": sessions_removed,
        "uploads": sweep_files(config.UPLOAD_DIR, _FILE_DAYS),
        "workspace": reap_workspace(
            config.WORKSPACE_DIR,
            _FILE_DAYS,
            _active_session_ids(config.SESSION_DB_PATH),
        ),
    }
    logger.info(f"[cleanup] agent: {result}")
    return result


async def cleanup_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(run_once)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[cleanup] 循环异常：{e}")
        await asyncio.sleep(_INTERVAL)


async def start() -> asyncio.Task | None:
    if _INTERVAL <= 0:
        logger.info("[cleanup] CLEANUP_INTERVAL_SECONDS<=0，已禁用定时清理")
        return None
    return asyncio.create_task(cleanup_loop())


async def stop(task: asyncio.Task | None) -> None:
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

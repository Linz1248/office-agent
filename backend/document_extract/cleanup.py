"""document_extract 定时清理：回收上传/输出/缓存与 LibreOffice 临时残留，避免长期占用存储。

策略：仅按 mtime / created_at 删除超过保留期的文件与记录。活跃会话（分钟级）远
短于文件保留期（天级），故不会被误删。保留期均可经环境变量覆盖（见 config.py）；
置 0 关闭对应清理。

清理对象：
- uploads/         用户上传文档（PDF/Word/Excel/图片，extract_filename 落盘处）
- output/          生成的 Excel（/download 下载后留存的副本）
- cache.db         ocr_cache / llm_cache 行（按 created_at；INSERT OR REPLACE 时刷新）
- /tmp/lo-conv-*、/tmp/lo-profile-*  LibreOffice headless 转换残留（从不被删除的小泄漏）
- backend/logs/*.log  单文件超上限则保留尾部

对 AI 问答上下文的影响：清理掉用户引用过的文件后，相关工具会返回
"文件不存在或已过期（可能已被定时清理），请重新上传后再试"（见 main.py 各端点 +
office_mcp._handle_error），由 agent 转告用户重新上传，不会崩溃或盲目重试。
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
_CACHE_DAYS = config.CLEANUP_CACHE_DAYS
_INTERVAL = config.CLEANUP_INTERVAL_SECONDS
_LOGS_MAX_MB = config.CLEANUP_LOGS_MAX_MB


# ── 纯函数（便于单测，均显式接收路径/参数，不直接依赖全局配置） ──────────


def _remove_empty_dirs(root: Path) -> None:
    """自底向上删除 root 下的空目录（不动 root 本身）。"""
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


def sweep_tmp_lo(retention_days: float, tmp_root: Path = Path("/tmp")) -> int:
    """清理 LibreOffice headless 残留（lo-conv-* / lo-profile-*，从不被主动删除）。"""
    if retention_days <= 0:
        return 0
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for pat in ("lo-conv-*", "lo-profile-*"):
        for p in tmp_root.glob(pat):
            try:
                if p.stat().st_mtime < cutoff:
                    if p.is_dir():
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        p.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                pass
    return removed


def prune_cache(db_path: Path, retention_days: float) -> int:
    """删除 cache.db 中 created_at 早于保留期的 ocr_cache / llm_cache 行，并 VACUUM 回收空间。

    created_at 为 SQLite CURRENT_TIMESTAMP（UTC ISO 文本 'YYYY-MM-DD HH:MM:SS'），
    INSERT OR REPLACE 时刷新为最近写入时间，故按其清理即“长期未再命中的缓存”。
    """
    if retention_days <= 0 or not Path(db_path).exists():
        return 0
    cutoff_iso = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - retention_days * 86400))
    removed = 0
    try:
        # 复用主服务的 NFS 安全连接配方（nolock=1 + busy_timeout）
        conn = sqlite3.connect(f"file:{db_path}?nolock=1", uri=True)
        conn.execute("PRAGMA busy_timeout=5000")
        for tbl in ("ocr_cache", "llm_cache"):
            cur = conn.execute(f"DELETE FROM {tbl} WHERE created_at < ?", (cutoff_iso,))
            removed += cur.rowcount
        conn.commit()
        conn.execute("VACUUM")
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"清理 cache.db 失败：{e}")
    return removed


def trim_logs(log_dir: Path, max_mb: float) -> int:
    """对 log_dir 下超 max_mb 的 *.log 保留尾部 max_mb（按行边界对齐，避免截断 UTF-8 字符）。"""
    if max_mb <= 0 or not Path(log_dir).exists():
        return 0
    max_bytes = int(max_mb * 1024 * 1024)
    trimmed = 0
    for p in Path(log_dir).glob("*.log"):
        try:
            if p.stat().st_size > max_bytes:
                tail = p.read_bytes()[-max_bytes:]
                nl = tail.find(b"\n")
                if 0 <= nl < len(tail) - 1:
                    tail = tail[nl + 1:]
                p.write_bytes(tail)
                trimmed += 1
        except OSError:
            pass
    return trimmed


# ── 编排 + 调度 ─────────────────────────────────────────────────────


def run_once() -> dict:
    """执行一次完整清理，返回各分项计数（用于日志）。"""
    result = {
        "uploads": sweep_files(config.UPLOAD_DIR, _FILE_DAYS),
        "output": sweep_files(config.OUTPUT_DIR, _FILE_DAYS),
        "tmp_lo": sweep_tmp_lo(_FILE_DAYS),
        "cache_rows": prune_cache(config.CACHE_DB, _CACHE_DAYS),
        "logs_trimmed": trim_logs(config.LOGS_DIR, _LOGS_MAX_MB),
    }
    logger.info(f"[cleanup] document_extract: {result}")
    return result


async def cleanup_loop() -> None:
    """周期性清理。任何一轮异常都不终止循环（仅记录），避免长期不再清理。"""
    while True:
        try:
            await asyncio.to_thread(run_once)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[cleanup] 循环异常：{e}")
        await asyncio.sleep(_INTERVAL)


async def start() -> asyncio.Task | None:
    """启动清理后台任务，返回 task 句柄（供 shutdown 取消）。"""
    if _INTERVAL <= 0:
        logger.info("[cleanup] CLEANUP_INTERVAL_SECONDS<=0，已禁用定时清理")
        return None
    return asyncio.create_task(cleanup_loop())


async def stop(task: asyncio.Task | None) -> None:
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

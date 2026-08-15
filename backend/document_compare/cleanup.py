"""document_compare 定时清理：回收 uploads/（待比对 PDF）与 compare_results/（结果 PDF），
避免长期占用存储。

策略：仅按 mtime 删除超过保留期的文件。进行中的比对写入的临时图（tmp_imgs/）
mtime 为当前时刻，故按保留期清扫不会误删在用文件。保留期均可经环境变量覆盖
（见 config.py）；置 0 关闭对应清理。

对 AI 问答上下文的影响：清理掉用户引用过的比对文件后，compare_documents 工具会
返回 "文件不存在或已过期（可能已被定时清理），请重新上传后再试"（见 main.py 各端点
+ office_mcp._handle_error），由 agent 转告用户重新上传，不会崩溃或盲目重试。
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

import config

logger = logging.getLogger("cleanup")

_FILE_DAYS = config.CLEANUP_FILE_DAYS
_INTERVAL = config.CLEANUP_INTERVAL_SECONDS


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


def run_once() -> dict:
    result = {
        "uploads": sweep_files(config.UPLOAD_DIR, _FILE_DAYS),
        "output": sweep_files(config.OUTPUT_DIR, _FILE_DAYS),
        "tmp": sweep_files(config.TMP_DIR, _FILE_DAYS),
    }
    logger.info(f"[cleanup] document_compare: {result}")
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

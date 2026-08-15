"""音频索引防抖自动重建（处理器触发）。

模型与图像一致：每个目录 → 一个 1:1 索引 + 一个全局索引。
- upload_audios（转写完成后）/ delete_audios 调用 schedule_audio_rebuild(folder)。
- 防抖合并后重建：global（所有文件夹）+ 各变更文件夹的 1:1 同名索引。

不沿用 FS watcher：Whisper 转写慢，文件创建事件早于转写完成，watcher 会在
texts/*.json 未写完时读到残缺转写，故由处理器在转写完成后显式触发。
"""
import os
import threading

from config import REPO_AUDIOS_ROOT
from core.audios.build import build_audio_index

_DEBOUNCE_SECONDS = 4.0  # 批量增删合并窗口

_lock = threading.Lock()
_timer = None
_pending_folders = set()
_sbert = None
REPO = str(REPO_AUDIOS_ROOT)


def init_audio_monitor(sbert):
    """在 lifespan 中注入 SBERT 模型（供后台重建使用）。"""
    global _sbert
    _sbert = sbert


def schedule_audio_rebuild(folder, sbert=None):
    """登记一个需重建的文件夹，防抖后批量重建 global + 该文件夹索引。可在请求线程调用。"""
    global _timer, _sbert
    if sbert is not None:
        _sbert = sbert
    with _lock:
        _pending_folders.add(folder)
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(_DEBOUNCE_SECONDS, _flush)
        _timer.start()


def _flush():
    """防抖到点：重建 global（所有文件夹）+ 各待重建文件夹的 1:1 同名索引。"""
    global _timer
    with _lock:
        folders = list(_pending_folders)
        _pending_folders.clear()
        _timer = None
    sbert = _sbert

    # 1) global：所有文件夹
    try:
        all_folders = [
            d
            for d in os.listdir(REPO)
            if os.path.isdir(os.path.join(REPO, d))
        ]
        if all_folders:
            build_audio_index(all_folders, "global", sbert)
            print("[AudioRebuild] global 音频索引重建完成")
    except Exception as e:
        print(f"[AudioRebuild] global 重建失败: {e}")

    # 2) 各变更文件夹的 1:1 索引
    for folder in folders:
        try:
            build_audio_index([folder], folder, sbert)
            print(f"[AudioRebuild] {folder} 音频索引重建完成")
        except Exception as e:
            print(f"[AudioRebuild] {folder} 重建失败: {e}")

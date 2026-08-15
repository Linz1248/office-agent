"""图像仓库监控：目录变动后自动重建索引（每个目录对应一个 1:1 索引 + 全局索引）。

- 每个顶层文件夹 F → 索引 F（仅来自 F，1:1）。
- 另维护 global（所有文件夹）。
- 变更某文件夹 F 时，仅重建 global + F 的 1:1 索引（精确、高效）。
- 安全保护：若 F 的现有索引是子集/多文件夹索引（meta folder_names != [F]，如覆盖多
  文件夹的 InsightFace 人脸索引），跳过不覆盖，以免破坏人脸索引/子集索引。
"""
import os
import time
import threading
import json
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from config import REPO_IMAGES_ROOT, INDICE_META_ROOT
from core.images.build import build_image_index

IMAGES_REPO_DIR = str(REPO_IMAGES_ROOT)
META_DIR = str(INDICE_META_ROOT)

stop_event = threading.Event()
build_thread = None
model = None
preprocess = None
device = None
debounce_timer = None
_pending_folders = set()
_pending_lock = threading.Lock()
DEBOUNCE_SECONDS = 5  # 无变动持续时间后才重建索引


def _top_folder(path):
    """从仓库内绝对路径提取顶层文件夹名；仓库外或仓库根本身返回 None。"""
    try:
        rel = os.path.relpath(path, IMAGES_REPO_DIR)
    except ValueError:
        return None
    if rel.startswith("..") or rel == ".":
        return None
    return rel.split(os.sep)[0]


def _is_clip_1to1(folder):
    """folder 的现有索引是否为 CLIP 1:1（无索引，或 meta folder_names==[folder]）。

    子集/多文件夹索引（如覆盖多个人物文件夹的 face、覆盖多个车辆文件夹的 car）
    返回 False → 跳过，避免用 CLIP 1:1 覆盖 InsightFace 人脸索引或破坏子集索引。
    """
    meta_path = os.path.join(META_DIR, f"{folder}.json")
    if not os.path.isfile(meta_path):
        return True
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return True
    return meta.get("folder_names") == [folder]


def interruptible_build():
    """重建 global + 各变更文件夹的 1:1 索引（跳过子集/人脸索引）。"""
    global stop_event, model, preprocess, device

    with _pending_lock:
        folders = set(_pending_folders)
        _pending_folders.clear()

    # 1) global：所有顶层文件夹
    try:
        all_folders = [
            d
            for d in os.listdir(IMAGES_REPO_DIR)
            if os.path.isdir(os.path.join(IMAGES_REPO_DIR, d))
        ]
        if all_folders:
            print("[Build] 重建 global 索引")
            build_image_index(
                all_folders, "global", model, preprocess, device, stop_event
            )
            print("[Build] global 索引重建完成")
        if stop_event.is_set():
            return
    except Exception as e:
        print(f"[Build] global 重建失败: {e}")

    # 2) 各变更文件夹的 1:1 索引
    for folder in sorted(folders):
        if stop_event.is_set():
            return
        folder_path = os.path.join(IMAGES_REPO_DIR, folder)
        if not os.path.isdir(folder_path):
            continue
        if not _is_clip_1to1(folder):
            print(f"[Build] 跳过 {folder}（子集/人脸索引，不覆盖）")
            continue
        try:
            build_image_index(
                [folder], folder, model, preprocess, device, stop_event
            )
            print(f"[Build] {folder} 1:1 索引重建完成")
        except Exception as e:
            print(f"[Build] {folder} 重建失败: {e}")


def restart_build():
    global build_thread, stop_event

    if build_thread is not None and build_thread.is_alive():
        print("[Monitor] 正在中断旧的构建进程...")
        stop_event.set()
        build_thread.join()
        print("[Monitor] 旧构建已终止")

    stop_event.clear()
    build_thread = threading.Thread(target=interruptible_build, daemon=True)
    build_thread.start()


def debounce_rebuild():
    """防抖计时结束后触发重建"""
    print(f"[Monitor] 文件系统稳定超过 {DEBOUNCE_SECONDS}s，开始重建索引")
    restart_build()


class ChangeHandler(FileSystemEventHandler):
    def _schedule(self, path):
        f = _top_folder(path)
        if not f:
            return
        with _pending_lock:
            _pending_folders.add(f)
        global debounce_timer
        if debounce_timer is not None:
            debounce_timer.cancel()
        debounce_timer = threading.Timer(DEBOUNCE_SECONDS, debounce_rebuild)
        debounce_timer.start()

    def on_created(self, event):
        self._schedule(event.src_path)

    def on_deleted(self, event):
        self._schedule(event.src_path)

    def on_moved(self, event):
        self._schedule(event.src_path)
        self._schedule(getattr(event, "dest_path", None))


def start_monitor(clip_model, clip_preprocess, clip_device):
    global model, preprocess, device
    model, preprocess, device = clip_model, clip_preprocess, clip_device

    # 启动时全量同步：把所有顶层文件夹登记为待重建
    with _pending_lock:
        _pending_folders.clear()
        if os.path.isdir(IMAGES_REPO_DIR):
            for d in os.listdir(IMAGES_REPO_DIR):
                if os.path.isdir(os.path.join(IMAGES_REPO_DIR, d)):
                    _pending_folders.add(d)
    restart_build()

    event_handler = ChangeHandler()
    observer = Observer()
    observer.schedule(event_handler, IMAGES_REPO_DIR, recursive=True)
    observer.start()
    print("[Monitor] 文件监控器已启动")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

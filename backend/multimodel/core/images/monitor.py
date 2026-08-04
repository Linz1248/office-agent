import os
import time
import threading
import json
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from config import REPO_IMAGES_ROOT, INDICE_IMAGES_ROOT, INDICE_META_ROOT
from core.images.feature_extractor import extract_features
from core.images.faiss_index import build_index

# 监控的图像仓库目录与全局索引路径
IMAGES_REPO_DIR = str(REPO_IMAGES_ROOT)
IMAGES_INDEX_DIR = str(INDICE_IMAGES_ROOT / "global.index")
IMAGES_META_PATH = str(INDICE_META_ROOT / "global.json")

# 全局状态
stop_event = threading.Event()
build_thread = None
model = None
preprocess = None
device = None
debounce_timer = None
DEBOUNCE_SECONDS = 5  # 无变动持续时间后才重建索引


def interruptible_build():
    global stop_event, model, preprocess, device

    print("[Build] 开始构建 global.index")
    image_paths = []
    folder_names = set()

    for root, _, files in os.walk(IMAGES_REPO_DIR):
        for f in files:
            if stop_event.is_set():
                print("[Build] 构建被中止")
                return
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")):
                full_path = os.path.join(root, f)
                image_paths.append(full_path)
                folder_names.add(os.path.relpath(root, IMAGES_REPO_DIR))

    if not image_paths:
        print("[Build] 无图片可构建索引")
        return

    features = extract_features(model, preprocess, image_paths, device)
    if stop_event.is_set():
        print("[Build] 构建被中止，放弃保存")
        return

    build_index(features, IMAGES_INDEX_DIR)
    print("[Build] global.index 构建完成")

    # 写入 meta.json 到索引的 meta 目录
    meta = {
        "index_name": os.path.basename(IMAGES_INDEX_DIR),
        "folder_names": sorted(list(folder_names)),
        "image_count": len(image_paths),
        "image_paths": image_paths,
    }

    os.makedirs(os.path.dirname(IMAGES_META_PATH), exist_ok=True)
    with open(IMAGES_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[Build] meta 信息已保存至 {IMAGES_META_PATH}")


def restart_build():
    global build_thread, stop_event

    if build_thread is not None and build_thread.is_alive():
        print("[Monitor] 正在中断旧的构建进程...")
        stop_event.set()
        build_thread.join()
        print("[Monitor] 旧构建已终止")

    stop_event.clear()
    build_thread = threading.Thread(target=interruptible_build)
    build_thread.start()


def debounce_rebuild():
    """防抖计时结束后触发重建"""
    print(f"[Monitor] 文件系统稳定超过 {DEBOUNCE_SECONDS}s，开始重建索引")
    restart_build()


class ChangeHandler(FileSystemEventHandler):
    def on_any_event(self, event):
        global debounce_timer

        # 只处理重要类型事件，忽略 modified
        if event.event_type not in ("created", "deleted", "moved"):
            return

        print(f"[Monitor] 检测到 {event.event_type}：{event.src_path}，等待稳定...")

        # 重置计时器
        if debounce_timer is not None:
            debounce_timer.cancel()
        debounce_timer = threading.Timer(DEBOUNCE_SECONDS, debounce_rebuild)
        debounce_timer.start()


def start_monitor(clip_model, clip_preprocess, clip_device):
    global model, preprocess, device
    model, preprocess, device = clip_model, clip_preprocess, clip_device

    # 启动时构建一次索引
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

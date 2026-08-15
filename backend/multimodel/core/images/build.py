"""图像索引构建可复用逻辑。

供 build_images_index 端点与 images watchdog（monitor.py）共用，避免重复。
收集 folder_names（相对 REPO_IMAGES_ROOT）下所有图片 → CLIP 特征 → FAISS 索引 →
写 indices/images/{index_name}.index + indices/meta/{index_name}.json（含 folder_names）。
"""
import os
import json

from config import REPO_IMAGES_ROOT, INDICE_IMAGES_ROOT, INDICE_META_ROOT
from core.images.feature_extractor import extract_features
from core.images.faiss_index import build_index
from core.build_progress import BuildProgress

_IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def _validate_name(name: str) -> None:
    if ".." in name or "/" in name or "\\" in name:
        raise ValueError(f"名称不合法: {name}")


def build_image_index(
    folder_names,
    index_name,
    model,
    preprocess,
    device,
    stop_event=None,
):
    """构建一个命名图像索引。folder_names 相对 REPO_IMAGES_ROOT。

    返回 dict(index_path, meta_path, image_count)，或被 stop_event 中断时返回 None。
    抛 ValueError（名称非法 / 无图片）/ FileNotFoundError（文件夹不存在）。
    """
    for fn in folder_names:
        _validate_name(fn)
    _validate_name(index_name)

    repo_root = str(REPO_IMAGES_ROOT)
    image_paths = []
    for folder_name in folder_names:
        folder_path = os.path.join(repo_root, folder_name)
        if not os.path.isdir(folder_path):
            raise FileNotFoundError(f"文件夹不存在: {folder_name}")
        for root, _dirs, files in os.walk(folder_path):
            for f in files:
                if stop_event is not None and stop_event.is_set():
                    return None
                if f.lower().endswith(_IMG_EXTS):
                    image_paths.append(os.path.join(root, f))

    if not image_paths:
        raise ValueError("指定文件夹中无图片可构建索引")

    BuildProgress.start("image", index_name, len(image_paths), phase="extracting")
    try:
        features = extract_features(
            model, preprocess, image_paths, device,
            progress_cb=lambda c, t: BuildProgress.tick("image", c),
        )
    except Exception as e:
        BuildProgress.finish("image", error=e)
        raise
    if stop_event is not None and stop_event.is_set():
        BuildProgress.finish("image")
        return None

    index_filename = (
        f"{index_name}.index" if not index_name.endswith(".index") else index_name
    )
    index_path = os.path.join(str(INDICE_IMAGES_ROOT), index_filename)
    build_index(features, index_path)

    meta = {
        "index_name": index_filename,
        "folder_names": list(folder_names),
        "image_count": len(image_paths),
        "image_paths": image_paths,
    }
    os.makedirs(str(INDICE_META_ROOT), exist_ok=True)
    meta_path = os.path.join(str(INDICE_META_ROOT), f"{index_name}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    BuildProgress.finish("image")
    return {"index_path": index_path, "meta_path": meta_path, "image_count": len(image_paths)}

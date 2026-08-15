"""音频索引构建可复用逻辑。

供 build_audios_index 端点与音频防抖调度器（core/audios/monitor.py）共用。
读取 repositories/texts/<folder>/*.json 的转写段落 → SBERT 特征 → FAISS 索引 →
写 indices/audios/{index_name}.index + indices/texts/{index_name}.json（段落数组）。
"""
import os
import json

from config import REPO_TEXTS_ROOT, INDICE_AUDIOS_ROOT, INDICE_TEXTS_ROOT
from core.audios.features import extract_text_features
from core.images.faiss_index import build_index
from core.build_progress import BuildProgress


def _validate_name(name: str) -> None:
    if ".." in name or "/" in name or "\\" in name:
        raise ValueError(f"名称不合法: {name}")


def build_audio_index(folder_names, index_name, model_sbert, stop_event=None):
    """构建一个命名音频索引。folder_names 相对 REPO_TEXTS_ROOT。

    返回 dict(index_path, segment_count)，或被 stop_event 中断时返回 None。
    抛 ValueError（名称非法 / 无有效转写文本）/ FileNotFoundError（文件夹不存在）。
    """
    for fn in folder_names:
        _validate_name(fn)
    _validate_name(index_name)

    all_texts = []
    all_segments = []
    for folder_name in folder_names:
        folder_path = os.path.join(str(REPO_TEXTS_ROOT), folder_name)
        if not os.path.isdir(folder_path):
            raise FileNotFoundError(f"文件夹不存在: {folder_name}")
        for root, _dirs, files in os.walk(folder_path):
            for f in files:
                if stop_event is not None and stop_event.is_set():
                    return None
                if f.lower().endswith(".json"):
                    with open(os.path.join(root, f), "r", encoding="utf-8") as file:
                        data = json.load(file)
                        for seg in data.get("segments", []):
                            all_texts.append(seg["text"])
                            all_segments.append(seg)

    if not all_texts:
        raise ValueError("未找到有效的转写文本")

    BuildProgress.start("audio", index_name, len(all_segments), phase="extracting")
    try:
        features = extract_text_features(all_texts, model_sbert)
    except Exception as e:
        BuildProgress.finish("audio", error=e)
        raise

    index_path = os.path.join(str(INDICE_AUDIOS_ROOT), f"{index_name}.index")
    meta_path = os.path.join(str(INDICE_TEXTS_ROOT), f"{index_name}.json")
    build_index(features, index_path)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(all_segments, f, ensure_ascii=False, indent=2)

    BuildProgress.finish("audio")
    return {"index_path": index_path, "segment_count": len(all_segments)}

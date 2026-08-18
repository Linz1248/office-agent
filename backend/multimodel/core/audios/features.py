import os
import json
import numpy as np
from typing import List, Dict
import torch
from pydub import AudioSegment
from opencc import OpenCC
from sentence_transformers import SentenceTransformer
from faster_whisper import WhisperModel

# 国内 HuggingFace 镜像
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


def load_audio_model(device):
    whisper_device = "cuda" if "cuda" in device else "cpu"
    model_sbert = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2", device=device)
    model_whisper = WhisperModel("small", device=whisper_device, compute_type="float16")
    cc = OpenCC("t2s")

    return model_whisper, model_sbert, cc


def transcribe_audio_segments(audio_path: str, model, cc) -> List[Dict]:
    segments, _ = model.transcribe(
        audio_path,
        beam_size=2,
        language="zh",
        task="transcribe",
        vad_parameters={
            "min_speech_duration_ms": 2000,
            "max_speech_duration_ms": 14000,
            "speech_pad_ms": 1000,
        },
    )

    results = []
    for seg in segments:
        text_simplified = cc.convert(seg.text.strip())
        results.append(
            {
                "text": text_simplified,
                "start": round(float(seg.start), 2),
                "end": round(float(seg.end), 2),
                "audio_path": audio_path.replace("\\", "/"),
            }
        )

    return results


def save_transcription_to_json(audio_file: str, results: List[Dict], output_dir: str) -> str:
    """将转写结果保存到 JSON 文件"""
    os.makedirs(output_dir, exist_ok=True)  # 创建目录（如果不存在）

    # 从 audio_file 提取文件名
    base_name = os.path.splitext(os.path.basename(audio_file))[0]
    output_path = os.path.join(output_dir, f"{base_name}.json").replace("\\", "/")

    # 保存转写结果
    transcription_data = {
        "audio_file": audio_file.replace("\\", "/"),
        "segments": results,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(transcription_data, f, ensure_ascii=False, indent=4)

    return output_path


def extract_text_features(text_list, model_sbert):
    """
    将一批文本转为归一化的句向量，供 FAISS 索引使用
    """
    embeddings = model_sbert.encode(text_list, normalize_embeddings=True)
    return np.array(embeddings).astype("float32")

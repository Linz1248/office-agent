import torch
from PIL import Image
from tqdm import tqdm
import numpy as np
from pydantic import BaseModel

from cn_clip.clip import load_from_name, tokenize


def load_clip_model(device, models_dir):
    """加载 Chinese-CLIP ViT-B-16 模型，从本地 models_dir 读取（缺失则下载）。"""
    print("加载 Chinese-CLIP 模型...")
    model, preprocess = load_from_name(
        "ViT-B-16", device=device, download_root=str(models_dir)
    )
    model.eval()
    return model, preprocess  # 通常使用验证集预处理


def extract_features(model, preprocess, paths, device, progress_cb=None):
    all_features = []
    total = len(paths)
    for i, path in enumerate(tqdm(paths, desc="提取图像特征")):
        image = preprocess(Image.open(path).convert("RGB")).unsqueeze(0).to(device)
        with torch.no_grad():
            features = model.encode_image(image)
            features = features / features.norm(dim=-1, keepdim=True)
        all_features.append(features.cpu().numpy())
        if progress_cb is not None:
            try:
                progress_cb(i + 1, total)
            except Exception:
                pass
    return np.vstack(all_features).astype("float32")


def extract_text(model, text: str, device):
    # 使用 cn_clip 的 tokenize 函数
    text_tokens = tokenize([text]).to(device)

    with torch.no_grad():
        text_features = model.encode_text(text_tokens)
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)

    return text_features.cpu().numpy().astype("float32")


class TextQuery(BaseModel):
    text: str

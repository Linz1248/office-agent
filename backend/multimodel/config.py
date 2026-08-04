"""multimodel 服务统一配置。

所有路径基于服务根目录（本文件所在目录），不依赖运行时的工作目录，
因此无论从哪里启动 `uvicorn main:app` 都能正确定位资源。
关键参数可通过环境变量覆盖。
"""
import os
from pathlib import Path

# 服务根目录：backend/multimodel/
SERVICE_ROOT = Path(__file__).resolve().parent

# 模型与数据目录
MODELS_DIR = SERVICE_ROOT / "models"
REPO_ROOT = SERVICE_ROOT / "repositories"
INDEX_ROOT = SERVICE_ROOT / "indices"

REPO_IMAGES_ROOT = REPO_ROOT / "images"
REPO_AUDIOS_ROOT = REPO_ROOT / "audios"
REPO_TEXTS_ROOT = REPO_ROOT / "texts"
REPO_THUMBNAIL_ROOT = REPO_ROOT / "thumbnails"

INDICE_IMAGES_ROOT = INDEX_ROOT / "images"
INDICE_AUDIOS_ROOT = INDEX_ROOT / "audios"
INDICE_TEXTS_ROOT = INDEX_ROOT / "texts"
INDICE_META_ROOT = INDEX_ROOT / "meta"

def cuda_available() -> bool:
    """延迟探测 CUDA，避免在导入 config 时强依赖 torch。"""
    try:
        import torch  # noqa: WPS433
        return torch.cuda.is_available()
    except Exception:
        return False


# 运行设备：可用 MULTIMODEL_DEVICE 覆盖（如 "cpu" / "cuda:1"），默认自动探测
DEVICE = os.environ.get("MULTIMODEL_DEVICE") or ("cuda:0" if cuda_available() else "cpu")

# 服务端口
PORT = int(os.environ.get("MULTIMODEL_PORT", "8000"))

# 国内 HuggingFace 镜像，避免下载模型时连不上官方源
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# insightface 从本地 models 目录加载 buffalo_l，避免走默认 repo
os.environ.setdefault("INSIGHTFACE_HOME", str(SERVICE_ROOT))


def cuda_available() -> bool:
    """延迟探测 CUDA，避免在导入 config 时强依赖 torch。"""
    try:
        import torch  # noqa: WPS433
        return torch.cuda.is_available()
    except Exception:
        return False

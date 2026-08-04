"""document_extract 服务统一配置。

路径基于服务根目录（本文件所在目录），关键参数可通过环境变量覆盖。
"""
import os
from pathlib import Path

# 服务根目录：backend/document_extract/
SERVICE_ROOT = Path(__file__).resolve().parent

# 运行目录
UPLOAD_DIR = SERVICE_ROOT / "uploads"
DATA_DIR = SERVICE_ROOT / "data"          # 样例 PDF 与中间产物（temp.md / prompt.txt）
LOG_DIR = SERVICE_ROOT / "logs"

# 预训练模型根目录（PaddleOCR PPStructureV3 各模块 + sat 段落切分模型）
PRETRAINED_MODELS_DIR = Path(
    os.environ.get("DOC_EXTRACT_PRETRAINED_MODELS", str(SERVICE_ROOT / "pretrained_models"))
)
SAT_MODEL_ID = str(PRETRAINED_MODELS_DIR / "sat-6l-sm")

# 数据库（users.db 使用 nolock 以兼容 NFS；cache.db 使用 WAL）
USERS_DB = SERVICE_ROOT / "users.db"
CACHE_DB = SERVICE_ROOT / "cache.db"
CACHE_VERSION = 1

# 鉴权
SECRET_KEY = os.environ.get("DOC_EXTRACT_SECRET_KEY", "document-extract-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # token 有效时间，单位：分钟

# OCR / 推理设备（PaddlePaddle 设备字符串，如 "gpu:1" / "cpu"）
DEVICE = os.environ.get("DOC_EXTRACT_DEVICE", "gpu:1")

# LLM（contextgem 通过 Ollama 调用本地大模型）
OLLAMA_API_BASE = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "ollama_chat/myaniu/qwen2.5-1m:14b")
LLM_TIMEOUT = int(os.environ.get("DOC_EXTRACT_LLM_TIMEOUT", "120"))
LLM_SEED = 42

# 服务端口
PORT = int(os.environ.get("DOC_EXTRACT_PORT", "9090"))

# PPStructureV3 各子模块的本地模型目录名（均位于 PRETRAINED_MODELS_DIR 下）
PP_STRUCTURE_MODEL_DIRS = {
    "text_detection_model_dir": "PP-OCRv5_server_det_infer",
    "text_recognition_model_dir": "PP-OCRv5_server_rec_infer",
    "doc_unwarping_model_dir": "UVDoc_infer",
    "layout_detection_model_dir": "PP-DocLayout_plus-L_infer",
    "region_detection_model_dir": "PP-DocBlockLayout_infer",
    "wired_table_structure_recognition_model_dir": "SLANeXt_wired_infer",
    "wired_table_cells_detection_model_dir": "RT-DETR-L_wired_table_cell_det_infer",
    "wireless_table_cells_detection_model_dir": "RT-DETR-L_wireless_table_cell_det_infer",
    "doc_orientation_classify_model_dir": "PP-LCNet_x1_0_doc_ori_infer",
    "table_classification_model_dir": "PP-LCNet_x1_0_table_cls",
    "wireless_table_structure_recognition_model_dir": "SLANet_plus",
    "textline_orientation_model_dir": "PP-LCNet_x1_0_textline_ori",
    "table_orientation_classify_model_dir": "PP-LCNet_x1_0_doc_ori_infer",
}

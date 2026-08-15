"""document_compare 服务统一配置。

路径基于服务根目录（本文件所在目录）；OCR/印章模型由 RapidOCR / PaddleOCR 自动下载，无需本地模型目录。
"""
import os
from pathlib import Path

# 服务根目录：backend/document_compare/
SERVICE_ROOT = Path(__file__).resolve().parent

# 运行目录
TMP_DIR = SERVICE_ROOT / "tmp_imgs"          # 临时图片目录
UPLOAD_DIR = SERVICE_ROOT / "uploads"        # 上传的待比对 PDF
OUTPUT_DIR = SERVICE_ROOT / "compare_results"  # 比对结果 PDF（通过 /static 暴露）

# 服务端口
PORT = int(os.environ.get("DOC_COMPARE_PORT", "9900"))

# 定时清理保留期（单位：天），均可经环境变量覆盖；置 0 关闭对应清理
# 清理 uploads/（待比对 PDF）与 compare_results/（结果 PDF）；tmp_imgs/ 在比对流程内
# 已即时清理，定时清扫仅兜底（进行中的临时图 mtime 为当前，不会被误删）
CLEANUP_FILE_DAYS = float(os.environ.get("CLEANUP_FILE_DAYS", "7"))
CLEANUP_INTERVAL_SECONDS = float(os.environ.get("CLEANUP_INTERVAL_SECONDS", "3600"))

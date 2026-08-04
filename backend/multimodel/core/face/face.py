import os
from insightface.app import FaceAnalysis

from config import SERVICE_ROOT


def load_face_model(device="cuda:0", root=None):
    """加载 insightface buffalo_l 人脸分析模型，从本地 models 目录读取。"""
    model_root = str(root) if root is not None else str(SERVICE_ROOT)
    model_name = "buffalo_l"

    # 明确传入 root，使其从 <服务根>/models/buffalo_l 加载
    app = FaceAnalysis(name=model_name, root=model_root)
    app.prepare(ctx_id=0 if device == "cuda" else -1)

    return app


if __name__ == "__main__":
    load_face_model()

# multimodel 多模态检索服务

基于 Chinese-CLIP / Whisper / SBERT / InsightFace 的图像、语音、人脸相似度检索。运行在 conda 环境 `retrieve`，默认端口 `8000`。

## 启动

```bash
conda activate retrieve
cd backend/multimodel
uvicorn main:app --host 0.0.0.0 --port 8000
```

启动时会加载 CLIP、Whisper、SBERT、InsightFace 模型，并启动一个后台线程监控 `repositories/images` 目录：文件变动稳定 5 秒后自动重建全局索引 `indices/images/global.index`。

## 目录

```
multimodel/
├── main.py              # FastAPI 入口与全部接口
├── config.py            # 路径/设备/端口配置
├── core/
│   ├── images/          # CLIP 特征提取、FAISS 索引、目录监控
│   ├── audios/          # Whisper 转写、SBERT 文本特征
│   └── face/            # InsightFace 人脸特征
├── models/              # 模型权重（CLIP、buffalo_l）
├── repositories/        # 图像/音频/文本/缩略图仓库
├── indices/             # FAISS 索引与 meta
└── requirements.txt
```

## 主要接口

- 图像：`/upload_images/`、`/build_images_index/`、`/get_images_dir/`、`/delete_images/`、`/images_search_images/`、`/text_search_images/`
- 语音：`/upload_audios/`、`/build_audios_index/`、`/get_audios_dir/`、`/delete_audios/`、`/text_search_audios/`
- 人脸：`/build_faces_index/`、`/images_search_faces/`
- 静态资源：`/repositories`、`/images`、`/audios`、`/texts`、`/thumbnails`

## 配置（环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `MULTIMODEL_DEVICE` | 自动（有 GPU 则 `cuda:0`） | 推理设备，如 `cpu` / `cuda:1` |
| `MULTIMODEL_PORT` | `8000` | 服务端口 |
| `HF_ENDPOINT` | `https://hf-mirror.com` | HuggingFace 镜像 |
| `INSIGHTFACE_HOME` | 服务根目录 | insightface 模型根 |

模型从 `models/` 目录加载（Chinese-CLIP 缺失时会从镜像下载到该目录；buffalo_l 需提前放置在 `models/buffalo_l/`）。

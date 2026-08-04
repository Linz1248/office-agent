# document_compare 文档比对服务

基于 RapidOCR + PaddleOCR 印章识别的合同/文档差异比对，在 PDF 上按词标注删除/新增/修改内容并输出可下载的结果 PDF。运行在 conda 环境 `agent`，默认端口 `9900`。

## 启动

```bash
conda activate agent
cd backend/document_compare
uvicorn main:app --host 0.0.0.0 --port 9900
```

## 目录

```
document_compare/
├── main.py              # FastAPI 入口与比对逻辑
├── config.py            # 路径/端口配置
├── utils/
│   ├── draw_boxes.py    # 在 PDF 上绘制差异框
│   └── ocr_utils.py     # RapidOCR 识别 + 印章识别
├── data/                # 样例 PDF
├── uploads/             # 运行时上传目录（自动创建）
├── tmp_imgs/            # 运行时临时图片（自动创建）
├── compare_results/     # 比对结果 PDF（通过 /static 暴露）
└── requirements.txt
```

## 主要接口

- `POST /upload`：上传待比对的 PDF（无鉴权）
- `POST /compare`：执行比对，返回结果文件名与相似度
- `GET /download?filename=`：获取结果文件的 `/static/` 访问 URL
- `GET /get_file?filename=`：直接返回结果 PDF
- 静态资源：`/static/`（比对结果 PDF）

## 配置（环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DOC_COMPARE_PORT` | `9900` | 服务端口 |

OCR / 印章识别模型由 RapidOCR、PaddleOCR 自动下载，无需本地模型目录。

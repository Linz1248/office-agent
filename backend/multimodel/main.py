"""multimodel 服务：图像 / 语音 / 人脸相似度检索 API。

启动时加载 CLIP、Whisper、SBERT、InsightFace 模型；当图像仓库目录发生变动时，
自动重建全局索引 global.index。
"""
import os
import io
import json
import time
import base64
import shutil
import tempfile
import threading
from datetime import datetime
from typing import List

import numpy as np
import torch
import cv2
from PIL import Image
from pydub import AudioSegment
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import config
from config import (
    MODELS_DIR,
    REPO_ROOT,
    INDEX_ROOT,
    REPO_IMAGES_ROOT,
    REPO_AUDIOS_ROOT,
    REPO_TEXTS_ROOT,
    REPO_THUMBNAIL_ROOT,
    INDICE_IMAGES_ROOT,
    INDICE_AUDIOS_ROOT,
    INDICE_TEXTS_ROOT,
    INDICE_META_ROOT,
    DEVICE,
)
from core.images.monitor import start_monitor
from core.images.feature_extractor import (
    load_clip_model,
    extract_features,
    extract_text,
    TextQuery,
)
from core.images.faiss_index import build_index, load_index
from core.audios.features import (
    load_audio_model,
    transcribe_audio_segments,
    save_transcription_to_json,
    extract_text_features,
)
from core.face.face import load_face_model


# 全局模型实例（在 lifespan 中初始化）
clip_model = None
preprocess = None
model_whisper = None
model_sbert = None
cc_model = None
face_model = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global clip_model, preprocess, model_whisper, model_sbert, cc_model, face_model

    print("启动时加载CLIP模型...")
    clip_model, preprocess = load_clip_model(DEVICE, MODELS_DIR)
    print("CLIP 模型加载完成")

    # 加载语音模型
    model_whisper, model_sbert, cc_model = load_audio_model(DEVICE)
    print("语音模型加载完成")

    # 加载人脸模型
    face_model = load_face_model(DEVICE)

    # 需要确保存在的目录列表
    paths_to_check = [
        REPO_IMAGES_ROOT,
        REPO_AUDIOS_ROOT,
        INDICE_IMAGES_ROOT,
        INDICE_AUDIOS_ROOT,
        REPO_TEXTS_ROOT,
        INDICE_TEXTS_ROOT,
        INDICE_META_ROOT,
        REPO_THUMBNAIL_ROOT,
    ]
    for path in paths_to_check:
        os.makedirs(path, exist_ok=True)

    # 监测仓库变动
    threading.Thread(
        target=start_monitor, args=(clip_model, preprocess, DEVICE), daemon=True
    ).start()
    print("[FastAPI] 已启动仓库目录监控线程")

    yield


app = FastAPI(title="图像相似度检索API", lifespan=lifespan)

# 跨域资源共享
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态资源挂载（挂载前确保目录存在）
static_dirs = {
    "/repositories": str(REPO_ROOT),
    "/images": str(REPO_IMAGES_ROOT),
    "/audios": str(REPO_AUDIOS_ROOT),
    "/texts": str(REPO_TEXTS_ROOT),
    "/thumbnails": str(REPO_THUMBNAIL_ROOT),
}
for mount_path, dir_path in static_dirs.items():
    os.makedirs(dir_path, exist_ok=True)
    app.mount(mount_path, StaticFiles(directory=dir_path), name=mount_path.strip("/"))


# ========================== 工具函数 ===========================

def build_tree(root_path: str, only_dirs: bool = False):
    def walk(path: str):
        children = []
        file_count = 0

        for entry in sorted(os.listdir(path)):
            full_path = os.path.join(path, entry)
            if os.path.isdir(full_path):
                children.append(walk(full_path))
            else:
                file_count += 1

        node = {
            "name": os.path.basename(path),
            "type": "dir",
            "children": children if only_dirs else [],
        }
        if only_dirs:
            node["file_count"] = file_count
        else:
            # 如果不是only_dirs，直接返回完整文件+文件夹结构
            node["children"] = []
            for entry in sorted(os.listdir(path)):
                full_path = os.path.join(path, entry)
                if os.path.isdir(full_path):
                    node["children"].append(walk(full_path))
                else:
                    node["children"].append({"name": entry, "type": "file"})
        return node

    if not os.path.exists(root_path):
        return []

    root_node = walk(root_path)
    return root_node["children"]


def load_image_paths_from_meta(index_name: str):
    meta_path = os.path.join(str(INDICE_META_ROOT), f"{index_name}.json")
    if not os.path.exists(meta_path):
        raise HTTPException(status_code=404, detail=f"meta 文件不存在: {index_name}.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    return meta.get("image_paths", [])


# ========================== 图像 API 接口 ==========================

@app.post("/upload_images/")
async def upload_images(folder_name: str = Form(...), files: List[UploadFile] = File(...)):
    """
    上传多张图片，存储到 repositories/images/<folder_name>/，
    并镜像缩略图到 repositories/thumbnails/<folder_name>/
    """
    # 安全性检查
    if ".." in folder_name or "/" in folder_name or "\\" in folder_name:
        raise HTTPException(status_code=400, detail="文件夹名称不合法")

    save_dir = os.path.join(str(REPO_IMAGES_ROOT), folder_name)
    thumb_dir = os.path.join(str(REPO_THUMBNAIL_ROOT), folder_name)

    os.makedirs(save_dir, exist_ok=True)
    os.makedirs(thumb_dir, exist_ok=True)

    saved_files = []
    for upload_file in files:
        ext = os.path.splitext(upload_file.filename)[1].lower()
        if ext not in [".jpg", ".jpeg", ".png", ".bmp", ".webp"]:
            continue

        # 保存原图
        content = await upload_file.read()
        save_path = os.path.join(save_dir, upload_file.filename)
        with open(save_path, "wb") as f:
            f.write(content)

        # 生成缩略图
        try:
            image = Image.open(io.BytesIO(content))
            image.thumbnail((256, 256))  # 设置缩略图最大边长
            thumb_path = os.path.join(thumb_dir, upload_file.filename)
            image.save(thumb_path)
        except Exception as e:
            print(f"生成缩略图失败: {upload_file.filename}, 错误: {e}")

        saved_files.append(upload_file.filename)

    return JSONResponse(
        {
            "message": f"成功上传{len(saved_files)}个文件到文件夹 {folder_name}",
            "files": saved_files,
            "save_path": save_dir,
        }
    )


@app.post("/build_images_index/")
async def build_images_index(
    folder_names: List[str] = Query(..., description="要构建索引的文件夹名列表，均位于 repositories 目录下"),
    index_name: str = Query(..., description="索引文件名，不带后缀"),
):
    # 参数检查
    for fn in folder_names:
        if ".." in fn or "/" in fn or "\\" in fn:
            raise HTTPException(status_code=400, detail=f"文件夹名不合法: {fn}")
    if ".." in index_name or "/" in index_name or "\\" in index_name:
        raise HTTPException(status_code=400, detail="索引文件名不合法")

    # 收集所有图片路径
    image_paths = []
    for folder_name in folder_names:
        folder_path = os.path.join(str(REPO_IMAGES_ROOT), folder_name)
        if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
            raise HTTPException(status_code=404, detail=f"文件夹不存在: {folder_name}")
        for root, _, files in os.walk(folder_path):
            for f in files:
                if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")):
                    image_paths.append(os.path.join(root, f))

    if len(image_paths) == 0:
        raise HTTPException(status_code=400, detail="指定文件夹中无图片可构建索引")

    # 提取特征
    features = extract_features(clip_model, preprocess, image_paths, DEVICE)

    # 索引路径
    index_filename = f"{index_name}.index" if not index_name.endswith(".index") else index_name
    index_path = os.path.join(str(INDICE_IMAGES_ROOT), index_filename)

    # 构建索引并保存
    build_index(features, index_path)

    # 同步构建 meta 信息
    meta = {
        "index_name": index_filename,
        "folder_names": folder_names,
        "image_count": len(image_paths),
        "image_paths": image_paths,
    }
    meta_path = os.path.join(str(INDICE_META_ROOT), f"{index_name}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return JSONResponse(
        {
            "message": "索引构建成功",
            "index_path": index_path,
            "meta_path": meta_path,
            "image_count": len(image_paths),
        }
    )


@app.get("/get_images_dir/")
async def get_all_dirs_tree(
    include_files: bool = Query(False, description="是否包含具体文件（True=包含文件，False=仅返回文件夹结构）"),
):
    """
    获取 repositories 和 indices 下的目录结构（树状）
    - include_files=True: 返回包含文件的完整树
    - include_files=False: 仅返回树状的文件夹结构（children中只有子文件夹），
      同时每个文件夹会包含一个 file_count 字段，表示该目录下直接文件数。
    """
    repo_tree = build_tree(str(REPO_IMAGES_ROOT), only_dirs=not include_files)
    index_tree = build_tree(str(INDICE_IMAGES_ROOT), only_dirs=not include_files)

    return JSONResponse({"repositories": repo_tree, "indices": index_tree})


@app.post("/delete_images/")
async def delete_item(
    target: str = Query(..., description="目标类型：'repo' 或 'index' 或 'all'"),
    name: List[str] = Query(..., description="要删除的项目名称列表，格式同之前，支持多次传递参数"),
):
    """
    删除 repositories 或 indices 下的指定项目，支持多文件/文件夹批量删除。
    - target='repo': name 可以是文件夹名（如 'folder1'）、图片路径（如 'folder1/image1.jpg'）或 'all'。
    - target='index': name 可以是索引名（如 'index1' 或 'index1.index'）或 'all'（保留 global.index）。
    - target='all': 同时删除 repositories 和 indices 下的指定项目。
    - name 支持多个参数传递，例如 ?name=folder1&name=folder2/image1.jpg&name=index1
    """
    if target not in ["repo", "index", "all"]:
        raise HTTPException(status_code=400, detail="target 只可为 'repo', 'index', 'all'")
    if any(".." in n or "\\" in n for n in name):
        raise HTTPException(status_code=400, detail="路径中不能包含非法字符")
    dir_type = "images"

    # 支持传入单个 'all' 来代表全部删除
    if len(name) == 1 and name[0] == "all":
        name_list = ["all"]
    else:
        name_list = name

    if not name_list:
        raise HTTPException(status_code=400, detail="name 参数不能为空")

    subdir_targets = ["images", "audios"] if dir_type == "all" else [dir_type]
    deleted_items = []

    for sd_type in subdir_targets:
        repo_root = os.path.join(str(REPO_ROOT), sd_type)
        index_root = os.path.join(str(INDEX_ROOT), sd_type)

        if "all" in name_list:
            # 全删
            if target in ["repo", "all"] and os.path.exists(repo_root):
                shutil.rmtree(repo_root, ignore_errors=True)
                os.makedirs(repo_root, exist_ok=True)
                deleted_items.append("all")
            if target in ["index", "all"] and os.path.exists(index_root):
                for f in os.listdir(index_root):
                    f_path = os.path.join(index_root, f)
                    if f.endswith(".index") and f != "global.index":
                        os.remove(f_path)
                        deleted_items.append(f)
        else:
            # 删除指定项
            for subname in name_list:
                if target in ["repo", "all"]:
                    path = os.path.join(repo_root, subname)
                    if "/" in subname:
                        # 删除 images 中的文件
                        if not subname.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")):
                            raise HTTPException(status_code=400, detail=f"不支持的文件格式: {subname}")
                        if os.path.isfile(path):
                            os.remove(path)
                            deleted_items.append(subname)

                            # 同步删除 thumbnails 中对应的文件
                            thumb_file_path = os.path.join(str(REPO_ROOT), "thumbnails", subname)
                            if os.path.isfile(thumb_file_path):
                                os.remove(thumb_file_path)
                                deleted_items.append(f"thumbnails: {subname}")
                        else:
                            raise HTTPException(status_code=404, detail=f"图片不存在: {path}")
                    elif os.path.isdir(path):
                        # 删除 images 中的文件夹
                        shutil.rmtree(path)
                        deleted_items.append(subname)

                        # 同步删除 thumbnails 中对应的文件夹
                        thumb_dir_path = os.path.join(str(REPO_ROOT), "thumbnails", subname)
                        if os.path.isdir(thumb_dir_path):
                            shutil.rmtree(thumb_dir_path)
                            deleted_items.append(f"thumbnails: {subname}")
                    elif os.path.isfile(path):
                        # 删除 images 中的根目录文件（较少见）
                        if not subname.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")):
                            raise HTTPException(status_code=400, detail=f"不支持的文件格式: {subname}")
                        os.remove(path)
                        deleted_items.append(subname)

                        # 同步删除 thumbnails 中对应的文件
                        thumb_file_path = os.path.join(str(REPO_ROOT), "thumbnails", subname)
                        if os.path.isfile(thumb_file_path):
                            os.remove(thumb_file_path)
                            deleted_items.append(f"thumbnails: {subname}")
                    else:
                        raise HTTPException(status_code=404, detail=f"文件或文件夹不存在: {path}")

                if target in ["index", "all"]:
                    filename = f"{subname}.index" if not subname.endswith(".index") else subname
                    if filename == "global.index":
                        raise HTTPException(status_code=403, detail="global.index 不允许删除")
                    index_path = os.path.join(index_root, filename)
                    if os.path.isfile(index_path):
                        os.remove(index_path)
                        deleted_items.append(filename)
                        index_name_without_ext = os.path.splitext(filename)[0]
                        meta_name = f"{index_name_without_ext}.json"
                        meta_root = os.path.join(str(INDEX_ROOT), "meta")
                        meta_path = os.path.join(meta_root, meta_name)
                        if os.path.isfile(meta_path):
                            os.remove(meta_path)
                            deleted_items.append(f"meta: {meta_name}")
                    else:
                        raise HTTPException(status_code=404, detail=f"索引文件不存在: {index_path}")

    if not deleted_items:
        raise HTTPException(status_code=404, detail="未找到任何可删除的项目")

    return JSONResponse(
        {
            "message": f"{target} -> {dir_type} 中已删除: {'all' if 'all' in name_list else deleted_items}"
        }
    )


@app.post("/images_search_images/")
async def search_image(
    images: List[UploadFile] = File(...),
    index_name: str = Query("global", description="索引文件名，不带 .index 后缀，默认使用 global"),
    value: float = Query(5.0, description="如果 >=1 表示返回 topK 个结果，如果在 0-1 之间表示相似度阈值"),
    return_original: bool = Query(False, description="是否返回匹配图片的原图 base64 编码"),
    return_thumbnail: bool = Query(True, description="是否返回匹配图片的缩略图 base64 编码"),
):
    print(f"\n[{datetime.now()}] 收到图像检索请求：")
    print(f"Query 参数：index_name={index_name}, value={value}, return_original={return_original}, return_thumbnail={return_thumbnail}")
    print(f"共收到 {len(images)} 张图片：")
    for img_file in images:
        print(f" - 文件名: {img_file.filename}, Content-Type: {img_file.content_type}")

    valid_exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
    temp_paths = []

    for img_file in images:
        if not img_file.filename.lower().endswith(valid_exts):
            raise HTTPException(status_code=400, detail=f"{img_file.filename} 不是支持的图片格式")

        suffix = os.path.splitext(img_file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await img_file.read())
            temp_paths.append(tmp.name)

    if not temp_paths:
        raise HTTPException(status_code=400, detail="没有有效图片")

    # 提取特征
    features = extract_features(clip_model, preprocess, temp_paths, DEVICE)
    query_feature = features.mean(axis=0, keepdims=True).astype("float32")

    # 删除临时文件
    for path in temp_paths:
        os.remove(path)

    # 加载索引
    index_file = f"{index_name}.index"
    index_path = os.path.join(str(INDICE_IMAGES_ROOT), index_file)
    index = load_index(index_path)
    if index is None:
        raise HTTPException(status_code=404, detail=f"索引文件不存在: {index_file}")

    # 加载图像路径
    image_paths = load_image_paths_from_meta(index_name)
    if len(image_paths) != index.ntotal:
        raise HTTPException(status_code=500, detail="索引条目数量与图像数量不一致，请重新构建索引")

    D, I = index.search(query_feature, len(image_paths))
    matched = []

    # 按索引与相似度组合成元组 (idx, dist)
    matched_pairs = [(idx, dist) for idx, dist in zip(I[0], D[0]) if idx != -1]
    matched_pairs.sort(key=lambda x: -x[1])  # 距离越大越相似

    # 过滤符合阈值的
    if value >= 1:
        filtered = matched_pairs[: int(value)]
    elif 0 < value < 1:
        filtered = [p for p in matched_pairs if p[1] >= value]
        if len(filtered) < 5:
            filtered = matched_pairs[:5]
    else:
        raise HTTPException(status_code=400, detail="value 应为正数：>=1 表示topk，0~1 表示相似度阈值")

    for idx, dist in filtered:
        path_rel = os.path.relpath(image_paths[idx], str(REPO_IMAGES_ROOT))
        item = {"path": path_rel, "score": float(dist)}

        abs_path = os.path.join(str(REPO_IMAGES_ROOT), path_rel)
        if return_original or return_thumbnail:
            try:
                with Image.open(abs_path) as img:
                    if return_original:
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG")
                        item["original_base64"] = base64.b64encode(buf.getvalue()).decode("utf-8")
                    if return_thumbnail:
                        img_thumb = img.copy()
                        img_thumb.thumbnail((128, 128))
                        buf_thumb = io.BytesIO()
                        img_thumb.save(buf_thumb, format="JPEG")
                        item["thumbnail_base64"] = base64.b64encode(buf_thumb.getvalue()).decode("utf-8")
            except Exception as e:
                item["error"] = f"无法处理图像: {e}"

        matched.append(item)

    return JSONResponse(
        {
            "message": "检索成功（模式: topk）" if value >= 1 else "检索成功（模式: score）",
            "matched_images": matched,
            "count": len(matched),
        }
    )


@app.post("/text_search_images/")
async def search_by_text(
    query: TextQuery,
    index_name: str = Query("global", description="索引文件名，不带 .index 后缀"),
    value: float = Query(5.0, description=">=1表示Top-K，0~1表示相似度阈值"),
    return_original: bool = Query(False, description="是否返回匹配图片原图 base64 编码"),
    return_thumbnail: bool = Query(False, description="是否返回匹配图片缩略图 base64 编码"),
):
    text = query.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本不能为空")

    query_feature = extract_text(clip_model, text, DEVICE)

    index_file = f"{index_name}.index"
    index_path = os.path.join(str(INDICE_IMAGES_ROOT), index_file)
    index = load_index(index_path)
    if index is None:
        raise HTTPException(status_code=404, detail=f"索引文件不存在: {index_file}")

    image_paths = load_image_paths_from_meta(index_name)
    if len(image_paths) != index.ntotal:
        raise HTTPException(status_code=500, detail="索引条目数量与图像数量不一致，请重新构建索引")

    D, I = index.search(query_feature, len(image_paths))
    matched_pairs = [(idx, dist) for idx, dist in zip(I[0], D[0]) if idx != -1]
    matched_pairs.sort(key=lambda x: -x[1])

    if value >= 1:
        filtered = matched_pairs[: int(value)]
    elif 0 < value < 1:
        filtered = [p for p in matched_pairs if p[1] >= (value / 2)]
        if len(filtered) < 5:
            filtered = matched_pairs[:5]
    else:
        raise HTTPException(status_code=400, detail="value 应为正数：>=1 表示topk，0~1 表示相似度阈值")

    results = []
    for idx, dist in filtered:
        path_rel = os.path.relpath(image_paths[idx], str(REPO_IMAGES_ROOT))
        item = {
            "path": path_rel,
            "score": float(dist) * 2,  # 相似度值乘以 2 表示匹配度
        }

        abs_path = os.path.join(str(REPO_IMAGES_ROOT), path_rel)
        if return_original or return_thumbnail:
            try:
                with Image.open(abs_path) as img:
                    if return_original:
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG")
                        item["original_base64"] = base64.b64encode(buf.getvalue()).decode("utf-8")
                    if return_thumbnail:
                        img_thumb = img.copy()
                        img_thumb.thumbnail((128, 128))
                        buf_thumb = io.BytesIO()
                        img_thumb.save(buf_thumb, format="JPEG")
                        item["thumbnail_base64"] = base64.b64encode(buf_thumb.getvalue()).decode("utf-8")
            except Exception as e:
                item["error"] = f"无法处理图像: {e}"

        results.append(item)

    return JSONResponse(
        {
            "message": "检索成功（模式: topk）" if value >= 1 else "检索成功（模式: score）",
            "query_text": text,
            "results": results,
            "count": len(results),
        }
    )


# ========================== 语音 API 接口 ==========================

@app.post("/upload_audios/")
async def upload_audios(folder_name: str = Form(...), files: List[UploadFile] = File(...)):
    time_start = time.time()

    if ".." in folder_name or "/" in folder_name or "\\" in folder_name:
        raise HTTPException(status_code=400, detail="文件夹名称不合法")

    save_dir = os.path.join(str(REPO_AUDIOS_ROOT), folder_name)
    meta_dir = os.path.join(str(REPO_TEXTS_ROOT), folder_name)
    os.makedirs(save_dir, exist_ok=True)
    os.makedirs(meta_dir, exist_ok=True)

    saved_files = []
    meta_files = []

    for file in files:
        filename = file.filename
        if not filename.lower().endswith((".wav", ".mp3", ".m4a")):
            continue

        save_path = os.path.join(save_dir, filename)
        content = await file.read()
        with open(save_path, "wb") as f:
            f.write(content)
        saved_files.append(save_path)

        print(f"成功保存文件: {save_path}")

    for file_path in saved_files:
        segments = transcribe_audio_segments(file_path, model_whisper, cc_model)
        meta_path = save_transcription_to_json(file_path, segments, meta_dir)
        meta_files.append(meta_path)

    time_end = time.time()
    print(f"总耗时: {time_end - time_start:.2f}s", flush=True)

    if not saved_files:
        raise HTTPException(status_code=400, detail="未上传任何有效音频文件")

    return JSONResponse(
        {
            "message": f"成功上传{len(saved_files)}个文件到文件夹 {folder_name}",
            "audio_files": saved_files,
            "save_path": save_dir,
        }
    )


@app.post("/delete_audios/")
async def delete_audios(
    target: str = Query(..., description="目标类型：'repo' 或 'index' 或 'all'"),
    name: List[str] = Query(..., description="要删除的项目名称列表，支持多次传递参数"),
):
    """
    删除 repositories 或 indices 下的指定项目，支持批量删除。
    - target='repo': 删除音频文件/文件夹，同时删除 texts 下对应 JSON 文件/文件夹。
    - target='index': 删除 faiss 索引，同时删除对应的 meta JSON 文件。
    - target='all': 同时执行上述两项。
    """
    if target not in {"repo", "index", "all"}:
        raise HTTPException(status_code=400, detail="target 只可为 'repo', 'index', 'all'")

    if any(".." in n or "\\" in n for n in name):
        raise HTTPException(status_code=400, detail="路径中不能包含非法字符")

    name_list = ["all"] if len(name) == 1 and name[0] == "all" else name
    if not name_list:
        raise HTTPException(status_code=400, detail="name 参数不能为空")

    repo_root = os.path.join(str(REPO_ROOT), "audios")
    texts_root = os.path.join(str(REPO_ROOT), "texts")
    index_root = os.path.join(str(INDEX_ROOT), "audios")
    meta_root = os.path.join(str(INDEX_ROOT), "texts")

    deleted_items = []

    # 删除所有
    if "all" in name_list:
        if target in {"repo", "all"}:
            shutil.rmtree(repo_root, ignore_errors=True)
            shutil.rmtree(texts_root, ignore_errors=True)
            os.makedirs(repo_root, exist_ok=True)
            os.makedirs(texts_root, exist_ok=True)
            deleted_items.append("repo audios all")
            deleted_items.append("texts all")

        if target in {"index", "all"}:
            for f in os.listdir(index_root):
                if f.endswith(".index") and f != "global.index":
                    os.remove(os.path.join(index_root, f))
                    deleted_items.append(f"index: {f}")
                    # 同名 meta.json
                    meta_file = f.replace(".index", ".json")
                    meta_path = os.path.join(meta_root, meta_file)
                    if os.path.isfile(meta_path):
                        os.remove(meta_path)
                        deleted_items.append(f"meta: {meta_file}")
        return JSONResponse({"message": f"已删除: {deleted_items}"})

    # 批量删除指定项
    for item in name_list:
        # 删除 repo + texts
        if target in {"repo", "all"}:
            repo_path = os.path.join(repo_root, item)
            texts_path = os.path.join(texts_root, item)

            if "/" in item:  # 指定的是具体音频文件
                if not item.lower().endswith((".mp3", ".wav", ".m4a")):
                    raise HTTPException(status_code=400, detail=f"不支持的音频格式: {item}")

                if os.path.isfile(repo_path):
                    os.remove(repo_path)
                    deleted_items.append(f"repo file: {item}")
                    # 删除对应单文件 JSON
                    json_name = os.path.splitext(os.path.basename(item))[0] + ".json"
                    json_path = os.path.join(texts_root, json_name)
                    if os.path.isfile(json_path):
                        os.remove(json_path)
                        deleted_items.append(f"text json: {json_name}")
                else:
                    raise HTTPException(status_code=404, detail=f"音频文件不存在: {repo_path}")

            elif os.path.isdir(repo_path):  # 指定的是文件夹
                shutil.rmtree(repo_path)
                deleted_items.append(f"repo folder: {item}")
                if os.path.isdir(texts_path):
                    shutil.rmtree(texts_path)
                    deleted_items.append(f"text folder: {item}")

            elif os.path.isfile(repo_path):  # 边界情况（孤立文件）
                os.remove(repo_path)
                deleted_items.append(f"repo orphan file: {item}")
            else:
                raise HTTPException(status_code=404, detail=f"repo 项不存在: {repo_path}")

        # 删除 index + meta
        if target in {"index", "all"}:
            index_file = item if item.endswith(".index") else f"{item}.index"
            index_path = os.path.join(index_root, index_file)

            if index_file == "global.index":
                raise HTTPException(status_code=403, detail="global.index 不允许删除")

            if os.path.isfile(index_path):
                os.remove(index_path)
                deleted_items.append(f"index: {index_file}")

                meta_file = index_file.replace(".index", ".json")
                meta_path = os.path.join(meta_root, meta_file)
                if os.path.isfile(meta_path):
                    os.remove(meta_path)
                    deleted_items.append(f"meta: {meta_file}")
            else:
                raise HTTPException(status_code=404, detail=f"索引文件不存在: {index_path}")

    if not deleted_items:
        raise HTTPException(status_code=404, detail="未找到任何可删除的项目")

    return JSONResponse({"message": f"成功删除: {deleted_items}"})


@app.get("/get_audios_dir/")
async def get_all_dirs_tree(
    include_files: bool = Query(False, description="是否包含具体文件（True=包含文件，False=仅返回文件夹结构）"),
):
    """
    获取 repositories 和 indices 下的目录结构（树状）
    - include_files=True: 返回包含文件的完整树
    - include_files=False: 仅返回树状的文件夹结构（children中只有子文件夹），
      同时每个文件夹会包含一个 file_count 字段，表示该目录下直接文件数。
    """
    repo_tree = build_tree(str(REPO_AUDIOS_ROOT), only_dirs=not include_files)
    index_tree = build_tree(str(INDICE_AUDIOS_ROOT), only_dirs=not include_files)

    return JSONResponse({"repositories": repo_tree, "indices": index_tree})


@app.post("/build_audios_index/")
async def build_audios_index(
    folder_names: List[str] = Query(..., description="多个音频文件所在的文件夹（位于 repositories/audios 下）"),
    index_name: str = Query(..., description="索引文件名，不带后缀"),
):
    # 参数检查
    for fn in folder_names:
        if ".." in fn or "/" in fn or "\\" in fn:
            raise HTTPException(status_code=400, detail=f"文件夹名不合法: {fn}")
    if ".." in index_name or "/" in index_name or "\\" in index_name:
        raise HTTPException(status_code=400, detail="索引文件名不合法")

    # 遍历 repositories/texts/下的多个文件夹，查找所有 JSON 文件
    all_texts = []
    all_segments = []

    for folder_name in folder_names:
        folder_path = os.path.join(str(REPO_TEXTS_ROOT), folder_name)
        if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
            raise HTTPException(status_code=404, detail=f"文件夹不存在: {folder_name}")

        for root, _, files in os.walk(folder_path):
            for f in files:
                if f.lower().endswith(".json"):
                    meta_path = os.path.join(root, f)
                    with open(meta_path, "r", encoding="utf-8") as file:
                        data = json.load(file)
                        segments = data.get("segments", [])
                        for seg in segments:
                            all_texts.append(seg["text"])
                            all_segments.append(seg)

    if len(all_texts) == 0:
        raise HTTPException(status_code=400, detail="未找到有效的转写文本")

    # 提取文本特征
    features = extract_text_features(all_texts, model_sbert)

    # 构建索引路径
    index_path = os.path.join(str(INDICE_AUDIOS_ROOT), f"{index_name}.index")
    meta_path = os.path.join(str(INDICE_TEXTS_ROOT), f"{index_name}.json")

    # 构建并保存索引
    build_index(features, index_path)

    # 保存元数据（包含 audio_path / start / end / text）
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(all_segments, f, ensure_ascii=False, indent=2)

    return JSONResponse(
        {
            "message": "音频转写索引构建成功",
            "index_path": index_path,
            "segment_count": len(all_segments),
        }
    )


@app.post("/text_search_audios/")
async def search_text_to_audio(
    query: TextQuery,
    index_name: str = Query("global", description="索引名，不带 .index 后缀"),
    value: float = Query(5.0, description=">=1 表示 Top-K，0~1 表示相似度阈值"),
    return_audio: bool = Query(False, description="是否返回完整原始音频 base64 编码"),
    return_clip: bool = Query(False, description="是否返回截取的音频片段 base64 编码"),
):
    text = query.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本不能为空")

    # 提取文本特征
    query_feature = extract_text_features([text], model_sbert)
    if not isinstance(query_feature, np.ndarray):
        raise HTTPException(status_code=500, detail="特征提取失败")

    # 加载索引和 metadata
    index_file = f"{index_name}.index"
    index_path = os.path.join(str(INDEX_ROOT), "audios", index_file)
    index = load_index(index_path)
    if index is None:
        raise HTTPException(status_code=404, detail=f"索引文件不存在: {index_file}")

    meta_file = f"{index_name}.json"
    meta_path = os.path.join(str(INDEX_ROOT), "texts", meta_file)
    if not os.path.exists(meta_path):
        raise HTTPException(status_code=404, detail=f"meta 文件不存在: {meta_file}")
    with open(meta_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    # 检索
    D, I = None, None
    if value >= 1:
        k = int(value)
        D, I = index.search(query_feature, k)
    elif 0 < value < 1:
        # 先搜索全部
        D, I = index.search(query_feature, index.ntotal)
    else:
        raise HTTPException(status_code=400, detail="value 应为正数：>=1 表示topk，0~1 表示相似度阈值")

    # 组合结果 (idx, score)
    matched_pairs = [(idx, score) for idx, score in zip(I[0], D[0]) if idx != -1]
    matched_pairs.sort(key=lambda x: -x[1])  # 按相似度降序

    # 过滤阈值条件，并保证至少5条（如果是阈值模式）
    if value >= 1:
        filtered = matched_pairs[: int(value)]
    else:  # 0 < value < 1
        filtered = [p for p in matched_pairs if p[1] >= value]
        if len(filtered) < 5:
            filtered = matched_pairs[:5]

    matched = []
    for idx, score in filtered:
        seg = metadata[idx]

        audio_base64 = None
        clip_base64 = None
        if return_audio or return_clip:
            audio_path = seg["audio_path"].replace("\\", "/")
            try:
                audio = AudioSegment.from_file(audio_path)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"加载音频失败: {audio_path}, 错误: {e}")

            if return_audio:
                raw_bytes = audio.export(format="wav").read()
                audio_base64 = base64.b64encode(raw_bytes).decode("utf-8")

            if return_clip:
                start_ms = int(seg["start"] * 1000)
                end_ms = int(seg["end"] * 1000)
                clip = audio[start_ms:end_ms]
                clip_bytes = clip.export(format="wav").read()
                clip_base64 = base64.b64encode(clip_bytes).decode("utf-8")

        item = {
            "audio_path": seg["audio_path"],
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"],
            "score": float(score),
        }
        if return_audio:
            item["audio_base64"] = audio_base64
        if return_clip:
            item["clip_base64"] = clip_base64

        matched.append(item)

    return JSONResponse(
        {
            "message": "检索成功（模式: topk）" if value >= 1 else "检索成功（模式: score）",
            "matches": matched,
            "count": len(matched),
        }
    )


# ========================== 人脸 API 接口 ==========================
@app.post("/build_faces_index/")
async def build_faces_index(
    folder_names: List[str] = Query(..., description="要构建人脸索引的文件夹名列表，位于 repositories/images/ 下"),
    index_name: str = Query(..., description="索引文件名，不带后缀"),
):
    # 参数合法性校验
    for fn in folder_names:
        if ".." in fn or "/" in fn or "\\" in fn:
            raise HTTPException(status_code=400, detail=f"文件夹名不合法: {fn}")
    if ".." in index_name or "/" in index_name or "\\" in index_name:
        raise HTTPException(status_code=400, detail="索引文件名不合法")

    # 收集所有图片路径
    image_paths = []
    for folder_name in folder_names:
        folder_path = os.path.join(str(REPO_IMAGES_ROOT), folder_name)
        if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
            raise HTTPException(status_code=404, detail=f"文件夹不存在: {folder_name}")
        for root, _, files in os.walk(folder_path):
            for f in files:
                if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")):
                    image_paths.append(os.path.join(root, f))

    if not image_paths:
        raise HTTPException(status_code=400, detail="指定文件夹中无可用图片")

    # 提取所有人脸特征
    vectors = []
    valid_paths = []
    for img_path in image_paths:
        img = cv2.imread(img_path)
        if img is None:
            continue
        faces = face_model.get(img)
        if not faces:
            continue
        for face in faces:
            vectors.append(face.embedding)
            valid_paths.append(img_path)

    if not vectors:
        raise HTTPException(status_code=400, detail="没有检测到任何人脸，无法构建索引")

    # 构建索引前归一化
    features = np.array(vectors, dtype=np.float32)
    features = features / np.linalg.norm(features, axis=1, keepdims=True)

    # 确保索引和meta目录存在
    os.makedirs(INDICE_IMAGES_ROOT, exist_ok=True)
    os.makedirs(INDICE_META_ROOT, exist_ok=True)

    index_filename = f"{index_name}.index" if not index_name.endswith(".index") else index_name
    index_path = os.path.join(str(INDICE_IMAGES_ROOT), index_filename)
    build_index(features, index_path)

    # 保存 meta 信息
    meta = {
        "index_name": index_filename,
        "folder_names": folder_names,
        "image_count": len(valid_paths),
        "image_paths": valid_paths,
    }
    meta_path = os.path.join(str(INDICE_META_ROOT), f"{index_name}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return JSONResponse(
        {
            "message": "人脸索引构建成功",
            "index_path": index_path,
            "meta_path": meta_path,
            "image_count": len(valid_paths),
        }
    )


@app.post("/images_search_faces/")
async def search_faces(
    images: List[UploadFile] = File(...),
    index_name: str = Query("global", description="索引文件名，不带 .index 后缀，默认使用 global"),
    value: float = Query(5.0, description="如果 >=1 表示返回 topK 个结果，如果在 0-1 之间表示相似度阈值"),
    return_original: bool = Query(False, description="是否返回匹配图片的原图 base64 编码"),
    return_thumbnail: bool = Query(True, description="是否返回匹配图片的缩略图 base64 编码"),
):
    print(f"\n[{datetime.now()}] 收到图像检索请求：")
    print(f"Query 参数：index_name={index_name}, value={value}, return_original={return_original}, return_thumbnail={return_thumbnail}")
    print(f"共收到 {len(images)} 张图片：")
    for img_file in images:
        print(f" - 文件名: {img_file.filename}, Content-Type: {img_file.content_type}")

    valid_exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
    temp_paths = []

    for img_file in images:
        if not img_file.filename.lower().endswith(valid_exts):
            raise HTTPException(status_code=400, detail=f"{img_file.filename} 不是支持的图片格式")

        suffix = os.path.splitext(img_file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await img_file.read())
            temp_paths.append(tmp.name)

    if not temp_paths:
        raise HTTPException(status_code=400, detail="没有有效图片")

    # 加载索引
    index_file = f"{index_name}.index"
    index_path = os.path.join(str(INDICE_IMAGES_ROOT), index_file)
    index = load_index(index_path)
    if index is None:
        raise HTTPException(status_code=404, detail=f"索引文件不存在: {index_file}")

    image_paths = load_image_paths_from_meta(index_name)
    if len(image_paths) != index.ntotal:
        raise HTTPException(status_code=500, detail="索引条目数量与图像数量不一致，请重新构建索引")

    all_scores = {}  # {idx: [score1, score2, ...]}

    # 遍历上传的图片并提取所有人脸
    for path in temp_paths:
        img = cv2.imread(path)
        if img is None:
            continue
        faces = face_model.get(img)
        if not faces:
            continue

        for face in faces:
            emb = face.embedding.astype("float32")
            emb = emb / np.linalg.norm(emb)
            query_feature = np.expand_dims(emb, axis=0)

            D, I = index.search(query_feature, len(image_paths))
            for idx, dist in zip(I[0], D[0]):
                if idx == -1:
                    continue
                if idx not in all_scores:
                    all_scores[idx] = []
                all_scores[idx].append(dist)

    # 删除临时文件
    for path in temp_paths:
        os.remove(path)

    if not all_scores:
        raise HTTPException(status_code=404, detail="未检测到人脸或没有匹配结果")

    # 平均相似度
    averaged = [(idx, max(scores)) for idx, scores in all_scores.items()]
    averaged.sort(key=lambda x: x[1], reverse=True)

    # 去重：按路径唯一性筛选
    seen_paths = set()
    unique_items = []
    for idx, score in averaged:
        path_rel = os.path.relpath(image_paths[idx], str(REPO_IMAGES_ROOT))
        if path_rel in seen_paths:
            continue
        seen_paths.add(path_rel)
        unique_items.append((idx, score))

    # 选择 Top-K 或 相似度阈值
    if value >= 1:
        filtered = unique_items[: int(value)]
    elif 0 < value < 1:
        filtered = [item for item in unique_items if item[1] >= value]
        if len(filtered) < 5:
            filtered = unique_items[:5]
    else:
        raise HTTPException(status_code=400, detail="value 应为正数：>=1 表示topk，0~1 表示相似度阈值")

    # 构建返回结果
    matched = []
    for idx, score in filtered:
        path_rel = os.path.relpath(image_paths[idx], str(REPO_IMAGES_ROOT))
        item = {"path": path_rel, "score": float(score)}

        abs_path = os.path.join(str(REPO_IMAGES_ROOT), path_rel)
        if return_original or return_thumbnail:
            try:
                with Image.open(abs_path) as img:
                    if return_original:
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG")
                        item["original_base64"] = base64.b64encode(buf.getvalue()).decode("utf-8")
                    if return_thumbnail:
                        img_thumb = img.copy()
                        img_thumb.thumbnail((128, 128))
                        buf_thumb = io.BytesIO()
                        img_thumb.save(buf_thumb, format="JPEG")
                        item["thumbnail_base64"] = base64.b64encode(buf_thumb.getvalue()).decode("utf-8")
            except Exception as e:
                item["error"] = f"无法处理图像: {e}"

        matched.append(item)

    return JSONResponse(
        {
            "message": "检索成功（模式: topk）" if value >= 1 else "检索成功（模式: score）",
            "matched_images": matched,
            "count": len(matched),
        }
    )


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=config.PORT, reload=False)

"""document_compare 服务：合同/文档比对。

基于 RapidOCR + PaddleOCR 印章识别，对两份 PDF 做文本差异比对，
并在 PDF 上按词标注删除/新增/修改内容，输出可下载的比对结果 PDF。
"""
import os
import time
import uuid
import logging
from difflib import SequenceMatcher
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from rapidocr import ModelType, OCRVersion, RapidOCR
from paddleocr import SealRecognition
import Levenshtein as Lev
import uvicorn

import config
import cleanup  # 定时清理（uploads/compare_results/tmp_imgs）
from config import TMP_DIR, UPLOAD_DIR, OUTPUT_DIR, PORT
from utils import draw_boxes_on_pdf_word, rapidocr_util


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
logger.propagate = False


# 数据模型
class CompareRequest(BaseModel):
    benchmark_file: str
    compare_file: str
    use_seal: bool
    header_h: int = 0  # 页眉高度
    footer_h: int = 0  # 页脚高度


# 全局 OCR / 印章识别实例（在 lifespan 中初始化）
ocr = None
sealRecognition = None

# 定时清理后台任务句柄（lifespan 中创建/取消）
_cleanup_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ocr, sealRecognition, _cleanup_task

    TMP_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    ocr = RapidOCR(
        params={
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Det.model_type ": ModelType.SERVER,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.SERVER,
            "Cls.model_type": ModelType.SERVER,
        }
    )

    sealRecognition = SealRecognition(
        use_doc_orientation_classify=True,
        use_doc_unwarping=False,
        use_layout_detection=True,
        text_recognition_model_name="PP-OCRv4_server_rec_doc",
        seal_det_unclip_ratio=0.8,
    )

    app.mount("/static", StaticFiles(directory=str(OUTPUT_DIR)), name="static")

    # 启动定时清理任务（uploads/compare_results/tmp_imgs）
    _cleanup_task = await cleanup.start()
    yield
    # 关闭定时清理任务
    await cleanup.stop(_cleanup_task)
    _cleanup_task = None


app = FastAPI(title="合同比对接口", lifespan=lifespan)

# 跨域资源共享
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def read_root():
    return {"message": "欢迎使用sv"}


@app.post("/upload", summary="上传单个文件, 当前仅支持PDF文件")
async def doc_upload(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件不能为空")

    if Path(file.filename).suffix != ".pdf":
        raise HTTPException(status_code=400, detail="不支持的文件类型, 只支持PDF文件")

    new_name = generate_filename(file.filename)
    dest_path = UPLOAD_DIR / new_name

    try:
        with dest_path.open("wb") as buffer:
            while chunk := await file.read(1024 * 1024):  # 每次 1 MB
                buffer.write(chunk)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"写入文件失败：{exc}")

    return JSONResponse(
        {
            "status_code": status.HTTP_200_OK,
            "message": "上传成功",
            "saved_name": new_name,
        }
    )


@app.post("/compare", summary="开始比对")
async def compare(request: CompareRequest):
    benchmark_file_path = f"{UPLOAD_DIR}/{request.benchmark_file}"
    compare_file_path = f"{UPLOAD_DIR}/{request.compare_file}"

    # 比对函数
    (boxes_of_file1, boxes_of_file2, seal_boxes_of_file1, seal_boxes_of_file2,
     similarity) = compare_file(
        ocr=ocr,
        file_path1=benchmark_file_path,
        file_path2=compare_file_path,
        use_seal=request.use_seal,
        sealRecognition=sealRecognition,
        header_h=request.header_h,
        footer_h=request.footer_h,
    )

    # 将文本框的两点坐标形式转换成4点坐标形式
    seal_boxes_of_file1 = expand_two_points_to_four(seal_boxes_of_file1)
    seal_boxes_of_file2 = expand_two_points_to_four(seal_boxes_of_file2)
    boxes_of_file1.extend(seal_boxes_of_file1)
    boxes_of_file2.extend(seal_boxes_of_file2)

    unique_str = uuid.uuid4().hex
    ts = str(int(time.time()))
    benchmark_file_name = f"benchmark_{ts}_{unique_str}.pdf"
    compare_file_name = f"compare_{ts}_{unique_str}.pdf"

    # 绘制文本框
    draw_boxes_on_pdf_word(
        pdf_path=benchmark_file_path,
        boxes=boxes_of_file1,
        output_path=f"{OUTPUT_DIR}/{benchmark_file_name}",
        TMP_DIR=str(TMP_DIR),
    )
    draw_boxes_on_pdf_word(
        pdf_path=compare_file_path,
        boxes=boxes_of_file2,
        output_path=f"{OUTPUT_DIR}/{compare_file_name}",
        TMP_DIR=str(TMP_DIR),
    )
    return {
        "benchmark_file": benchmark_file_name,
        "compare_file": compare_file_name,
        "similarity": similarity,
    }


@app.get("/download", summary="下载文件")
async def download_file(filename: str, request: Request):
    # 验证文件路径
    file_path = f"{OUTPUT_DIR}/{filename}"

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="文件不存在或已过期（可能已被定时清理），请重新上传后再试")

    base_url = str(request.base_url).rstrip("/")
    return {"url": f"{base_url}/static/{filename}"}


@app.get("/get_file", summary="直接返回文件")
async def get_file(filename: str):
    file_path = os.path.join(str(OUTPUT_DIR), filename)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="文件不存在或已过期（可能已被定时清理），请重新上传后再试")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


def generate_filename(original_filename: str) -> str:
    """
    重命名函数
    例： 时间戳_32位随机字符串.pdf
    """
    ext = Path(original_filename).suffix  # 保留原始扩展名
    unique_str = uuid.uuid4().hex  # 32 位随机字符串
    ts = str(int(time.time()))  # 当前时间戳
    return f"{ts}_{unique_str}{ext}"


def tokenize_with_spans(s: str):
    """
    将字符串分成 tokens，并返回 tokens 列表和每个 token 对应的字符区间 spans。
    目前策略：连续数字归为一个 token，其它字符单字符为一个 token。
    返回: tokens, spans  其中 spans[i] = (start_char_index, end_char_index)
    """
    tokens = []
    spans = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch.isdigit():
            j = i + 1
            while j < n and s[j].isdigit():
                j += 1
            tokens.append(s[i:j])
            spans.append((i, j))
            i = j
        else:
            # 单字符 token（你也可以把连续字母当作一个 token，按需修改）
            tokens.append(ch)
            spans.append((i, i + 1))
            i += 1
    return tokens, spans


def iter_char_ranges_from_tokens(spans, i, j):
    """
    把 token 索引区间 [i,j) 拆成字符级区间。
    返回: 生成器，逐个产出 (char_start, char_end) 的半开区间
    """
    if i >= j:
        if i < len(spans):
            pos = spans[i][0]
            yield (pos, pos)
        elif spans:
            pos = spans[-1][1]
            yield (pos, pos)
        else:
            yield (0, 0)
        return

    # 逐字符遍历
    for idx in range(i, j):
        start, end = spans[idx]
        for k in range(start, end):
            yield (k, k + 1)


# 建立映射表
def _build_whitespace_map(text: str):
    """
    返回两个列表：
        stripped_text  : 去掉所有空白后的字符串
        idx_map        : idx_map[i] == stripped_text 中第 i 个字符在原 text 中的下标
    """
    idx_map = []
    stripped_chars = []
    for i, ch in enumerate(text):
        if not ch.isspace():  # 跳过所有空白字符
            stripped_chars.append(ch)
            idx_map.append(i)
    return "".join(stripped_chars), idx_map


# 把无空白区间映射回原始区间
def _map_range_to_original(idx_map, start_stripped, end_stripped):
    """
    把 [start_stripped, end_stripped) 映射回原始文本的字符区间
    """
    if start_stripped == end_stripped:  # 空区间
        if start_stripped < len(idx_map):
            pos = idx_map[start_stripped]  # 尽量靠近左侧
        else:
            pos = idx_map[-1] + 1 if idx_map else 0
        return pos, pos
    start_orig = idx_map[start_stripped]
    end_orig = idx_map[end_stripped - 1] + 1  # 半开区间
    return start_orig, end_orig


def text_compare(a: str, b: str):
    # 建立无空白副本 + 索引映射
    a_strip, a_map = _build_whitespace_map(a)
    b_strip, b_map = _build_whitespace_map(b)

    # token 化（在无空白副本上）
    tokens_a, spans_a = tokenize_with_spans(a_strip)
    tokens_b, spans_b = tokenize_with_spans(b_strip)

    # token 级比对
    sm = SequenceMatcher(None, tokens_a, tokens_b)
    token_sim = sm.ratio()

    # 字符级相似度
    char_sim = Lev.ratio(a_strip, b_strip)

    # 组装结果
    changes = []
    for tag, ai, aj, bi, bj in sm.get_opcodes():
        # 左侧字符级区间列表
        a_ranges = list(iter_char_ranges_from_tokens(spans_a, ai, aj))
        # 右侧字符级区间列表
        b_ranges = list(iter_char_ranges_from_tokens(spans_b, bi, bj))

        # 下面把字符级区间映射回原始坐标并生成变更记录
        # 为了简单，这里把相同 tag 的连续字符区间合并成一条记录
        # （如果希望每字符一条记录，可继续细化）
        if not a_ranges:
            a_ranges = [(0, 0)]
        if not b_ranges:
            b_ranges = [(0, 0)]

        a_start_strip, a_end_strip = a_ranges[0][0], a_ranges[-1][1]
        b_start_strip, b_end_strip = b_ranges[0][0], b_ranges[-1][1]

        a_start_orig, a_end_orig = _map_range_to_original(a_map, a_start_strip, a_end_strip)
        b_start_orig, b_end_orig = _map_range_to_original(b_map, b_start_strip, b_end_strip)

        # 组装结果
        if tag == "equal":
            changes.append(("equal", a_start_orig, a_end_orig, b_start_orig, b_end_orig, ""))
        elif tag == "replace":
            changes.append(("replace", a_start_orig, a_end_orig, b_start_orig, b_end_orig,
                            f'"{a[a_start_orig:a_end_orig]}" -> "{b[b_start_orig:b_end_orig]}"'))
        elif tag == "delete":
            changes.append(("delete", a_start_orig, a_end_orig, b_start_orig, b_end_orig,
                            f'删除 "{a[a_start_orig:a_end_orig]}"'))
        elif tag == "insert":
            changes.append(("insert", a_start_orig, b_end_orig, b_start_orig, b_end_orig,
                            f'插入 "{b[b_start_orig:b_end_orig]}"'))
    return token_sim, char_sim, changes


def to_halfwidth(s: str) -> str:
    """
    将常见全角字符转换为半角：
    - 全角空格 U+3000 -> 普通空格
    - 全角 ASCII（U+FF01 ~ U+FF5E） -> 半角对应字符
    """
    out_chars = []
    for ch in s:
        code = ord(ch)
        if code == 0x3000:  # 全角空格
            out_chars.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:  # 全角 ASCII 标点/字母/数字
            out_chars.append(chr(code - 0xFEE0))
        else:
            out_chars.append(ch)
    return "".join(out_chars)


def expand_two_points_to_four(data):
    """
    将两点坐标扩展为4点坐标的形式
    Args:
        data: 两点坐标数据

    Returns:
        4点坐标数据
    """
    if not data or len(data) == 0:
        return []

    res = []
    for item in data:
        # 提取原始数据
        operation = item[0]
        index = item[1][0]  # 0
        coords = item[1][1]  # [x1, y1, x2, y2]

        # 提取左上角和右下角坐标
        x1, y1, x2, y2 = coords

        # 计算4个点的坐标
        # 按照顺时针方向：左上 -> 右上 -> 右下 -> 左下
        top_left = [int(round(x1)), int(round(y1))]
        top_right = [int(round(x2)), int(round(y1))]
        bottom_right = [int(round(x2)), int(round(y2))]
        bottom_left = [int(round(x1)), int(round(y2))]

        # 构建4点坐标
        four_points = [top_left, top_right, bottom_right, bottom_left]
        temp = [operation, [index, four_points]]
        res.append(temp)

    return res


def compare_file(ocr: RapidOCR, file_path1: str, file_path2: str, use_seal: bool,
                 sealRecognition: SealRecognition, header_h: int = 0, footer_h: int = 0):
    logger.info("OCR识别中...")
    text1, words_to_boxes_map1, seal_texts1, seal_boxes1 = rapidocr_util(
        ocr=ocr, file_path=file_path1, header_h=header_h, footer_h=footer_h,
        use_seal=use_seal, sealRecognition=sealRecognition, TMP_DIR=str(TMP_DIR),
    )
    text2, words_to_boxes_map2, seal_texts2, seal_boxes2 = rapidocr_util(
        ocr=ocr, file_path=file_path2, header_h=header_h, footer_h=footer_h,
        use_seal=use_seal, sealRecognition=sealRecognition, TMP_DIR=str(TMP_DIR),
    )

    logger.info("开始进行文档比对...")

    # 统一全角/半角（这里把全角转换为半角）
    text1 = to_halfwidth(text1)
    text2 = to_halfwidth(text2)

    token_similarity, char_similarity, diffs = text_compare(text1, text2)
    _, _, diffs_seal = text_compare(seal_texts1, seal_texts2)
    print(f"相似度: {char_similarity:.4f}")

    boxes_of_file1 = []
    boxes_of_file2 = []
    seal_boxes_of_file1 = []
    seal_boxes_of_file2 = []
    for op, as1, as2, bs1, bs2, txt in diffs:
        if op != "equal":
            print(f"{op}  原文件[{as1}:{as2}]  新文件[{bs1}:{bs2}]  {txt}")
        if op == "delete":
            for item in words_to_boxes_map1[as1:as2]:
                boxes_of_file1.append(["delete", item])
        if op == "replace":
            for item in words_to_boxes_map1[as1:as2]:
                boxes_of_file1.append(["replace", item])
            for item in words_to_boxes_map2[bs1:bs2]:
                boxes_of_file2.append(["replace", item])
        if op == "insert":
            for item in words_to_boxes_map2[bs1:bs2]:
                boxes_of_file2.append(["insert", item])

    for op, as1, as2, bs1, bs2, txt in diffs_seal:
        if op != "equal":
            print(f"{op}  原文件[{as1}:{as2}]  新文件[{bs1}:{bs2}]  {txt}")
        if op == "delete":
            for item in seal_boxes1[as1:as2]:
                seal_boxes_of_file1.append(["delete", item])
        if op == "replace":
            for item in seal_boxes1[as1:as2]:
                seal_boxes_of_file1.append(["replace", item])
            for item in seal_boxes2[bs1:bs2]:
                seal_boxes_of_file2.append(["replace", item])
        if op == "insert":
            for item in seal_boxes2[bs1:bs2]:
                seal_boxes_of_file2.append(["insert", item])
    return boxes_of_file1, boxes_of_file2, seal_boxes_of_file1, seal_boxes_of_file2, char_similarity


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_level="info")

import os
from pathlib import Path

import cv2
import fitz
import numpy as np
from PIL import Image
from rapidocr import RapidOCR
from paddleocr import SealRecognition


def rapidocr_util(ocr: RapidOCR, file_path: str, header_h: int, footer_h: int, TMP_DIR: str,
                  use_seal: bool = False, sealRecognition: SealRecognition = None):
    doc = fitz.open(file_path)

    content = ""
    words_to_boxes_map = []
    file_name = Path(file_path).stem
    seal_texts = ""
    seal_boxes = []
    for page_index in range(len(doc)):
        page = doc[page_index]

        r = page.rect
        page.draw_rect(fitz.Rect(r.x0, r.y0, r.x1, r.y0 + header_h), color=None, fill=(1, 1, 1), overlay=True)
        page.draw_rect(fitz.Rect(r.x0, r.y1 - footer_h, r.x1, r.y1), color=None, fill=(1, 1, 1), overlay=True)

        # 页面 -> 图片
        mat = fitz.Matrix(2, 2)  # 2x 分辨率
        pix = page.get_pixmap(matrix=mat)
        img_path = os.path.join(TMP_DIR, f"{file_name}_page_{page_index}.jpg")
        pix.save(img_path)

        # OCR 识别
        img_np = np.array(Image.open(img_path))
        seal_texts_temp, seal_boxes_temp = get_seal(
            sealRecognition=sealRecognition, img_np=img_np, page_index=page_index
        )
        if use_seal:
            seal_texts += seal_texts_temp
            seal_boxes.extend(seal_boxes_temp)

        cur_page_seal_boxes = [
            box for p_idx, box in seal_boxes_temp if p_idx == page_index
        ]
        for (x1, y1, x2, y2) in cur_page_seal_boxes:
            # 转成 int，再画
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            cv2.rectangle(img_np, (x1, y1), (x2, y2), (255, 255, 255), -1)

        result = ocr(img_np, use_det=True, use_cls=True, use_rec=True,
                     return_word_box=True, return_single_char_box=True)

        word_results = result.word_results
        for words in word_results:
            for word in words:
                content += word[0]
                words_to_boxes_map.append([page_index, word[2]])
        os.remove(img_path)
    return content, words_to_boxes_map, seal_texts, seal_boxes


def get_seal(sealRecognition: SealRecognition, img_np: np.ndarray, page_index: int):
    output = sealRecognition.predict(img_np)[0]
    res_json = output.json
    res = res_json["res"]

    boxes = res["layout_det_res"]["boxes"]

    seal_boxes_temp = []
    seal_texts_list = []
    seal_texts = ""
    seal_boxes = []
    for box in boxes:
        if box["label"] == "seal":
            seal_boxes_temp.append([[page_index, box["coordinate"]]])

    for seal_rec_texts in res["seal_res_list"]:
        seal_texts_list.append(seal_rec_texts["rec_texts"][0])

    for i in range(len(seal_texts_list)):
        text = seal_texts_list[i]
        seal_texts += text
        seal_box = seal_boxes_temp[i]
        seal_boxes.extend(seal_box * len(text))

    return seal_texts, seal_boxes

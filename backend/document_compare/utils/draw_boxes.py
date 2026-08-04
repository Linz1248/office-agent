import os
from collections import defaultdict

import fitz  # PyMuPDF
from PIL import Image, ImageDraw


def draw_boxes_on_pdf_word(pdf_path: str, output_path: str, boxes: list, TMP_DIR: str = "./tmp_imgs",
                           mat_scale: float = 2.0, opacity=0.5):
    """
    在 PDF 上按词绘制差异框。
    boxes: 列表，每项 [diff_type, [page_index, quad_img]]
        quad_img: 4 个点的列表 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        坐标假设与页面渲染到 pixmap 时的像素坐标系一致（mat = Matrix(mat_scale, mat_scale)）。
    mat_scale: 渲染 pixmap 时的缩放
    opacity: 0.0 ~ 1.0 的透明度
    """
    os.makedirs(TMP_DIR, exist_ok=True)
    doc = fitz.open(pdf_path)

    color_dict = {
        "delete": (255, 0, 0),    # 红色
        "insert": (0, 255, 0),    # 绿色
        "replace": (255, 255, 0),  # 黄色
    }

    # 按页收集 boxes
    page_boxes = defaultdict(list)
    for box in boxes:
        diff_type = box[0]
        page_idx = int(box[1][0])
        page_boxes[page_idx].append([diff_type, box[1][1]])

    for page_idx, quad_list in page_boxes.items():
        page = doc[page_idx]

        # 渲染页面得到 pixmap（用于得到正确的像素尺寸）
        mat = fitz.Matrix(mat_scale, mat_scale)
        pix = page.get_pixmap(matrix=mat)
        img_w, img_h = pix.width, pix.height

        # 在同样像素尺寸下创建透明 overlay
        overlay = Image.new("RGBA", (img_w, img_h), (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)

        # 计算 0~255 的 alpha 值
        alpha = int(max(0.0, min(1.0, opacity)) * 255)

        # 画每个多边形（4 点）
        for quad in quad_list:
            rgb = color_dict[quad[0]]
            fill = (rgb[0], rgb[1], rgb[2], alpha)

            pts = [(int(p[0]), int(p[1])) for p in quad[1]]
            draw.polygon(pts, fill=fill)

        # 保存 overlay PNG（包含 alpha）
        overlay_path = os.path.join(TMP_DIR, f"overlay_page_{page_idx}.png")
        overlay.save(overlay_path, format="PNG")

        # 将 overlay PNG 插入回 PDF 页面（缩放到 page.rect），overlay=True 表示在上层绘制
        page.insert_image(page.rect, filename=overlay_path, overlay=True)

        os.remove(overlay_path)

    doc.save(output_path)
    doc.close()

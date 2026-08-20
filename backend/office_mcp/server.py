"""Office MCP Server：将办公功能封装为 MCP 工具供 Agent 调用。

工具列表：
  - read_document           : 读取已上传文档（PDF/Word/Excel）的全文文本
  - read_image              : 识别已上传图片中的文字（OCR）
  - extract_document        : 从 PDF 中抽取指定字段
  - extract_to_excel        : 从已上传文档提取字段生成 Excel 下载链接
  - compare_documents       : 比对两份 PDF 文档
  - list_image_libraries    : 列出图像库索引
  - search_images_by_text   : 通过文字搜索图片
  - search_images_by_image  : 通过图片搜索相似图片（以图搜图）
  - list_audio_libraries    : 列出音频库索引
  - search_audios_by_text   : 通过文字搜索音频

通过 streamable-http 传输协议运行，AgentScope 通过 HttpStatelessClient 连接。
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from config import (
    DOC_COMPARE_URL,
    DOC_EXTRACT_URL,
    MULTIMODEL_URL,
    PUBLIC_MULTIMODEL_BASE,
    HTTP_TIMEOUT,
    PORT,
    SERVICE_ACCOUNT_PASSWORD,
    SERVICE_ACCOUNT_USERNAME,
)

mcp = FastMCP("office-tools", host="0.0.0.0", port=PORT)

# ── HTTP 客户端 ────────────────────────────────────────────────

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(HTTP_TIMEOUT, connect=10.0))
    return _client


# ── document_extract 认证 ─────────────────────────────────────

_cached_token: str | None = None
_token_expires: float = 0.0


async def _get_extract_token() -> str:
    """登录 document_extract 服务获取 JWT token，带缓存。"""
    global _cached_token, _token_expires
    if _cached_token and time.time() < _token_expires - 60:
        return _cached_token

    client = _get_client()
    resp = await client.post(
        f"{DOC_EXTRACT_URL}/login",
        json={
            "username": SERVICE_ACCOUNT_USERNAME,
            "password": SERVICE_ACCOUNT_PASSWORD,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    _cached_token = data["access_token"]
    _token_expires = time.time() + data.get("expiresIn", 259200000) / 1000
    return _cached_token


async def _extract_post(
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    files: dict[str, Any] | None = None,
) -> dict:
    """向 document_extract 发 POST（json 或 multipart 文件），自动处理 401 token 过期重试。"""
    global _cached_token, _token_expires
    client = _get_client()
    token = await _get_extract_token()
    url = f"{DOC_EXTRACT_URL}{path}"

    async def _send(tok: str):
        headers = {"Authorization": f"Bearer {tok}"}
        if files is not None:
            return await client.post(url, files=files, headers=headers)
        return await client.post(url, json=payload, headers=headers)

    resp = await _send(token)
    if resp.status_code == 401:
        _cached_token = None
        _token_expires = 0.0
        token = await _get_extract_token()
        resp = await _send(token)
    resp.raise_for_status()
    return resp.json()


# ── 辅助函数 ──────────────────────────────────────────────────


def _truncate(text: str, max_len: int = 2000) -> str:
    """截断过长文本，避免超出 LLM 上下文限制。"""
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"\n...(已截断，共 {len(text)} 字符)"


def _handle_error(e: Exception, service: str) -> str:
    """将 HTTP 异常转换为用户友好的错误提示。

    透传下游 HTTPException 的 detail（如「文件不存在或已过期，请重新上传」），
    使 agent 能据此引导用户重新上传，而非仅看到无信息的状态码。
    """
    if isinstance(e, httpx.ConnectError):
        return f"{service}服务不可达，请确认该服务已启动"
    if isinstance(e, httpx.TimeoutException):
        return f"{service}服务响应超时，请稍后重试"
    if isinstance(e, httpx.HTTPStatusError):
        detail = None
        try:
            body = e.response.json()
            if isinstance(body, dict):
                detail = body.get("detail") or body.get("message")
        except Exception:
            pass
        if not detail:
            try:
                detail = (e.response.text or "").strip()[:200] or None
            except Exception:
                detail = None
        base = f"{service}服务返回错误 ({e.response.status_code})"
        return f"{base}：{detail}" if detail else base
    return f"{service}服务请求失败: {e}"


# ── 文档抽取工具 ──────────────────────────────────────────────


@mcp.tool()
async def read_document(filename: str) -> str:
    """读取已上传文档的全文文本（PDF/Word/Excel，按扩展名解析）。

    PDF 走 OCR；Word(.docx)/Excel(.xlsx) 走结构化解析；旧版 .doc/.xls 经
    LibreOffice 转换后解析。Excel 按工作表输出 Markdown 表格。
    适用于用户对上传文档提出一般性请求：解释、总结、问答、翻译、提取要点等。
    调用后由你基于全文直接作答，无需其它工具。
    需要结构化抽取特定字段时改用 extract_document（仅 PDF）；需要比对两份文档时改用 compare_documents（仅 PDF）。
    超长文本会被框架自动截断并卸载，必要时可按需回查。

    Args:
        filename: 已上传的文档文件名（extract_filename），如 "9f2e1c4f..._1719469876.pdf" / ".docx" / ".xlsx"。

    Returns:
        str: 文档全文文本。
    """
    try:
        result = await _extract_post("/doc_text", {"filename": filename})
    except Exception as e:
        return _handle_error(e, "文档读取")
    return result.get("text", "")


@mcp.tool()
async def read_image(file_path: str) -> str:
    """识别已上传图片中的文字（OCR），返回 Markdown 文本。

    适用于用户上传图片后要求「识别/提取图片里的文字、把图转文字、看图里写了什么」等。
    调用后由你基于识别出的文本直接作答。需要「以图搜图」改用 search_images_by_image；
    需要读取文档（PDF/Word/Excel）全文改用 read_document。

    Args:
        file_path: 已上传的图片文件路径，由文件上传功能返回。

    Returns:
        str: 图片中识别出的文本（Markdown）。
    """
    from pathlib import Path
    import mimetypes

    path = Path(file_path)
    if not path.exists():
        return f"图片文件不存在或已过期（可能已被定时清理），请重新上传该图片后再试。"

    media_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    content = path.read_bytes()
    try:
        result = await _extract_post(
            "/image_text", files={"file": (path.name, content, media_type)}
        )
    except Exception as e:
        return _handle_error(e, "图片识别")
    return result.get("text", "")


@mcp.tool()
async def extract_document(
    filename: str,
    fields: list[str],
    enhance: bool = False,
    fields_enhance: list[str] | None = None,
    fields_template: dict[str, str] | None = None,
) -> str:
    """从 PDF/图片 文档中抽取指定的字段信息。

    仅在用户明确要求提取特定字段时调用此工具，不要用于一般性的文件解释。
    调用前需确认用户要提取哪些字段（fields 参数不可为空）。

    Args:
        filename: 已上传的 PDF/图片 文件名（extract_filename），如 "9f2e1c4f..._1719469876.pdf"。
        fields: 需要抽取的字段名称列表，如 ["合同名称", "签订日期", "甲方", "乙方"]。
        enhance: 是否启用增强抽取模式（使用示例样本提升准确率，默认 False）。
        fields_enhance: 需要增强抽取的字段名列表（仅 enhance=True 时有效）。
        fields_template: 字段示例样本，key 为字段名，value 为示例值（仅 enhance=True 时有效）。

    Returns:
        str: 抽取结果（JSON 格式），包含每个字段的提取值。
    """
    payload: dict[str, Any] = {
        "filename": filename,
        "fields": fields,
        "enhance": enhance,
        "fields_enhance": fields_enhance or [],
        "fields_template": fields_template or {},
    }
    try:
        result = await _extract_post("/doc_extract", payload)
    except Exception as e:
        return _handle_error(e, "文档抽取")
    return _truncate(json.dumps(result, ensure_ascii=False, indent=2))


@mcp.tool()
async def extract_to_excel(
    filename: str,
    fields: list[str] | None = None,
    template_filename: str | None = None,
    enhance: bool = False,
    fields_enhance: list[str] | None = None,
    fields_template: dict[str, str] | None = None,
) -> str:
    """从已上传的目标文档中提取指定字段，生成 Excel 供下载。

    - 传 fields（字段名列表）→ 生成默认「字段 | 值」Excel；
    - 传 template_filename（已上传的 Excel 模板）→ 按模板「字段名 + 右侧空单元格」
      自动识别字段，把提取值填入对应右侧位置后下载。
    两者至少传一个；filename 始终为目标文档（PDF/Word/Excel/图片）的 extract_filename。

    适用场景：用户明确要求「把文档里的字段提取出来并输出/下载成 Excel/表格」时调用。
    用户上传了 Excel 模板时，用该模板的 extract_filename 作为 template_filename。
    未上传目标文档时，先提示用户上传。

    Args:
        filename: 目标文档的 extract_filename（如 "9f2e..._1719469876.pdf"）。
        fields: 要提取的字段名列表（生成默认表时必填）。
        template_filename: 已上传 Excel 模板的 extract_filename（填充模板模式时必填）。
        enhance / fields_enhance / fields_template: 同 extract_document 的增强抽取参数。

    Returns:
        str: 下载链接 + 各字段提取结果摘要（agent 据此整理为 markdown 下载链接呈现）。
    """
    common = {
        "enhance": enhance,
        "fields_enhance": fields_enhance or [],
        "fields_template": fields_template or {},
    }
    try:
        if template_filename:
            r = await _extract_post("/fill_template", {
                "filename": filename,
                "template_filename": template_filename,
                **common,
            })
        elif fields:
            r = await _extract_post("/extract_to_excel", {
                "filename": filename,
                "fields": fields,
                **common,
            })
        else:
            return "参数错误：需提供 fields（字段列表）或 template_filename（Excel 模板）。"
    except Exception as e:
        return _handle_error(e, "字段提取→Excel")

    url = r.get("download_url", "")
    results = r.get("results", {}) or {}
    summary = "\n".join(f"- {k}: {v}" for k, v in results.items())
    if len(summary) > 1500:
        summary = summary[:1500] + "\n…"
    return f"下载链接：{url}\n\n提取结果：\n{summary}"


# ── 文档比对工具 ──────────────────────────────────────────────


@mcp.tool()
async def compare_documents(
    benchmark_file: str,
    compare_file: str,
    use_seal: bool = True,
    header_h: int = 0,
    footer_h: int = 0,
) -> str:
    """比对两份 PDF 文档的差异，包括文本差异和印章差异。

    仅在用户明确要求比对两份文档时调用，需要两个已上传的文件。

    Args:
        benchmark_file: 基准文件名（compare_filename），即原始版本。
        compare_file: 待比对文件名（compare_filename），即新版本。
        use_seal: 是否进行印章比对（默认 True）。
        header_h: 页眉高度（像素），页眉区域不参与比对（默认 0）。
        footer_h: 页脚高度（像素），页脚区域不参与比对（默认 0）。

    Returns:
        str: 比对结果，包含相似度分数和结果文件信息。
    """
    client = _get_client()
    payload = {
        "benchmark_file": benchmark_file,
        "compare_file": compare_file,
        "use_seal": use_seal,
        "header_h": header_h,
        "footer_h": footer_h,
    }
    try:
        resp = await client.post(f"{DOC_COMPARE_URL}/compare", json=payload)
        resp.raise_for_status()
        result = resp.json()
    except Exception as e:
        return _handle_error(e, "文档比对")

    return (
        f"文档比对完成！\n"
        f"相似度: {result.get('similarity', 'N/A')}\n"
        f"基准文件结果: {result.get('benchmark_file', 'N/A')}\n"
        f"比对文件结果: {result.get('compare_file', 'N/A')}\n"
        f"可通过文档比对页面查看标注后的差异详情。"
    )


# ── 图像检索工具 ──────────────────────────────────────────────


@mcp.tool()
async def list_image_libraries() -> str:
    """列出所有可用的图像库文件夹和索引。

    Returns:
        str: 图像库目录结构，包含文件夹和索引名称列表。
    """
    client = _get_client()
    try:
        resp = await client.get(
            f"{MULTIMODEL_URL}/get_images_dir/", params={"include_files": "true"}
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as e:
        return _handle_error(e, "图像检索")

    repos = result.get("repositories", [])
    indices = result.get("indices", [])
    repo_names = [r.get("name", "") for r in repos]
    index_names = [i.get("name", "").replace(".index", "") for i in indices]

    return (
        f"图像库概况：\n"
        f"  文件夹 ({len(repo_names)}): {', '.join(repo_names) if repo_names else '无'}\n"
        f"  索引 ({len(index_names)}): {', '.join(index_names) if index_names else '无'}\n"
        f"可用 index_name 参数值: {index_names if index_names else ['global']}"
    )


@mcp.tool()
async def search_images_by_text(
    query: str,
    index_name: str = "global",
    top_k: int = 5,
) -> str:
    """通过文字描述搜索相似的图片。

    仅在用户明确要求搜索图片时调用。

    Args:
        query: 搜索文本描述，如 "警车" 或 "起重机"。
        index_name: 索引名称（不带 .index 后缀），可通过 list_image_libraries 查看。默认 "global"。
        top_k: 返回结果数量（默认 5）。

    Returns:
        str: JSON 字符串 {"summary", "items"}，items 含 thumb_url/url/score，
             前端会自动渲染为图片画廊，无需复述文件路径。
    """
    client = _get_client()
    try:
        resp = await client.post(
            f"{MULTIMODEL_URL}/text_search_images/",
            params={
                "index_name": index_name,
                "value": top_k,
                "return_thumbnail": False,
                "return_original": False,
            },
            json={"text": query},
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as e:
        return _handle_error(e, "图像检索")

    results = result.get("results", [])
    if not results:
        return f"未找到与 '{query}' 匹配的图片。"

    items = [
        {
            "kind": "image",
            "path": item.get("path", ""),
            "thumb_url": f"{PUBLIC_MULTIMODEL_BASE}/thumbnails/{item.get('path', '')}",
            "url": f"{PUBLIC_MULTIMODEL_BASE}/images/{item.get('path', '')}",
            "score": round(float(item.get("score", 0)), 4),
        }
        for item in results
    ]
    return json.dumps(
        {"summary": f"找到 {len(items)} 张匹配图片。", "items": items},
        ensure_ascii=False,
    )


@mcp.tool()
async def search_images_by_image(
    file_path: str,
    index_name: str = "global",
    top_k: int = 5,
) -> str:
    """通过上传的图片搜索相似的图片（以图搜图）。

    仅在用户明确要求以图搜图时调用，需要用户提供图片文件。

    Args:
        file_path: 已上传的图片文件路径，由文件上传功能返回。
        index_name: 索引名称（不带 .index 后缀），可通过 list_image_libraries 查看。默认 "global"。
        top_k: 返回结果数量（默认 5）。

    Returns:
        str: JSON 字符串 {"summary", "items"}，items 含 thumb_url/url/score，
             前端会自动渲染为图片画廊，无需复述文件路径。
    """
    from pathlib import Path
    import mimetypes

    path = Path(file_path)
    if not path.exists():
        return f"图片文件不存在或已过期（可能已被定时清理），请重新上传该图片后再试。"

    client = _get_client()
    media_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    content = path.read_bytes()
    try:
        resp = await client.post(
            f"{MULTIMODEL_URL}/images_search_images/",
            params={
                "index_name": index_name,
                "value": top_k,
                "return_thumbnail": False,
                "return_original": False,
            },
            files={"images": (path.name, content, media_type)},
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as e:
        return _handle_error(e, "图像检索")

    matched = result.get("matched_images", [])
    if not matched:
        return f"未找到与图片 '{path.name}' 匹配的相似图片。"

    items = [
        {
            "kind": "image",
            "path": item.get("path", ""),
            "thumb_url": f"{PUBLIC_MULTIMODEL_BASE}/thumbnails/{item.get('path', '')}",
            "url": f"{PUBLIC_MULTIMODEL_BASE}/images/{item.get('path', '')}",
            "score": round(float(item.get("score", 0)), 4),
        }
        for item in matched
    ]
    return json.dumps(
        {"summary": f"找到 {len(items)} 张相似图片。", "items": items},
        ensure_ascii=False,
    )


# ── 音频检索工具 ──────────────────────────────────────────────


@mcp.tool()
async def list_audio_libraries() -> str:
    """列出所有可用的音频库文件夹和索引。

    Returns:
        str: 音频库目录结构，包含文件夹和索引名称列表。
    """
    client = _get_client()
    try:
        resp = await client.get(
            f"{MULTIMODEL_URL}/get_audios_dir/", params={"include_files": "true"}
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as e:
        return _handle_error(e, "音频检索")

    repos = result.get("repositories", [])
    indices = result.get("indices", [])
    repo_names = [r.get("name", "") for r in repos]
    index_names = [i.get("name", "").replace(".index", "") for i in indices]

    return (
        f"音频库概况：\n"
        f"  文件夹 ({len(repo_names)}): {', '.join(repo_names) if repo_names else '无'}\n"
        f"  索引 ({len(index_names)}): {', '.join(index_names) if index_names else '无'}\n"
        f"可用 index_name 参数值: {index_names if index_names else ['global']}"
    )


@mcp.tool()
async def search_audios_by_text(
    query: str,
    index_name: str = "base",
    top_k: int = 5,
) -> str:
    """通过文字描述搜索相似的音频片段。

    仅在用户明确要求搜索音频时调用。

    Args:
        query: 搜索文本描述，如 "习近平重要讲话" 或 "诗歌朗诵"。
        index_name: 音频索引名（不带 .index 后缀）。音频库默认索引为 "base"
                    （images 才用 "global"），可用 list_audio_libraries 查看。默认 "base"。
        top_k: 返回结果数量（默认 5）。

    Returns:
        str: JSON 字符串 {"summary", "items"}，items 含 url/start/end/text/score，
             前端会自动渲染为音频播放器（含片段定位），无需复述文件路径。
    """
    client = _get_client()
    try:
        resp = await client.post(
            f"{MULTIMODEL_URL}/text_search_audios/",
            params={
                "index_name": index_name,
                "value": top_k,
                "return_audio": False,
                "return_clip": False,
            },
            json={"text": query},
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as e:
        return _handle_error(e, "音频检索")

    matches = result.get("matches", [])
    if not matches:
        return f"未找到与 '{query}' 匹配的音频。"

    items = []
    for item in matches:
        rel = item.get("rel_path") or ""
        items.append({
            "kind": "audio",
            "url": f"{PUBLIC_MULTIMODEL_BASE}/audios/{rel}",
            "start": round(float(item.get("start", 0)), 2),
            "end": round(float(item.get("end", 0)), 2),
            "text": item.get("text", ""),
            "score": round(float(item.get("score", 0)), 4),
        })
    return json.dumps(
        {"summary": f"找到 {len(items)} 段匹配音频。", "items": items},
        ensure_ascii=False,
    )


# ── 启动 ──────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="streamable-http")

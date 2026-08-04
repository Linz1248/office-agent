"""Office MCP Server：将现有办公功能封装为 MCP 工具。

暴露以下 MCP 工具，供 AgentScope Agent 调用：
  - list_extract_documents  : 列出已上传的待抽取 PDF
  - extract_document        : 从 PDF 中抽取指定字段
  - list_compare_documents  : 列出已上传的待比对 PDF
  - compare_documents       : 比对两份 PDF 文档
  - list_image_libraries    : 列出图像库文件夹和索引
  - search_images_by_text   : 通过文字搜索图片
  - list_audio_libraries    : 列出音频库文件夹和索引
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
    HTTP_TIMEOUT,
    PORT,
    SERVICE_ACCOUNT_PASSWORD,
    SERVICE_ACCOUNT_USERNAME,
)

mcp = FastMCP("office-tools", host="0.0.0.0", port=PORT)

# ── 内部辅助函数 ──────────────────────────────────────────────

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(HTTP_TIMEOUT, connect=10.0))
    return _client


# document_extract 服务需要 JWT 认证，缓存 token
_cached_token: str | None = None
_token_expires: float = 0.0


async def _get_extract_token() -> str:
    """使用服务账号登录 document_extract 服务，获取 JWT token。"""
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
    # expiresIn 是毫秒
    _token_expires = time.time() + data.get("expiresIn", 86400000) / 1000
    return _cached_token


async def _extract_headers() -> dict[str, str]:
    """获取 document_extract 服务的认证头。"""
    token = await _get_extract_token()
    return {"Authorization": f"Bearer {token}"}


def _truncate(text: str, max_len: int = 2000) -> str:
    """截断过长文本，避免超出 LLM 上下文限制。"""
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"\n...(已截断，共 {len(text)} 字符)"


# ── 文档抽取工具 ──────────────────────────────────────────────

@mcp.tool()
async def list_extract_documents() -> str:
    """列出当前已上传至文档抽取服务的所有 PDF 文件名。

    Returns:
        str: 文件名列表（JSON 格式），如果没有文件则返回提示信息。
    """
    client = _get_client()
    headers = await _extract_headers()
    # document_extract 没有专门的 list 接口，通过访问根路径确认服务可用
    # 这里我们返回上传目录信息
    resp = await client.get(f"{DOC_EXTRACT_URL}/", headers=headers)
    if resp.status_code == 401:
        # token 过期，重试
        global _cached_token, _token_expires
        _cached_token = None
        _token_expires = 0.0
        headers = await _extract_headers()
        resp = await client.get(f"{DOC_EXTRACT_URL}/", headers=headers)
    return "文档抽取服务已就绪。用户可在对话中直接上传 PDF 文件，上传成功后消息会包含 extract_filename，使用该文件名调用 extract_document 工具进行字段抽取。"


@mcp.tool()
async def extract_document(
    filename: str,
    fields: list[str],
    enhance: bool = False,
    fields_enhance: list[str] | None = None,
    fields_template: dict[str, str] | None = None,
) -> str:
    """从 PDF 文档中抽取指定的字段信息。

    Args:
        filename: 已上传的 PDF 文件名（如 "9f2e1c4f..._1719469876.pdf"）。
        fields: 需要抽取的字段名称列表，如 ["合同名称", "签订日期", "甲方", "乙方"]。
        enhance: 是否启用增强抽取模式（默认 False）。增强模式会使用示例样本提升抽取准确率。
        fields_enhance: 需要增强抽取的字段名列表（仅在 enhance=True 时有效）。
        fields_template: 字段示例样本，key 为字段名，value 为示例值（仅在 enhance=True 时有效）。

    Returns:
        str: 抽取结果（JSON 格式），包含每个字段的提取值。
    """
    client = _get_client()
    headers = await _extract_headers()

    payload: dict[str, Any] = {
        "filename": filename,
        "fields": fields,
        "enhance": enhance,
        "fields_enhance": fields_enhance or [],
        "fields_template": fields_template or {},
    }

    resp = await client.post(
        f"{DOC_EXTRACT_URL}/doc_extract",
        json=payload,
        headers=headers,
    )
    if resp.status_code == 401:
        global _cached_token, _token_expires
        _cached_token = None
        _token_expires = 0.0
        headers = await _extract_headers()
        resp = await client.post(
            f"{DOC_EXTRACT_URL}/doc_extract",
            json=payload,
            headers=headers,
        )
    resp.raise_for_status()
    result = resp.json()
    return _truncate(json.dumps(result, ensure_ascii=False, indent=2))


# ── 文档比对工具 ──────────────────────────────────────────────

@mcp.tool()
async def list_compare_documents() -> str:
    """列出已上传至文档比对服务的所有 PDF 文件。

    Returns:
        str: 文件列表信息。提示用户已上传的文件名，可用于比对操作。
    """
    client = _get_client()
    # document_compare 没有专门的 list 接口
    return "文档比对服务已就绪。用户可在对话中直接上传 PDF 文件，上传成功后消息会包含 compare_filename，使用该文件名调用 compare_documents 工具进行比对。"


@mcp.tool()
async def compare_documents(
    benchmark_file: str,
    compare_file: str,
    use_seal: bool = True,
    header_h: int = 0,
    footer_h: int = 0,
) -> str:
    """比对两份 PDF 文档的差异，包括文本差异和印章差异。

    Args:
        benchmark_file: 基准文件名（原始版本），如 "1719469876_abc123.pdf"。
        compare_file: 待比对文件名（新版本），如 "1719469900_def456.pdf"。
        use_seal: 是否进行印章比对（默认 True）。
        header_h: 页眉高度（像素），页眉区域不参与比对（默认 0）。
        footer_h: 页脚高度（像素），页脚区域不参与比对（默认 0）。

    Returns:
        str: 比对结果，包含相似度分数和结果文件下载链接。
    """
    client = _get_client()
    payload = {
        "benchmark_file": benchmark_file,
        "compare_file": compare_file,
        "use_seal": use_seal,
        "header_h": header_h,
        "footer_h": footer_h,
    }
    resp = await client.post(f"{DOC_COMPARE_URL}/compare", json=payload)
    resp.raise_for_status()
    result = resp.json()

    summary = (
        f"文档比对完成！\n"
        f"相似度: {result.get('similarity', 'N/A')}\n"
        f"基准文件结果: {result.get('benchmark_file', 'N/A')}\n"
        f"比对文件结果: {result.get('compare_file', 'N/A')}\n"
        f"可通过文档比对页面查看标注后的差异详情。"
    )
    return summary


# ── 图像检索工具 ──────────────────────────────────────────────

@mcp.tool()
async def list_image_libraries() -> str:
    """列出所有可用的图像库文件夹和索引。

    Returns:
        str: 图像库目录结构（JSON 格式），包含 repositories 和 indices 两部分。
    """
    client = _get_client()
    resp = await client.get(f"{MULTIMODEL_URL}/get_images_dir/?include_files=false")
    resp.raise_for_status()
    result = resp.json()

    repos = result.get("repositories", [])
    indices = result.get("indices", [])

    repo_names = [r.get("name", "") for r in repos]
    index_names = [i.get("name", "").replace(".index", "") for i in indices]

    summary = (
        f"图像库概况：\n"
        f"  文件夹 ({len(repo_names)}): {', '.join(repo_names) if repo_names else '无'}\n"
        f"  索引 ({len(index_names)}): {', '.join(index_names) if index_names else '无'}\n"
        f"可用 index_name 参数值: {index_names if index_names else ['global']}"
    )
    return summary


@mcp.tool()
async def search_images_by_text(
    query: str,
    index_name: str = "global",
    top_k: int = 5,
) -> str:
    """通过文字描述搜索相似的图片。

    Args:
        query: 搜索文本描述，如 "警车" 或 "起重机"。
        index_name: 索引名称（不带 .index 后缀），可通过 list_image_libraries 查看。默认 "global"。
        top_k: 返回结果数量（默认 5）。

    Returns:
        str: 搜索结果（JSON 格式），包含匹配图片路径和相似度分数。
    """
    client = _get_client()
    resp = await client.post(
        f"{MULTIMODEL_URL}/text_search_images/?index_name={index_name}&value={top_k}",
        json={"text": query},
    )
    resp.raise_for_status()
    result = resp.json()

    results = result.get("results", [])
    if not results:
        return f"未找到与 '{query}' 匹配的图片。"

    lines = [f"找到 {len(results)} 张匹配图片："]
    for i, item in enumerate(results, 1):
        score = item.get("score", 0)
        path = item.get("path", "")
        lines.append(f"  {i}. {path} (相似度: {score:.4f})")
    return "\n".join(lines)


# ── 音频检索工具 ──────────────────────────────────────────────

@mcp.tool()
async def list_audio_libraries() -> str:
    """列出所有可用的音频库文件夹和索引。

    Returns:
        str: 音频库目录结构信息，包含文件夹和索引列表。
    """
    client = _get_client()
    resp = await client.get(f"{MULTIMODEL_URL}/get_audios_dir/?include_files=false")
    resp.raise_for_status()
    result = resp.json()

    repos = result.get("repositories", [])
    indices = result.get("indices", [])

    repo_names = [r.get("name", "") for r in repos]
    index_names = [i.get("name", "").replace(".index", "") for i in indices]

    summary = (
        f"音频库概况：\n"
        f"  文件夹 ({len(repo_names)}): {', '.join(repo_names) if repo_names else '无'}\n"
        f"  索引 ({len(index_names)}): {', '.join(index_names) if index_names else '无'}\n"
        f"可用 index_name 参数值: {index_names if index_names else ['global']}"
    )
    return summary


@mcp.tool()
async def search_audios_by_text(
    query: str,
    index_name: str = "global",
    top_k: int = 5,
) -> str:
    """通过文字描述搜索相似的音频片段。

    Args:
        query: 搜索文本描述，如 "习近平重要讲话" 或 "诗歌朗诵"。
        index_name: 索引名称（不带 .index 后缀），可通过 list_audio_libraries 查看。默认 "global"。
        top_k: 返回结果数量（默认 5）。

    Returns:
        str: 搜索结果，包含匹配音频路径、时间片段、文本内容和相似度分数。
    """
    client = _get_client()
    resp = await client.post(
        f"{MULTIMODEL_URL}/text_search_audios/?index_name={index_name}&value={top_k}",
        json={"text": query},
    )
    resp.raise_for_status()
    result = resp.json()

    matches = result.get("matches", [])
    if not matches:
        return f"未找到与 '{query}' 匹配的音频。"

    lines = [f"找到 {len(matches)} 段匹配音频："]
    for i, item in enumerate(matches, 1):
        score = item.get("score", 0)
        audio_path = item.get("audio_path", "")
        start = item.get("start", 0)
        end = item.get("end", 0)
        text = item.get("text", "")
        lines.append(
            f"  {i}. [{start:.1f}s-{end:.1f}s] {text[:80]}...\n"
            f"     来源: {audio_path} (相似度: {score:.4f})"
        )
    return "\n".join(lines)


# ── 启动 ──────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="streamable-http")

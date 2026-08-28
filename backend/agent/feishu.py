"""飞书会议 API 客户端。

对接飞书开放平台「视频会议」服务端 API，实现会议结束后的自动接收：
  1. tenant_access_token : 自建应用凭证换取租户访问令牌（每账号独立缓存）
  2. 搜索会议记录       : POST /vc/v1/meetings/search，按参会人 open_id 过滤，
                          只返回该用户参与的会议（避免收到别人的会议数据）
  3. 获取会议详情       : GET /vc/v1/meetings/{meeting_id}，含主题/时间/状态/
                          参会人/参会人；启用「获取智能纪要信息」「获取逐字稿信息」
                          字段权限后还会在 related_artifacts 中返回 note_doc_token
                          （智能纪要文档标识）与 verbatim_doc_token（逐字稿标识）。
                          不开通则不返回这两个敏感字段。
  4. 会议产物           : GET /vc/v1/meetings/{meeting_id}?query_mode=1，落在
                          related_artifacts（防御式递归采集文档 token）。
  5. 智能纪要（Note，AI 总结链路）:
        GET /vc/v1/notes/{note_id} → note_doc_token / verbatim_doc_token /
        shared_doc_tokens（防御式兼容顶层字段与 artifacts[].doc_token）。
  6. 会议录制（Recording，录制链路）:
        GET /vc/v1/meetings/{meeting_id}/recording → recording.url（妙记链接），
        从 URL 末尾路径段提取 minute_token。该接口独立于会议详情，
        飞书 API 不会在会议详情中返回 minute_token。
  7. 妙记逐字稿         : GET /minutes/v1/minutes/{minute_token}/transcript
        （成功时返回文件二进制流，非 JSON；用 _request_text 处理）。
  8. 文档纯文本         : GET /docx/v1/documents/{doc_token}/raw_content。

Note 与 Minutes 来自独立的 AI 总结 / 录制两条链路，一场会议可能两者都有、
只有其一、或都没有（飞书领域不变量）。

所有响应均为防御式解析：字段缺失返回空值而非抛错，保证同步循环对飞书
字段演进具备韧性。

应用需在飞书开放平台开通权限：
  - 获取会议信息（基础）
  - 获取智能纪要信息（历史版本，敏感字段，否则不返回 note_doc_token）
  - 获取逐字稿信息（历史版本，敏感字段，否则不返回 verbatim_doc_token）
  - 获取会议录制信息（录制链路，否则无法获取妙记 URL）
  - 导出妙记转写的文字内容（录制链路逐字稿导出）
  - 查看/评论/编辑云文档中所有文档（读取纪要正文）
"""
from __future__ import annotations

import logging
import time
from typing import Any

import asyncio

import httpx

from config import FEISHU_BASE_URL
from redis_utils import cache_get_json, cache_set_json

logger = logging.getLogger(__name__)

# 瞬时传输错误（ConnectTimeout/ReadTimeout/ConnectError 等）的退避重试参数。
# 这些错误通常意味请求未到达飞书或无响应，对只读类飞书 API 重试安全；
# API 错误（FeishuError / HTTPStatusError）不重试，避免副作用。
_HTTP_MAX_RETRIES = 3       # 最多尝试 3 次（含首次）
_HTTP_RETRY_BASE = 0.5      # 退避基数：0.5s → 1.0s → 2.0s

# tenant_access_token 提前刷新的余量（秒）
_TOKEN_REFRESH_MARGIN = 300


class FeishuError(Exception):
    """飞书 API 调用失败（携带错误码便于前端提示）。"""

    def __init__(self, code: int, msg: str):
        self.code = code
        super().__init__(f"飞书 API 错误 {code}: {msg}")


async def _check(data: dict) -> dict:
    """校验飞书统一响应体 {code, msg, data}，非 0 抛 FeishuError。"""
    code = data.get("code", 0)
    if code != 0:
        raise FeishuError(int(code), str(data.get("msg") or "未知错误"))
    return data.get("data") or {}


# 递归采集"文档 token"：飞书会议产物/纪要的字段名与嵌套层级在不同版本间
# 不稳定（顶层 note_doc_token / artifacts[].doc_token / shared_doc_tokens[]
# 等），统一用名称匹配 + 递归取值，避免字段演进导致取不到正文。
_DOC_TOKEN_KEYS = {
    "note_doc_token", "verbatim_doc_token", "doc_token",
    "shared_doc_tokens",
}


def _extract_doc_tokens(obj: Any, out: list[str] | None = None) -> list[str]:
    out = [] if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _DOC_TOKEN_KEYS and isinstance(v, str) and v:
                if v not in out:
                    out.append(v)
            elif k in _DOC_TOKEN_KEYS and isinstance(v, list):
                for item in v:
                    if isinstance(item, str) and item and item not in out:
                        out.append(item)
                    elif isinstance(item, dict):
                        _extract_doc_tokens(item, out)
            elif isinstance(v, (dict, list)):
                _extract_doc_tokens(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _extract_doc_tokens(item, out)
    return out


def _extract_text(obj: Any) -> str:
    """从妙记逐字稿等不定结构的响应里防御式取出纯文本。"""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return "\n".join(_extract_text(it) for it in obj)
    if isinstance(obj, dict):
        for k in ("text", "content", "transcript", "raw_content"):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v
        for k in ("items", "paragraphs", "lines", "blocks"):
            items = obj.get(k)
            if isinstance(items, list) and items:
                return "\n".join(
                    _extract_text(it) for it in items
                )
        # 兜底：拼接所有字符串值
        return "\n".join(
            str(v) for v in obj.values() if isinstance(v, str) and v.strip()
        )
    return ""


def _extract_minute_token(url: str) -> str:
    """从妙记 URL 中提取 minute_token（URL 末尾路径段）。

    录制 API 返回的 ``recording.url`` 形如
    ``https://meetings.feishu.cn/minutes/obcn37dxcftoc3656rgyejm7``，
    末尾路径段即为 minute_token（24 字符），可直接用于调用
    ``/minutes/v1/minutes/{minute_token}/transcript``。
    """
    if not url:
        return ""
    token = url.rstrip("/").rsplit("/", 1)[-1]
    # 过滤可能的 query string
    if "?" in token:
        token = token.split("?", 1)[0]
    return token


class FeishuClient:
    """单用户的飞书自建应用客户端（app_id/app_secret + 本人 open_id）。

    token 获取后缓存在实例内，过期前自动刷新；实例按用户短生命周期创建
    （每次同步新建），无需跨请求共享缓存。

    会话身份优先：若传入 user_access_token（用户授权凭证），所有请求以
    用户身份发出——这是搜索/获取「归属于该用户」的会议记录所必需的
    （tenant_access_token 只能看到归属于应用本身的会议，普通客户端会议
    不在其中）。未授权时退化为 tenant_access_token（仅能调用 get_meeting
    等支持 tenant 的接口，search 会返回空）。
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        app_id: str,
        app_secret: str,
        user_access_token: str | None = None,
    ):
        self._http = http_client
        self._app_id = app_id
        self._app_secret = app_secret
        self._user_access_token = user_access_token
        self._token: str | None = None
        self._token_expires: float = 0.0

    async def _get_token(self) -> str:
        """获取并缓存 tenant_access_token（自建应用凭证）。

        三级缓存：进程内 → Redis（跨 FeishuClient 实例共享，按 app_id）→ 飞书接口。
        本类实例按用户短生命周期创建（每次同步新建），进程内缓存无法跨实例复用，
        故 Redis 层是主缓存；Redis 不可用回退进程内 + 接口，行为等同改造前。
        仅缓存 tenant_access_token；user_access_token（OAuth 按用户令牌）不缓存。
        """
        if self._token and time.time() < self._token_expires - _TOKEN_REFRESH_MARGIN:
            return self._token
        cache_key = f"feishu:tenant_token:{self._app_id}"
        cached = await cache_get_json(cache_key)
        if cached and isinstance(cached, str):
            # Redis 命中即用（TTL 已预留 margin，token 仍有效）；进程内短期复用避免频繁查 Redis
            self._token = cached
            self._token_expires = time.time() + _TOKEN_REFRESH_MARGIN
            return self._token
        resp = await self._send_with_retry(
            "POST",
            f"{FEISHU_BASE_URL}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self._app_id, "app_secret": self._app_secret},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise FeishuError(
                int(data.get("code", -1)),
                f"获取访问凭证失败（请检查 App ID / App Secret）: {data.get('msg')}",
            )
        self._token = data["tenant_access_token"]
        expire = int(data.get("expire", 7200))
        self._token_expires = time.time() + expire
        # 回写 Redis：TTL 提前 margin 刷新，避免缓存内仍用过期 token
        await cache_set_json(cache_key, self._token, max(expire - _TOKEN_REFRESH_MARGIN, 60))
        return self._token

    async def _send_with_retry(self, method: str, url: str, **kwargs) -> httpx.Response:
        """带指数退避的重试：仅对 httpx.TransportError（ConnectTimeout/ReadTimeout/
        ConnectError/PoolTimeout 等）重试。

        这些错误通常意味请求未到达飞书或中途无响应（CDN 抖动等），对只读类飞书
        API 重试安全；HTTP 状态码错误与 FeishuError 不在此处重试（无副作用收益，
        且可能重复触发限流）。重试耗尽后抛最后一条 TransportError，由上层记日志。
        """
        last_exc: Exception | None = None
        for attempt in range(1, _HTTP_MAX_RETRIES + 1):
            try:
                return await self._http.request(method, url, **kwargs)
            except httpx.TransportError as e:
                last_exc = e
                if attempt >= _HTTP_MAX_RETRIES:
                    raise
                delay = _HTTP_RETRY_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "[feishu] %s %s 瞬时传输失败（第%d/%d次）：%s；%.1fs 后重试",
                    method, url, attempt, _HTTP_MAX_RETRIES, e, delay,
                )
                await asyncio.sleep(delay)
        raise last_exc  # 不可达

    async def _request(
        self, method: str, path: str, *, params: dict | None = None,
        json_body: dict | None = None,
    ) -> Any:
        """带鉴权的飞书 OpenAPI 请求，返回 data 部分（或整个 JSON，供防御式解析）。

        鉴权令牌优先级：user_access_token（用户身份）> tenant_access_token
        （应用身份）。飞书的错误响应体为 ``{"code":<非0>, "msg":..., "data":...}``，
        即便 HTTP 状态码是 400/403 也仍是 JSON。这里先解析再交由 _check 抛出
        携带真实错误码与（权限类错误自带的）一键开通链接的 FeishuError，避免
        raise_for_status 把它吞成无意义的 "400 Bad Request"，导致无法定位。
        """
        token = self._user_access_token or await self._get_token()
        resp = await self._send_with_retry(
            method,
            f"{FEISHU_BASE_URL}/open-apis{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            json=json_body,
        )
        try:
            data = resp.json()
        except Exception:
            # 非飞书标准响应（网关错误 HTML 等）：退化为 HTTP 状态报错
            resp.raise_for_status()
            raise
        return await _check(data)

    async def _request_text(
        self, method: str, path: str, *, params: dict | None = None,
    ) -> str:
        """带鉴权的飞书 OpenAPI 请求，返回响应文本（用于文件下载类接口）。

        飞书文件下载接口（如妙记逐字稿导出）成功时返回二进制流（HTTP 200），
        失败时仍为标准 JSON 错误体 {code, msg, data}。据此分流：JSON 响应
        交由 _check 抛出携带错误码的 FeishuError；文本响应直接返回。
        """
        token = self._user_access_token or await self._get_token()
        resp = await self._send_with_retry(
            method,
            f"{FEISHU_BASE_URL}/open-apis{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
        content_type = resp.headers.get("content-type", "")
        # 错误响应仍为 JSON（飞书统一错误体），解析后交由 _check 抛出
        if "application/json" in content_type:
            try:
                data = resp.json()
            except Exception:
                resp.raise_for_status()
                raise
            await _check(data)
            return ""  # code=0 但返回 JSON（不应出现在文件下载接口）
        if resp.status_code != 200:
            resp.raise_for_status()
        return resp.text

    # ── 会议检索 ────────────────────────────────────────────────
    async def search_meeting_ids(
        self,
        participant_open_id: str,
        start_ts: int,
        end_ts: int,
    ) -> list[str]:
        """搜索时间窗内指定参会人的会议，返回会议 ID 列表。

        meeting_filter.participant_ids 限定「我参与的会议」，配合每用户独立的
        应用凭证，从两个层面保证不接收他人的会议数据。

        start_time/end_time 必须为 ISO 8601 UTC 字符串（带 Z），如
        ``2026-08-16T05:41:53Z``；传 unix 秒/毫秒或本地时间会返回 122601
        meeting time format is invalid（经实测算得，SDK 仅标注 str 未给格式）。
        """
        from datetime import datetime, timezone

        def _iso(ts: int) -> str:
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        items: list[dict] = []
        page_token = ""
        while True:
            body: dict[str, Any] = {
                "query": "",
                "meeting_filter": {
                    "participant_ids": [participant_open_id],
                    "start_time": {
                        "start_time": _iso(start_ts),
                        "end_time": _iso(end_ts),
                    },
                },
            }
            if page_token:
                body["page_token"] = page_token
            data = await self._request(
                "POST", "/vc/v1/meetings/search", json_body=body
            )
            batch = data.get("items") or []
            items.extend(batch)
            if not data.get("has_more"):
                break
            page_token = data.get("page_token") or ""
            if not page_token:
                break
        return [str(it.get("id")) for it in items if it.get("id")]

    # ── 会议详情 ────────────────────────────────────────────────
    async def get_meeting(self, meeting_id: str) -> dict:
        """获取会议详情（含参会人列表）。返回 meeting 字典，失败返回空 dict。"""
        data = await self._request(
            "GET",
            f"/vc/v1/meetings/{meeting_id}",
            params={"user_id_type": "open_id", "with_participants": "true"},
        )
        return data.get("meeting") or {}

    async def get_meeting_artifacts(self, meeting_id: str) -> list[str]:
        """获取会议产物（智能纪要/逐字稿）的文档 token 列表。

        query_mode=1 只返回会议产物，落在 ``related_artifacts`` 字段（其内部
        结构飞书文档未给出稳定 schema）。这里防御式递归采集一切形如
        note_doc_token / verbatim_doc_token / shared_doc_tokens 的文档 token，
        字段名或嵌套层级变化都不影响取值。
        """
        try:
            data = await self._request(
                "GET", f"/vc/v1/meetings/{meeting_id}", params={"query_mode": 1}
            )
        except FeishuError as e:
            # 未开通智能纪要字段权限时降级：继续走 note_id 路径
            logger.warning("获取会议产物失败 meeting=%s: %s", meeting_id, e)
            return []
        return _extract_doc_tokens(data)

    # ── 会议录制（Recording，录制链路）──────────────────────────
    async def get_meeting_recording(self, meeting_id: str) -> dict:
        """获取会议录制文件信息（含妙记 URL，从中提取 minute_token）。

        GET /vc/v1/meetings/{meeting_id}/recording，需「获取会议录制信息」
        （vc:record:readonly）权限。返回 recording 字典，其 ``url`` 字段
        为妙记链接（``https://meetings.feishu.cn/minutes/{minute_token}``），
        末尾路径段即为 minute_token，可直接用于导出逐字稿。

        会议未录制、录制仍在处理中（错误码 124002）时返回空 dict。
        """
        try:
            data = await self._request(
                "GET", f"/vc/v1/meetings/{meeting_id}/recording"
            )
        except FeishuError as e:
            # 录制未开启 / 仍在处理 / 无权限 → 降级，不影响 AI 纪要链路
            logger.warning("获取会议录制失败 meeting=%s: %s", meeting_id, e)
            return {}
        return data.get("recording") or {}

    # ── 智能纪要（Note，AI 总结链路）──────────────────────────────
    async def get_note_doc_tokens(self, note_id: str) -> list[str]:
        """获取智能纪要下挂文档 token（note_doc_token / verbatim_doc_token /
        shared_doc_tokens）。

        GET /vc/v1/notes/{note_id} 返回 note 对象；其字段在历史版本为
        ``artifacts[].doc_token``，新版为顶层 ``note_doc_token`` 等。防御式
        递归采集，兼容两种结构。需开通「获取智能纪要信息」「获取逐字稿信息」
        字段权限才会返回这些 token。
        """
        data = await self._request(
            "GET", f"/vc/v1/notes/{note_id}", params={"user_id_type": "open_id"}
        )
        note = data.get("note") or data or {}
        return _extract_doc_tokens(note)

    # ── 妙记（Minutes，录制链路）────────────────────────────────
    async def get_minutes_transcript(self, minute_token: str) -> str:
        """导出妙记文字记录（录制链路的逐字稿，与 AI 总结的 Note 相互独立）。

        GET /minutes/v1/minutes/{minute_token}/transcript，需「导出妙记转写的
        文字内容」（minutes:minutes.transcript:export）权限。

        与常规飞书 API 不同，该接口成功时返回文件二进制流（.txt/.srt），
        失败时才返回 JSON 错误体。因此用 _request_text 处理，而非 _request。
        """
        return await self._request_text(
            "GET", f"/minutes/v1/minutes/{minute_token}/transcript",
            params={"need_speaker": "true", "file_format": "txt"},
        )

    # ── 文档正文 ────────────────────────────────────────────────
    async def get_doc_raw_content(self, doc_token: str) -> str:
        """读取云文档纯文本正文（纪要/逐字稿内容）。"""
        data = await self._request(
            "GET", f"/docx/v1/documents/{doc_token}/raw_content"
        )
        return str(data.get("content") or "")

    async def collect_meeting_content(
        self, meeting: dict, artifact_tokens: list[str]
    ) -> str:
        """汇聚一场会议的全部文本内容。

        两条独立链路（飞书领域模型：Note 与 Minutes 互不蕴含）：
          A. AI 总结 → Note(note_id) → /vc/v1/notes/{note_id} → note_doc_token
             等文档 token → docx raw_content（智能纪要正文 + 逐字稿）。
          B. 录制 → /vc/v1/meetings/{meeting_id}/recording → recording.url →
             从 URL 提取 minute_token → /minutes/v1/.../transcript（文字记录）。
        另并入会议产物 query_mode=1 的 related_artifacts token。单个文档/接口
        失败不影响其余。无任何标识时，提示多为字段权限未开通而非"无纪要"。
        """
        tokens = list(artifact_tokens)
        note_id = meeting.get("note_id")
        meeting_id = meeting.get("id")

        if note_id:
            try:
                for token in await self.get_note_doc_tokens(str(note_id)):
                    if token not in tokens:
                        tokens.append(token)
            except FeishuError as e:
                logger.warning("获取智能纪要失败 note=%s: %s", note_id, e)

        parts: list[str] = []
        for token in tokens:
            try:
                text = await self.get_doc_raw_content(token)
            except FeishuError as e:
                logger.warning("读取会议文档失败 doc=%s: %s", token, e)
                continue
            if text.strip():
                parts.append(text.strip())

        # 录制链路：通过录制 API 获取妙记 URL → 提取 minute_token → 导出逐字稿
        # （minute_token 不在会议详情响应中，须单独调用录制接口获取）
        if meeting_id:
            try:
                recording = await self.get_meeting_recording(str(meeting_id))
                minute_token = _extract_minute_token(recording.get("url") or "")
                if minute_token:
                    try:
                        text = await self.get_minutes_transcript(minute_token)
                        if text.strip():
                            parts.append(text.strip())
                    except Exception as e:  # noqa: BLE001 权限不足/妙记未就绪不影响 Note 链路
                        logger.warning("获取妙记逐字稿失败 minute=%s: %s", minute_token, e)
            except Exception as e:  # noqa: BLE001 录制接口不可用不影响 Note 链路
                logger.warning("获取会议录制信息失败 meeting=%s: %s", meeting_id, e)

        if not parts and not note_id and not tokens:
            logger.warning(
                "会议无 note_id/产物 token/录制正文（meeting=%s）。"
                "应用很可能未在飞书开放平台开通「获取智能纪要信息」「获取逐字稿信息」"
                "「获取会议录制信息」「导出妙记转写的文字内容」权限，"
                "或该会议确实未生成纪要/录制。",
                meeting.get("id"),
            )
        return "\n\n".join(parts)


# ── 用户授权（user_access_token，OAuth）─────────────────────────────
# 搜索/获取「归属于用户本人」的会议记录必须以用户身份调用，tenant 身份只能
# 看到归属于应用的会议。流程：引导用户打开授权页 → 飞书回调带回 code →
# 用 code 换 user_access_token + refresh_token → 后续用 refresh_token 自动续期。
# 授权页与换/刷 token 均用 v1（/authen/v1/index、/authen/v1/access_token、
# /authen/v1/refresh_access_token）——经实测 v2/v3 的 /oapi/token 路径均 404，
# v1 端点可用且稳定。v1 token 端点需 app_access_token 作 Authorization 头。
_OAUTH_AUTH_URL = f"{FEISHU_BASE_URL}/open-apis/authen/v1/index"
_OAUTH_TOKEN_URL = f"{FEISHU_BASE_URL}/open-apis/authen/v1/access_token"
_OAUTH_REFRESH_URL = f"{FEISHU_BASE_URL}/open-apis/authen/v1/refresh_access_token"
_APP_TOKEN_URL = f"{FEISHU_BASE_URL}/open-apis/auth/v3/app_access_token/internal"


def build_auth_url(app_id: str, redirect_uri: str, state: str) -> str:
    """构造飞书用户授权页链接（scope 含 offline_access 以获取 refresh_token）。"""
    from urllib.parse import urlencode

    return (
        _OAUTH_AUTH_URL
        + "?"
        + urlencode(
            {
                "app_id": app_id,
                "redirect_uri": redirect_uri,
                "state": state,
                # offline_access 必须在授权页声明，否则换 token 时不返回 refresh_token
                "scope": "offline_access",
            }
        )
    )


async def _get_app_access_token(
    http_client: httpx.AsyncClient, app_id: str, app_secret: str,
) -> str:
    """获取 app_access_token（v1 user token 端点鉴权所需，约 2h 有效，按需获取不缓存）。"""
    resp = await http_client.post(
        _APP_TOKEN_URL, json={"app_id": app_id, "app_secret": app_secret}
    )
    try:
        data = resp.json()
    except Exception:
        resp.raise_for_status()
        raise
    if data.get("code") != 0:
        raise FeishuError(
            int(data.get("code", -1)),
            f"获取 app_access_token 失败: {data.get('msg')}",
        )
    return data["app_access_token"]


def _parse_token_response(data: dict) -> dict:
    """解析 v1 token 端点响应 {code,msg,data:{access_token,refresh_token,...}}。"""
    code = data.get("code")
    if code not in (None, 0):
        raise FeishuError(int(code), f"user token 操作失败: {data.get('msg')}")
    inner = data.get("data") if isinstance(data.get("data"), dict) else data
    access_token = (inner or {}).get("access_token")
    if not access_token:
        raise FeishuError(-1, f"user token 响应异常: {data}")
    return {
        "access_token": access_token,
        "refresh_token": (inner or {}).get("refresh_token"),
        "expires_in": int((inner or {}).get("expires_in") or 0),
        "refresh_expires_in": int((inner or {}).get("refresh_expires_in") or 0),
    }


async def exchange_code(
    http_client: httpx.AsyncClient, app_id: str, app_secret: str,
    code: str, redirect_uri: str,
) -> dict:
    """用授权码 code 换取 user_access_token + refresh_token（v1 端点）。"""
    app_token = await _get_app_access_token(http_client, app_id, app_secret)
    resp = await http_client.post(
        _OAUTH_TOKEN_URL,
        headers={
            "Authorization": f"Bearer {app_token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json={"grant_type": "authorization_code", "code": code},
    )
    try:
        data = resp.json()
    except Exception:
        resp.raise_for_status()
        raise
    return _parse_token_response(data)


async def refresh_access_token(
    http_client: httpx.AsyncClient, app_id: str, app_secret: str,
    refresh_token: str,
) -> dict:
    """用 refresh_token 刷新 user_access_token（v1 端点）。"""
    app_token = await _get_app_access_token(http_client, app_id, app_secret)
    resp = await http_client.post(
        _OAUTH_REFRESH_URL,
        headers={
            "Authorization": f"Bearer {app_token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json={"grant_type": "refresh_token", "refresh_token": refresh_token, "app_id": app_id},
    )
    try:
        data = resp.json()
    except Exception:
        resp.raise_for_status()
        raise
    return _parse_token_response(data)

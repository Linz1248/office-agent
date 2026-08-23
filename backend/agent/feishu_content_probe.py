"""飞书会议正文链路诊断（user_access_token 身份）。

用真实用户授权凭证逐层打印每场会议的正文来源，定位"无正文"卡在哪一环：
  - 会议详情是否返回 note_id（智能纪要标识）
  - 会议产物 related_artifacts、智能纪要 doc token
  - 会议录制 API 是否返回妙记 URL（从中提取 minute_token）
  - 妙记逐字稿导出（录制链路正文）
  - 最终汇聚正文长度

用法：python feishu_content_probe.py [meeting_id ...]   # 不传则查全部会议
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feishu  # noqa: E402
from config import MEETING_DB_PATH  # noqa: E402


async def main(meeting_ids: list[str]) -> None:
    c = sqlite3.connect(str(MEETING_DB_PATH))
    c.row_factory = sqlite3.Row
    acc = c.execute(
        "SELECT app_id, app_secret, user_access_token, refresh_token, "
        "user_token_expires FROM feishu_accounts WHERE enabled=1 LIMIT 1"
    ).fetchone()
    if not acc:
        print("无已启用飞书账号"); return
    if not meeting_ids:
        meeting_ids = [r["meeting_id"] for r in c.execute(
            "SELECT meeting_id FROM meetings ORDER BY start_time DESC")]
    c.close()
    if not meeting_ids:
        print("无会议可诊断"); return

    now = int(time.time())
    async with httpx.AsyncClient(timeout=30.0) as http:
        token = acc["user_access_token"]
        if not token or not acc["user_token_expires"] or now >= acc["user_token_expires"] - 60:
            if not acc["refresh_token"]:
                print("user_access_token 失效且无 refresh_token，需重新授权"); return
            data = await feishu.refresh_access_token(
                http, acc["app_id"], acc["app_secret"], acc["refresh_token"])
            token = data["access_token"]
            print(f"[token] 已刷新，{data.get('expires_in')}s 后过期")

        client = feishu.FeishuClient(
            http, acc["app_id"], acc["app_secret"], user_access_token=token)
        for mid in meeting_ids:
            print(f"\n{'='*64}\n会议 {mid}")
            try:
                meeting = await client.get_meeting(mid)
            except feishu.FeishuError as e:
                print(f"  [详情] ✗ {e}"); continue
            note_id = meeting.get("note_id")
            meeting_id = meeting.get("id")
            print(f"  [详情] topic={meeting.get('topic')!r}")
            print(f"         note_id={note_id!r}  meeting_id={meeting_id!r}")
            print(f"         keys={list(meeting.keys())}")
            if not note_id:
                print("  ⚠ 无 note_id —— 会议可能未开启 AI 总结，或妙记尚未生成")

            try:
                arts = await client.get_meeting_artifacts(mid)
                print(f"  [产物 query_mode=1] doc_tokens={arts}")
            except feishu.FeishuError as e:
                print(f"  [产物] ✗ {e}")

            # 录制链路：通过录制 API 获取妙记 URL → 提取 minute_token
            minute_token = ""
            if meeting_id:
                try:
                    recording = await client.get_meeting_recording(str(meeting_id))
                    minute_url = recording.get("url") or ""
                    minute_token = feishu._extract_minute_token(minute_url)
                    print(f"  [录制] url={minute_url!r}  minute_token={minute_token!r}")
                except feishu.FeishuError as e:
                    print(f"  [录制] ✗ {e}")

            if note_id:
                try:
                    nt = await client.get_note_doc_tokens(str(note_id))
                    print(f"  [纪要 /vc/v1/notes] doc_tokens={nt}")
                except feishu.FeishuError as e:
                    print(f"  [纪要] ✗ {e}")
            if minute_token:
                try:
                    txt = await client.get_minutes_transcript(minute_token)
                    print(f"  [妙记逐字稿] len={len(txt)} 预览={txt[:160]!r}")
                except feishu.FeishuError as e:
                    print(f"  [妙记逐字稿] ✗ {e}")

            content = await client.collect_meeting_content(meeting, arts)
            print(f"  [汇聚正文] len={len(content)}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))

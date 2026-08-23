"""飞书会议接收链路诊断脚本。

不依赖真实"开会"即可逐层验证 feishu.py 的接收链路是否通畅：
  1. tenant_access_token（凭证是否正确）
  2. 搜索会议记录（按本人 open_id 过滤，能否搜到历史会议）
  3. 获取会议详情（主题/时间/状态/参会人）
  4. 拉取妙记/智能纪要正文（会议产物 doc token → docx 正文）

用法（在 backend/agent 目录下运行）：
  python feishu_probe.py --app-id cli_xxxxxxxx --app-secret xxx --open-id ou_xxxxxxxx
  # 也可只传 --open-id，app_id/app_secret 从 .env 的 FEISHU_APP_ID/FEISHU_APP_SECRET 读取（可选）

输出每一步的成功结果或飞书错误码，据此判断卡在哪一步（通常是应用权限未开通）。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

import httpx

# 允许从 .env 读取凭证（可选）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def _fail(msg: str) -> None:
    print(f"  \033[31m✗\033[0m {msg}")


def _info(msg: str) -> None:
    print(f"  · {msg}")


async def probe(app_id: str, app_secret: str, open_id: str, lookback_days: int) -> bool:
    import feishu  # 本地模块

    async with httpx.AsyncClient(timeout=30.0) as http:
        client = feishu.FeishuClient(http, app_id, app_secret)

        # ── 1. 凭证 → tenant_access_token ──
        print("\n[1/4] 校验飞书应用凭证（换取 tenant_access_token）…")
        try:
            await client._get_token()
            _ok("凭证有效，已获取 tenant_access_token")
        except feishu.FeishuError as e:
            _fail(f"凭证校验失败：{e}（请检查 App ID / App Secret 是否正确，应用是否已发布）")
            return False
        except Exception as e:  # noqa: BLE001
            _fail(f"网络或未知错误：{e}")
            return False

        # ── 2. 搜索会议记录（按参会人 = 本人过滤）──
        end_ts = int(time.time())
        start_ts = end_ts - lookback_days * 86400
        print(f"\n[2/4] 搜索最近 {lookback_days} 天内你参与的会议…")
        try:
            meeting_ids = await client.search_meeting_ids(open_id, start_ts, end_ts)
            _ok(f"搜到 {len(meeting_ids)} 场会议")
        except feishu.FeishuError as e:
            _fail(f"搜索会议失败：{e}")
            _info("常见原因：未开通「获取会议信息」权限，或 open_id 不属于本应用可见范围")
            return False
        if not meeting_ids:
            _info("该账号近期无会议记录——可开一场会（开启录制/AI 总结）后再跑本脚本")
            return True

        # ── 3. 最近一场会议详情 ──
        mid = meeting_ids[0]
        print(f"\n[3/4] 获取最近一场会议详情（meeting_id={mid}）…")
        try:
            meeting = await client.get_meeting(mid)
        except feishu.FeishuError as e:
            _fail(f"获取详情失败：{e}")
            return False
        status_map = {1: "呼叫中", 2: "进行中", 3: "已结束"}
        status = status_map.get(int(meeting.get("status") or 0), str(meeting.get("status")))
        _ok(f"主题：{meeting.get('topic') or '（无主题）'}")
        _info(f"状态：{status}　会议号：{meeting.get('meeting_no')}")
        _info(f"时间：{meeting.get('start_time')} ~ {meeting.get('end_time')}")
        _info(f"参会人数：{meeting.get('participant_count')}　note_id：{meeting.get('note_id')}")
        _info(f"录制能力：{meeting.get('ability', {}).get('use_recording') if meeting.get('ability') else 'N/A'}")

        # ── 4. 会议正文（妙记/智能纪要）──
        print(f"\n[4/4] 拉取会议正文（妙记/智能纪要）…")
        try:
            artifacts = await client.get_meeting_artifacts(mid)
            _info(f"会议产物 doc token：{artifacts or '（无，可能未开启录制/AI 总结）'}")
            content = await client.collect_meeting_content(meeting, artifacts)
        except feishu.FeishuError as e:
            _fail(f"拉取正文失败：{e}")
            _info("常见原因：未开通「查看云文档」权限，或会议未开启录制/AI 总结（妙记尚未生成）")
            return False
        if content.strip():
            _ok(f"正文获取成功，共 {len(content)} 字符")
            _info("正文预览：\n" + content[:300].replace("\n", " ") + ("…" if len(content) > 300 else ""))
            _ok("\n接收链路完全通畅：会议结束后系统将能自动收到数据。")
        else:
            _info("正文为空——该会议可能未开启录制/AI 总结，或妙记仍在生成（会后数分钟到数小时）")
            _info("飞书里确认该会议有妙记/智能纪要后再重试")
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description="飞书会议接收链路诊断")
    parser.add_argument("--app-id", default=os.environ.get("FEISHU_APP_ID", ""))
    parser.add_argument("--app-secret", default=os.environ.get("FEISHU_APP_SECRET", ""))
    parser.add_argument("--open-id", required=True, help="你的飞书 Open ID（ou_ 开头）")
    parser.add_argument("--days", type=int, default=7, help="回看天数（默认 7）")
    args = parser.parse_args()

    if not args.app_id or not args.app_secret:
        print("缺少 App ID / App Secret。请通过 --app-id/--app-secret 传入，")
        print("或在 backend/agent 目录设置环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET。")
        return 2
    if not args.open_id.startswith("ou_"):
        print("Open ID 应以 ou_ 开头")
        return 2

    print("=" * 56)
    print(" 飞书会议接收链路诊断")
    print("=" * 56)
    return 0 if asyncio.run(probe(args.app_id, args.app_secret, args.open_id, args.days)) else 1


if __name__ == "__main__":
    sys.exit(main())

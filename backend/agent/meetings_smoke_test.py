"""飞书会议模块冒烟测试（不依赖真实飞书账号与向量库）。

覆盖：
1. 元数据库建表与账号/待办/通知读写
2. 会议分析子 agent（真实 LLM 调用，structured_schema 输出）
3. 会议正文入库 + 分析结果 + 待办落库（is_mine=yes/unsure 两类）
4. 会议知识库索引与检索（需 Ollama 嵌入；不可用时跳过并提示）

运行：cd backend/agent && python meetings_smoke_test.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 用临时目录避免污染真实 meetings.db / meetings_qdrant
import config

_tmp = tempfile.mkdtemp(prefix="meetings_smoke_")
config.MEETING_DB_PATH = type(config.MEETING_DB_PATH)(os.path.join(_tmp, "meetings.db"))
config.MEETING_QDRANT_PATH = type(config.MEETING_QDRANT_PATH)(
    os.path.join(_tmp, "qdrant")
)

import httpx

import llm_config
import meetings

TEST_USER = "smoke_user"


def _check(name: str, cond: bool, detail: str = ""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}{(' - ' + detail) if detail else ''}")
    return cond


async def main() -> bool:
    results = []

    model = llm_config.get_meeting_model()
    async with httpx.AsyncClient(timeout=60.0) as client:
        await meetings.init_meetings(client, model)
        results.append(_check("模块初始化（会议知识库就绪=%s）" % meetings.is_kb_ready(), True))

        # 1. 账号配置读写（跳过真实连通性校验，直接写表）
        now = str(int(time.time() * 1000))
        await meetings._db.execute(
            "INSERT INTO feishu_accounts (user_id, app_id, app_secret, open_id, my_name, "
            "enabled, created_at, updated_at) VALUES (?, 'cli_x', 'secret', 'ou_x', '小明', 1, ?, ?)",
            (TEST_USER, now, now),
        )
        await meetings._db.commit()
        account = await meetings.get_account(TEST_USER)
        results.append(_check("账号配置读写", account is not None and account["my_name"] == "小明"))

        # 2. 会议入库（模拟一场已结束的产品周会）
        meeting_id = "smoke_meeting_1"
        content = (
            "产品周会 2026-08-20\n参会人：小明（产品经理）、王总、李雷（研发）、韩梅梅（设计）\n\n"
            "王总：Q3 会上线智能纪要功能，李雷你负责在 8月29日 18:00 前完成服务端联调。\n"
            "李雷：好的，我周五前给出联调报告。\n"
            "韩梅梅：首页改版的设计稿我这周内发出来。\n"
            "王总：另外大家都看一下竞品的新版本，下周会上讨论。\n"
            "小明：我来整理本次会议纪要，明天发群里。"
        )
        await meetings._db.execute(
            "INSERT INTO meetings (user_id, meeting_id, meeting_no, topic, start_time, "
            "end_time, status, analyze_status, content_text, created_at, updated_at) "
            "VALUES (?, ?, '123456789', '产品周会', 1755648000, 1755651600, 3, 'pending', ?, ?, ?)",
            (TEST_USER, meeting_id, content, now, now),
        )
        await meetings._db.commit()

        # 3. 子 agent 分析（真实 LLM）
        analysis = await meetings.analyze_meeting(TEST_USER, meeting_id)
        results.append(_check(
            "子 agent 结构化输出",
            bool(analysis.get("summary")) and isinstance(analysis.get("todos"), list),
            f"todos={len(analysis.get('todos') or [])}",
        ))
        todos = analysis.get("todos") or []
        mine = [t for t in todos if t.get("is_mine") == "yes"]
        unsure = [t for t in todos if t.get("is_mine") == "unsure"]
        others = [t for t in todos if t.get("is_mine") == "no"]
        results.append(_check(
            "待办归属三分类（yes/unsure/no）",
            len(mine) >= 1 and len(unsure) >= 1 and len(others) >= 1,
            f"mine={[t['content'] for t in mine]} unsure={[t['content'] for t in unsure]} "
            f"no={[t['content'] for t in others]}",
        ))
        # 小明被点名整理纪要 -> 应有一条 mine；李雷的联调 -> 应为 no
        results.append(_check(
            "点名本人的待办判定为 mine",
            any("纪要" in t["content"] for t in mine),
        ))
        results.append(_check(
            "指派给他人（李雷）的待办判定为 no",
            any("联调" in t["content"] for t in others),
        ))

        # 4. 待办落库（no 不入库）
        db_todos = await meetings.list_todos(TEST_USER)
        results.append(_check(
            "待办落库（排除他人待办）",
            len(db_todos) == len(mine) + len(unsure),
        ))
        confirmed = [t for t in db_todos if t["status"] == "confirmed"]
        pending = [t for t in db_todos if t["status"] == "pending_confirm"]
        results.append(_check(
            "mine->confirmed / unsure->pending_confirm",
            len(confirmed) == len(mine) and len(pending) == len(unsure),
        ))

        # 5. 通知
        notifs = await meetings.list_notifications(TEST_USER)
        results.append(_check("会议接收通知", len(notifs) >= 1, notifs[0]["title"] if notifs else ""))

        # 6. 会议知识库索引与检索（嵌入不可用则跳过）
        if meetings.is_kb_ready():
            items = await meetings.search_meeting_kb(TEST_USER, "谁负责服务端联调")
            results.append(_check(
                "会议知识库检索", len(items) >= 1,
                f"top={items[0]['topic'] if items else ''}",
            ))
        else:
            print("[SKIP] 会议知识库检索（Ollama 嵌入不可用）")

        # 7. 重复分析幂等（已 done 直接返回缓存）
        again = await meetings.analyze_meeting(TEST_USER, meeting_id)
        results.append(_check("重复分析幂等", again.get("meeting_id") == meeting_id))

        # 8. 通知设置校验
        try:
            await meetings.save_notify_settings(TEST_USER, "bad-email", True, "", False)
            results.append(_check("邮箱格式校验", False))
        except ValueError:
            results.append(_check("邮箱格式校验", True))

        await meetings.close_meetings()

    print(f"\n{'全部通过' if all(results) else '存在失败项'}: {sum(results)}/{len(results)}")
    return all(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)

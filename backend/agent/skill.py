"""Skill 系统：Markdown 指令集 + 内网共享市场。

基于 AgentScope SDK 的 Skill 机制（``SkillLoaderBase``），实现：

  - **个人 Skill**：用户通过前端编辑器创建 Markdown 指令文件（``SKILL.md``），
    智能体在对话中通过 SDK 内置的 ``Skill`` 查看器按需读取指令。
  - **内网共享市场**：用户可将个人 skill 公开到市场，其他用户可浏览、安装。
  - **快照拷贝安装**：安装时完整拷贝 ``SKILL.md`` 到安装者目录，原作者
    删除/修改不影响已安装版本；安装者可主动检查更新并选择同步。

与知识库（kb.py）的多租户隔离模式一致：

  - SQLite 元数据表，复合主键 ``(user_id, skill_id)``
  - ``shared`` 字段控制是否公开到市场
  - ``enabled`` 字段控制是否在对话中生效
  - contextvar 跨请求共享 Toolkit 但按请求解析当前用户

工具按请求解析当前用户：``/chat`` 在创建 Agent 前将 user_id 写入 contextvar，
``SharedSkillLoader.list_skills`` 读取之，故同一 Toolkit 可跨用户共享。
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid
from contextvars import ContextVar
from pathlib import Path

import aiosqlite
from agentscope.skill import Skill, SkillLoaderBase

from config import SKILL_DB_PATH, SKILL_DIR

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(_h)
logger.propagate = False


# ── 文件名安全化（与 kb._safe 一致，防路径穿越）────────────────────────────
def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", s).strip("._-") or "default"


# ── 当前请求上下文（供 SharedSkillLoader 按请求解析当前用户）──────────────
_current_user: ContextVar[str] = ContextVar("skill_current_user", default="")


def set_skill_context(user_id: str) -> None:
    """在 /chat 创建 Agent 前调用，注入当前用户到 contextvar。"""
    _current_user.set(user_id)


# ── 全局资源（lifespan 中初始化）──────────────────────────────────────────
_db: aiosqlite.Connection | None = None


def _now() -> str:
    return str(int(time.time() * 1000))


# ── 数据库初始化 ──────────────────────────────────────────────────────────
async def _init_db() -> None:
    global _db
    _db = await aiosqlite.connect(str(SKILL_DB_PATH))
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute(
        """
        CREATE TABLE IF NOT EXISTS skills (
            user_id           TEXT NOT NULL,
            skill_id          TEXT NOT NULL,
            name              TEXT NOT NULL,
            description       TEXT NOT NULL,
            shared            INTEGER NOT NULL DEFAULT 0,
            enabled           INTEGER NOT NULL DEFAULT 1,
            dir               TEXT NOT NULL,
            markdown          TEXT,
            tags              TEXT,
            author            TEXT,
            source_skill_id   TEXT,
            source_version    TEXT,
            source_updated_at TEXT,
            has_update        INTEGER NOT NULL DEFAULT 0,
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL,
            PRIMARY KEY (user_id, skill_id)
        )
        """
    )
    await _db.commit()
    logger.info(f"Skill 元数据库: {SKILL_DB_PATH}")


async def _close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


# ── frontmatter 解析 ──────────────────────────────────────────────────────
_FRONTMATTER_RE = re.compile(
    r"^\s*---\s*\n(?P<body>.*?)\n---\s*\n", re.DOTALL
)
_FIELD_RE = re.compile(r"^(?P<key>\w+)\s*:\s*(?P<value>.+)$", re.MULTILINE)


def _parse_frontmatter(content: str) -> tuple[str, str, str]:
    """解析 SKILL.md 的 frontmatter，返回 (name, description, body)。

    body 为 frontmatter 之后的 Markdown 正文。
    """
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return "", "", content.strip()
    body_text = m.group("body")
    fields = {
        fm.group("key"): fm.group("value").strip()
        for fm in _FIELD_RE.finditer(body_text)
    }
    md_body = content[m.end():].strip()
    return fields.get("name", ""), fields.get("description", ""), md_body


def _build_skill_md(name: str, description: str, tags: str, body: str) -> str:
    """组装完整的 SKILL.md 内容。"""
    parts = ["---", f"name: {name}", f"description: {description}"]
    if tags:
        parts.append(f"tags: {tags}")
    parts.append("---")
    if body:
        parts.append("")
        parts.append(body)
    return "\n".join(parts) + "\n"


def validate_skill_md(content: str) -> tuple[bool, str, str, str, str]:
    """校验上传的 SKILL.md 内容是否符合 SDK 的 frontmatter 规范。

    SDK 的 ``LocalSkillLoader._load_single_skill`` 使用 ``frontmatter.loads``
    解析 SKILL.md，要求 frontmatter 中必须包含 ``name`` 和 ``description``
    字段，否则跳过该 skill（返回 None）。

    本函数复刻 SDK 的校验逻辑，在上传时提前拦截不合规的文件，避免
    创建出 Loader 加载不到的"死 skill"。

    Returns:
        ``(valid, name, description, tags, body)``
        - ``valid``: 是否通过校验
        - ``name`` / ``description`` / ``tags``: frontmatter 中的字段值
        - ``body``: frontmatter 之后的 Markdown 正文
    """
    try:
        import frontmatter as fm_lib

        parsed = fm_lib.loads(content)
    except Exception:
        # frontmatter 库不可用时回退到正则解析
        name, desc, body = _parse_frontmatter(content)
        tags = ""
        if not name or not desc:
            return (False, "", "", "", "SKILL.md 缺少必需的 frontmatter 字段（name 或 description）")
        # 尝试从正则提取 tags
        m = _FRONTMATTER_RE.match(content)
        if m:
            fields = {
                fm.group("key"): fm.group("value").strip()
                for fm in _FIELD_RE.finditer(m.group("body"))
            }
            tags = fields.get("tags", "")
        return (True, name, desc, tags, body)

    name = str(parsed.get("name", "")).strip()
    description = str(parsed.get("description", "")).strip()
    tags = str(parsed.get("tags", "")).strip()
    body = parsed.content.strip()

    if not name:
        return (False, "", "", "", "SKILL.md 的 frontmatter 中缺少必需字段：name")
    if not description:
        return (False, "", "", "", "SKILL.md 的 frontmatter 中缺少必需字段：description")
    if not body:
        return (False, "", "", "", "SKILL.md 的指令正文为空，请添加具体的指令步骤")

    return (True, name, description, tags, body)


# ── 工具函数 ──────────────────────────────────────────────────────────────
def _skill_dir(user_id: str, skill_name: str, *, installed: bool = False) -> str:
    """返回 skill 文件目录的绝对路径。"""
    base = SKILL_DIR / _safe(user_id)
    if installed:
        base = base / "_installed"
    return str(base / _safe(skill_name))


def _row_to_dict(row: aiosqlite.Row) -> dict:
    return {
        "skill_id": row["skill_id"],
        "name": row["name"],
        "description": row["description"],
        "shared": bool(row["shared"]),
        "enabled": bool(row["enabled"]),
        "tags": row["tags"] or "",
        "author": row["author"],
        "has_update": bool(row["has_update"]),
        "markdown": row["markdown"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def _read_skill_md(dir_path: str) -> str | None:
    """读取目录中的 SKILL.md 全文。"""
    md_path = os.path.join(dir_path, "SKILL.md")
    try:
        import aiofiles

        async with aiofiles.open(md_path, "r", encoding="utf-8") as f:
            return await f.read()
    except Exception:
        return None


# ── CRUD ──────────────────────────────────────────────────────────────────
async def list_skills(user_id: str) -> list[dict]:
    """列出用户的所有 skill（自建 + 已安装）。"""
    if _db is None:
        return []
    cursor = await _db.execute(
        "SELECT * FROM skills WHERE user_id=? ORDER BY created_at DESC",
        (user_id,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [_row_to_dict(r) for r in rows]


async def get_skill(user_id: str, skill_id: str) -> dict | None:
    """获取单个 skill 详情。"""
    if _db is None:
        return None
    cursor = await _db.execute(
        "SELECT * FROM skills WHERE user_id=? AND skill_id=?",
        (user_id, skill_id),
    )
    row = await cursor.fetchone()
    await cursor.close()
    return _row_to_dict(row) if row else None


async def create_skill(
    user_id: str, name: str, description: str, tags: str, body: str,
) -> dict:
    """创建新 skill。"""
    if _db is None:
        raise RuntimeError("Skill 系统未初始化")

    skill_id = str(uuid.uuid4())
    dir_path = _skill_dir(user_id, name)
    md_content = _build_skill_md(name, description, tags, body)

    # 写入 SKILL.md
    import aiofiles

    os.makedirs(dir_path, exist_ok=True)
    md_path = os.path.join(dir_path, "SKILL.md")
    async with aiofiles.open(md_path, "w", encoding="utf-8") as f:
        await f.write(md_content)

    now = _now()
    await _db.execute(
        "INSERT INTO skills (user_id, skill_id, name, description, shared, "
        "enabled, dir, markdown, tags, author, source_skill_id, "
        "source_version, source_updated_at, has_update, "
        "created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 0, 1, ?, ?, ?, NULL, NULL, NULL, NULL, 0, ?, ?)",
        (user_id, skill_id, name, description, dir_path, md_content,
         tags, now, now),
    )
    await _db.commit()
    logger.info("创建 skill user=%s id=%s name=%s", user_id, skill_id, name)
    return get_skill(user_id, skill_id)


async def create_skill_from_upload(
    user_id: str, content: str,
) -> tuple[dict | None, str | None]:
    """从上传的 SKILL.md 全文创建 skill。

    先校验 frontmatter 是否合规（name/description 必需、正文非空），
    再写入磁盘并入库。校验失败时返回 (None, error_msg)。

    与 ``create_skill`` 的区别：上传的 SKILL.md 已含完整 frontmatter，
    不再由系统组装 frontmatter，而是直接使用原文。
    """
    if _db is None:
        return None, "Skill 系统未初始化"

    valid, name, description, tags, body = validate_skill_md(content)
    if not valid:
        return None, description  # description 位置返回错误信息

    skill_id = str(uuid.uuid4())
    dir_path = _skill_dir(user_id, name)

    import aiofiles

    os.makedirs(dir_path, exist_ok=True)
    md_path = os.path.join(dir_path, "SKILL.md")
    async with aiofiles.open(md_path, "w", encoding="utf-8") as f:
        await f.write(content)

    now = _now()
    await _db.execute(
        "INSERT INTO skills (user_id, skill_id, name, description, shared, "
        "enabled, dir, markdown, tags, author, source_skill_id, "
        "source_version, source_updated_at, has_update, "
        "created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 0, 1, ?, ?, ?, NULL, NULL, NULL, NULL, 0, ?, ?)",
        (user_id, skill_id, name, description, dir_path, content,
         tags, now, now),
    )
    await _db.commit()
    logger.info("上传创建 skill user=%s id=%s name=%s", user_id, skill_id, name)
    return await get_skill(user_id, skill_id), None


async def update_skill(
    user_id: str, skill_id: str, name: str, description: str,
    tags: str, body: str,
) -> dict | None:
    """编辑自己的 skill 内容（自建 skill 才允许）。"""
    if _db is None:
        return None
    cursor = await _db.execute(
        "SELECT * FROM skills WHERE user_id=? AND skill_id=? AND author IS NULL",
        (user_id, skill_id),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if not row:
        return None

    dir_path = row["dir"]
    md_content = _build_skill_md(name, description, tags, body)

    import aiofiles

    os.makedirs(dir_path, exist_ok=True)
    md_path = os.path.join(dir_path, "SKILL.md")
    async with aiofiles.open(md_path, "w", encoding="utf-8") as f:
        await f.write(md_content)

    now = _now()
    await _db.execute(
        "UPDATE skills SET name=?, description=?, tags=?, markdown=?, "
        "updated_at=? WHERE user_id=? AND skill_id=?",
        (name, description, tags, md_content, now, user_id, skill_id),
    )
    await _db.commit()
    return get_skill(user_id, skill_id)


async def delete_skill(user_id: str, skill_id: str) -> bool:
    """删除 skill（自建删文件+记录，已安装删副本+记录）。"""
    if _db is None:
        return False
    cursor = await _db.execute(
        "SELECT * FROM skills WHERE user_id=? AND skill_id=?",
        (user_id, skill_id),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if not row:
        return False

    # 删除磁盘文件
    dir_path = row["dir"]
    import shutil

    try:
        if os.path.isdir(dir_path):
            shutil.rmtree(dir_path)
    except Exception as e:
        logger.warning("删除 skill 目录失败 dir=%s: %s", dir_path, e)

    await _db.execute(
        "DELETE FROM skills WHERE user_id=? AND skill_id=?",
        (user_id, skill_id),
    )
    await _db.commit()
    logger.info("删除 skill user=%s id=%s", user_id, skill_id)
    return True


async def set_shared(user_id: str, skill_id: str, shared: bool) -> bool:
    """切换自己的 skill 公开状态（仅自建 skill 有效）。"""
    if _db is None:
        return False
    now = _now()
    cursor = await _db.execute(
        "UPDATE skills SET shared=?, updated_at=? "
        "WHERE user_id=? AND skill_id=? AND author IS NULL",
        (1 if shared else 0, now, user_id, skill_id),
    )
    await _db.commit()
    return cursor.rowcount > 0


async def set_enabled(user_id: str, skill_id: str, enabled: bool) -> bool:
    """切换 skill 启用状态（自建和已安装均可）。"""
    if _db is None:
        return False
    now = _now()
    cursor = await _db.execute(
        "UPDATE skills SET enabled=?, updated_at=? "
        "WHERE user_id=? AND skill_id=?",
        (1 if enabled else 0, now, user_id, skill_id),
    )
    await _db.commit()
    return cursor.rowcount > 0


# ── 市场查询 ──────────────────────────────────────────────────────────────
async def list_market_skills(
    user_id: str,
    tag: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """浏览市场：查询全平台公开 skill（跨用户）。"""
    if _db is None:
        return {"items": [], "total": 0, "page": page, "size": size}

    query = "SELECT * FROM skills WHERE shared=1 AND author IS NULL"
    params: list = []

    if tag:
        query += " AND tags LIKE ?"
        params.append(f"%{tag}%")
    if keyword:
        query += " AND (name LIKE ? OR description LIKE ?)"
        params.extend([f"%{keyword}%", f"%{keyword}%"])

    # 总数
    count_query = f"SELECT COUNT(*) as cnt FROM ({query})"
    cursor = await _db.execute(count_query, params)
    row = await cursor.fetchone()
    await cursor.close()
    total = row["cnt"] if row else 0

    # 分页
    query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    params.extend([size, (page - 1) * size])
    cursor = await _db.execute(query, params)
    rows = await cursor.fetchall()
    await cursor.close()

    items = []
    for r in rows:
        d = _row_to_dict(r)
        d["author"] = r["user_id"]  # 市场中展示原作者 user_id
        items.append(d)

    return {"items": items, "total": total, "page": page, "size": size}


# ── 安装（快照拷贝）──────────────────────────────────────────────────────
async def install_skill(
    user_id: str, author_id: str, author_skill_id: str,
) -> dict:
    """从市场安装 skill：完整拷贝 SKILL.md 到安装者目录。"""
    if _db is None:
        raise RuntimeError("Skill 系统未初始化")

    # 1. 获取原作者 skill 记录
    cursor = await _db.execute(
        "SELECT * FROM skills WHERE user_id=? AND skill_id=? AND shared=1",
        (author_id, author_skill_id),
    )
    author_row = await cursor.fetchone()
    await cursor.close()
    if not author_row:
        raise ValueError("skill 不存在或未公开")

    # 2. 获取原作者文件版本标识
    author_md_path = os.path.join(author_row["dir"], "SKILL.md")
    if not os.path.exists(author_md_path):
        raise ValueError("原作者 skill 文件不存在")

    source_mtime = str(os.path.getmtime(author_md_path))

    # 3. 读取原作者 SKILL.md 全文
    import aiofiles

    async with aiofiles.open(author_md_path, "r", encoding="utf-8") as f:
        markdown_content = await f.read()

    # 4. 拷贝到安装者目录
    install_dir = _skill_dir(user_id, author_row["name"], installed=True)
    os.makedirs(install_dir, exist_ok=True)
    install_md_path = os.path.join(install_dir, "SKILL.md")
    async with aiofiles.open(install_md_path, "w", encoding="utf-8") as f:
        await f.write(markdown_content)

    # 5. 创建安装记录
    new_id = str(uuid.uuid4())
    now = _now()
    await _db.execute(
        "INSERT INTO skills (user_id, skill_id, name, description, shared, "
        "enabled, dir, markdown, tags, author, source_skill_id, "
        "source_version, source_updated_at, has_update, "
        "created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 0, 1, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
        (user_id, new_id, author_row["name"], author_row["description"],
         install_dir, markdown_content, author_row["tags"],
         author_id, author_skill_id, source_mtime,
         author_row["updated_at"], now, now),
    )
    await _db.commit()
    logger.info("安装 skill user=%s author=%s id=%s name=%s",
                user_id, author_id, new_id, author_row["name"])
    return get_skill(user_id, new_id)


# ── 检查更新 & 同步 ──────────────────────────────────────────────────────
async def check_updates(user_id: str) -> list[dict]:
    """检查已安装 skill 是否有原作者更新。"""
    if _db is None:
        return []
    cursor = await _db.execute(
        "SELECT * FROM skills WHERE user_id=? AND author IS NOT NULL",
        (user_id,),
    )
    rows = await cursor.fetchall()
    await cursor.close()

    updates = []
    for row in rows:
        # 查原作者的 skill 是否还存在
        cursor2 = await _db.execute(
            "SELECT * FROM skills WHERE user_id=? AND skill_id=?",
            (row["author"], row["source_skill_id"]),
        )
        author_row = await cursor2.fetchone()
        await cursor2.close()

        if author_row is None:
            # 原作者已删除，不再检查更新
            await _db.execute(
                "UPDATE skills SET has_update=0 WHERE user_id=? AND skill_id=?",
                (user_id, row["skill_id"]),
            )
            continue

        author_md = os.path.join(author_row["dir"], "SKILL.md")
        if not os.path.exists(author_md):
            await _db.execute(
                "UPDATE skills SET has_update=0 WHERE user_id=? AND skill_id=?",
                (user_id, row["skill_id"]),
            )
            continue

        current_mtime = str(os.path.getmtime(author_md))
        has_update = current_mtime != row["source_version"]

        await _db.execute(
            "UPDATE skills SET has_update=?, source_updated_at=? "
            "WHERE user_id=? AND skill_id=?",
            (1 if has_update else 0, author_row["updated_at"],
             user_id, row["skill_id"]),
        )
        if has_update:
            updates.append({
                "skill_id": row["skill_id"],
                "name": row["name"],
                "author": row["author"],
            })

    await _db.commit()
    return updates


async def sync_skill(user_id: str, skill_id: str) -> dict | None:
    """同步原作者的最新 SKILL.md 到已安装的副本。"""
    if _db is None:
        return None
    cursor = await _db.execute(
        "SELECT * FROM skills WHERE user_id=? AND skill_id=? AND author IS NOT NULL",
        (user_id, skill_id),
    )
    installed = await cursor.fetchone()
    await cursor.close()
    if not installed:
        return None

    cursor = await _db.execute(
        "SELECT * FROM skills WHERE user_id=? AND skill_id=?",
        (installed["author"], installed["source_skill_id"]),
    )
    author_row = await cursor.fetchone()
    await cursor.close()
    if not author_row:
        raise ValueError("原作者 skill 已不存在")

    author_md = os.path.join(author_row["dir"], "SKILL.md")
    if not os.path.exists(author_md):
        raise ValueError("原作者 skill 文件已不存在")

    source_mtime = str(os.path.getmtime(author_md))
    import aiofiles

    async with aiofiles.open(author_md, "r", encoding="utf-8") as f:
        markdown_content = await f.read()

    install_md = os.path.join(installed["dir"], "SKILL.md")
    async with aiofiles.open(install_md, "w", encoding="utf-8") as f:
        await f.write(markdown_content)

    now = _now()
    await _db.execute(
        "UPDATE skills SET markdown=?, source_version=?, has_update=0, "
        "updated_at=? WHERE user_id=? AND skill_id=?",
        (markdown_content, source_mtime, now, user_id, skill_id),
    )
    await _db.commit()
    return get_skill(user_id, skill_id)


# ── SharedSkillLoader：接入 SDK Toolkit ──────────────────────────────────
class SharedSkillLoader(SkillLoaderBase):
    """支持多租户 + 内网共享的 Skill 加载器。

    每次请求时从 contextvar 解析当前用户，返回该用户启用的所有 skill
    （含自建 + 已安装的他人公开 skill 的独立副本）。

    与知识库的 ``search_handles`` 设计一致——同一份 Toolkit 跨用户共享，
    通过 contextvar 按请求解析当前用户。
    """

    async def list_skills(self) -> list[Skill]:
        user_id = _current_user.get()
        if not user_id or _db is None:
            return []

        cursor = await _db.execute(
            "SELECT * FROM skills WHERE user_id=? AND enabled=1 "
            "ORDER BY updated_at DESC",
            (user_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()

        skills: list[Skill] = []
        for row in rows:
            md_path = os.path.join(row["dir"], "SKILL.md")
            if not os.path.exists(md_path):
                continue  # 跳过失效的文件（目录被外部删除等）

            try:
                mtime = os.path.getmtime(md_path)
                import aiofiles

                async with aiofiles.open(md_path, "r", encoding="utf-8") as f:
                    content = await f.read()
                # 解析 frontmatter 获取 name/description
                name, description, _body = _parse_frontmatter(content)
                if not name:
                    name = row["name"]
                if not description:
                    description = row["description"]

                skills.append(Skill(
                    name=name,
                    description=description,
                    dir=row["dir"],
                    markdown=content,
                    updated_at=mtime,
                ))
            except Exception as e:
                logger.warning("加载 skill 失败 dir=%s: %s", row["dir"], e)
                continue

        return skills


# ── 初始化入口 ────────────────────────────────────────────────────────────
async def init_skills() -> None:
    """在 lifespan 中调用，初始化 DB 和目录。"""
    SKILL_DIR.mkdir(parents=True, exist_ok=True)
    await _init_db()
    logger.info(f"Skill 根目录: {SKILL_DIR}")


async def close_skills() -> None:
    """在 lifespan 结束时调用。"""
    await _close_db()

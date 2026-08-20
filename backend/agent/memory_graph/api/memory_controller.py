"""记忆路由：主动记住 / 检索 / 画像 / 审查纠错 / 社区 / 巩固 / 反思 / 图谱可视化。

鉴权复用 office-agent 的 ``main.verify_token``（惰性导入避免循环依赖），返回 office-agent
风格的纯数据（无 envelope）。会话依赖审计库（``memory_graph.db.audit_db.get_session``）。
"""
from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from memory_graph.db.audit_db import get_session
from memory_graph.schemas.memory_schema import MemorySearchRequest, RememberRequest
from memory_graph.services.memory_service import MemoryService

router = APIRouter(prefix="/memories", tags=["memory"])

_security = HTTPBearer()
_injected_auth = None


def set_auth_dependency(fn) -> None:
    """由 main.py 注入鉴权依赖（可选）；不注入则惰性复用 main.verify_token。"""
    global _injected_auth
    _injected_auth = fn


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> str:
    if _injected_auth is not None:
        return await _injected_auth(credentials)
    from main import verify_token  # 惰性导入，避免循环依赖
    return await verify_token(credentials)


@router.post("/remember")
async def remember(
    body: RememberRequest,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    memory = await MemoryService(session).remember(user_id, body.text)
    return MemoryService.to_out_dict(memory)


@router.post("/search")
async def search_memory(
    body: MemorySearchRequest,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await MemoryService(session).search(user_id, body.query, body.top_k)


@router.get("/profile")
async def get_profile(
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await MemoryService(session).get_profile(user_id)


@router.get("/review/overview")
async def review_overview(
    days: int = 30,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await MemoryService(session).review_overview(user_id, days=days)


@router.get("/review/entities")
async def list_review_entities(
    max_confidence: float = 0.75,
    type: str | None = None,
    include_verified: bool = False,
    limit: int = 50,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await MemoryService(session).list_review_entities(
        user_id, max_confidence=max_confidence, type_=type,
        include_verified=include_verified, limit=limit,
    )


@router.post("/review/{entity_id}/confirm")
async def confirm_entity(
    entity_id: str,
    body: dict | None = None,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    reason = (body or {}).get("reason")
    return await MemoryService(session).confirm_entity(user_id, entity_id, reason)


@router.patch("/review/{entity_id}/correct")
async def correct_entity(
    entity_id: str,
    body: dict,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await MemoryService(session).correct_entity_with_reason(
        user_id, entity_id,
        name=body.get("name"), type_=body.get("type"),
        description=body.get("description"), aliases=body.get("aliases"),
        reason=body.get("reason"),
    )


@router.delete("/review/{entity_id}")
async def delete_entity_with_reason(
    entity_id: str,
    reason: str | None = None,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await MemoryService(session).delete_entity_with_reason(user_id, entity_id, reason)


@router.delete("/entity/{entity_id}")
async def delete_entity(
    entity_id: str,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await MemoryService(session).delete_entity(user_id, entity_id)
    return {"ok": True}


@router.get("/communities")
async def list_communities(
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await MemoryService(session).list_communities(user_id)


@router.get("/communities/{community_id}")
async def community_members(
    community_id: str,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await MemoryService(session).community_members(user_id, community_id)


@router.post("/recluster")
async def recluster(
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await MemoryService(session).recluster(user_id)
    return {"ok": True}


@router.post("/merge-duplicates")
async def merge_duplicates(
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    removed = await MemoryService(session).merge_duplicates(user_id)
    return {"removed": removed}


@router.post("/consolidate")
async def consolidate(
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await MemoryService(session).consolidate(user_id)


@router.get("/insights")
async def list_insights(
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await MemoryService(session).list_insights(user_id)


@router.post("/reflect")
async def reflect(
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await MemoryService(session).reflect(user_id)


@router.delete("/insights/{insight_id}")
async def delete_insight(
    insight_id: str,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await MemoryService(session).delete_insight(user_id, insight_id)
    return {"ok": True}


@router.get("/graph")
async def get_graph(
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await MemoryService(session).get_graph(user_id)


@router.get("/graph/entity/{entity_id}")
async def get_entity_subgraph(
    entity_id: str,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await MemoryService(session).get_entity_subgraph(user_id, entity_id)


@router.get("/timeline")
async def get_timeline(
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await MemoryService(session).get_timeline(user_id)


@router.get("")
async def list_memories(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = MemoryService(session)
    items, total = await service.list_memories(user_id, page, page_size)
    return {
        "total": total, "page": page, "page_size": page_size,
        "items": [service.to_out_dict(m) for m in items],
    }


@router.get("/{memory_id}")
async def get_memory(
    memory_id: str,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = MemoryService(session)
    memory = await service.get_detail(user_id, memory_id)
    return service.to_out_dict(memory)


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: str,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await MemoryService(session).delete(user_id, memory_id)
    return {"ok": True}

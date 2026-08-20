"""记忆图谱存储层冒烟测试（无需 LLM）。

验证无 Docker 原生部署下的完整存储链路：
  1. init_memory_graph() -> is_ready()=True（Neo4j schema + 审计库建表）
  2. Neo4j 写图（Dialogue->Chunk->Statement->Entity + RELATION，含 4096 维向量）
  3. 向量召回 + 全文召回（cjk）+ 一跳邻居遍历 + access 回写
  4. 可视化查询（graph_full_nodes/edges）
  5. 审计库：反思计数器 bump/reset
  6. 清理测试数据（delete_user_graph）

用法（在 backend/agent/ 下，用 agent 服务的 conda env）：
  /opt/conda/envs/office-agent/bin/python memory_graph_smoke_test.py
"""
import asyncio
import math
import random

import memory_graph
from memory_graph import runtime

TEST_USER = "__smoke_test_user__"


def fake_embedding(dim: int, seed: float) -> list[float]:
    """确定性伪向量（不依赖 Ollama）。"""
    rng = random.Random(int(seed * 1000))
    v = [rng.random() for _ in range(dim)]
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


async def main() -> int:
    from memory_graph.core.graph_models import (
        ChunkNode,
        DialogueNode,
        EntityNode,
        MentionEdge,
        RelationEdge,
        StatementNode,
    )
    from memory_graph.repositories.neo4j.memory_graph_repository import (
        MemoryGraphRepository,
    )
    from memory_graph.core.retrieval.searcher import search_memory

    dims = memory_graph.settings.embedding_dims
    print(f"[1] 初始化（audit={memory_graph.settings.audit_backend}, dims={dims}）...")
    ready = await memory_graph.init_memory_graph()
    print(f"    is_ready = {ready}")
    if not ready:
        print("    ✗ 未就绪：请确认 Neo4j 已启动（backend/install_memory_infra.sh start）")
        return 1

    repo = MemoryGraphRepository()
    # 幂等：先清掉上次残留的测试数据
    await repo.delete_user_graph(TEST_USER)

    # ── 2. 写图 ──
    print("[2] 写入测试图（Dialogue->Chunk->Statement->Entity + RELATION）...")
    dialogue = DialogueNode(user_id=TEST_USER, content="冒烟测试来源", source="manual")
    chunk = ChunkNode(user_id=TEST_USER, dialog_id=dialogue.id, content="用户在腾讯做后端开发", sequence=0)
    stmt = StatementNode(
        user_id=TEST_USER, chunk_id=chunk.id,
        statement="用户在腾讯做后端开发",
        importance=0.9, confidence=0.95,
    )
    e_user = EntityNode(
        user_id=TEST_USER, name="用户", type="生命体",
        description="测试用户", name_embedding=fake_embedding(dims, 1.0),
        importance=0.9, confidence=0.95,
    )
    e_tx = EntityNode(
        user_id=TEST_USER, name="腾讯", type="组织",
        description="用户就职的公司", name_embedding=fake_embedding(dims, 2.0),
        importance=0.8, confidence=0.9,
    )
    mentions = [
        MentionEdge(user_id=TEST_USER, statement_id=stmt.id, entity_id=e_user.id),
        MentionEdge(user_id=TEST_USER, statement_id=stmt.id, entity_id=e_tx.id),
    ]
    relations = [
        RelationEdge(
            user_id=TEST_USER, source_id=e_user.id, target_id=e_tx.id,
            predicate="属于类型", predicate_surface="在...做后端",
            statement_id=stmt.id, importance=0.8, confidence=0.9,
        )
    ]
    await repo.save_graph(
        dialogues=[dialogue], chunks=[chunk], statements=[stmt],
        entities=[e_user, e_tx], events=[], mentions=mentions,
        relations=relations, involves=[],
    )
    print(f"    写入 dialogue={dialogue.id[:8]}… entities=2 relation=1 ✓")

    # ── 3a. 向量召回（用与 e_tx 相近的伪向量，免 LLM）──────────────────
    print("[3] 向量召回（复用已存实体向量）...")
    vec = e_tx.name_embedding
    rows = await repo.search_entities_by_vector(TEST_USER, vec, 5)
    names = [r["name"] for r in rows]
    print(f"    命中: {names}")
    assert "腾讯" in names, "向量召回未命中「腾讯」"
    print("    ✓ 向量索引工作正常")

    # ── 3b. 全文召回（cjk 分词）──
    print("[4] 全文召回（cjk）...")
    rows = await repo.search_entities_by_fulltext(TEST_USER, "腾讯", 5)
    names = [r["name"] for r in rows]
    print(f"    命中: {names}")
    assert any("腾讯" in n for n in names), "全文召回未命中"
    print("    ✓ cjk 全文索引工作正常")

    # ── 3c. 一跳邻居 ──
    print("[5] 一跳邻居遍历...")
    nb = await repo.get_entity_neighbors(TEST_USER, [e_user.id])
    preds = [(r.get("predicate"), r.get("object_name")) for r in nb if r.get("predicate")]
    print(f"    邻居关系: {preds}")
    assert any(p == "属于类型" and o == "腾讯" for p, o in preds), "邻居遍历未命中关系"
    print("    ✓ 邻居遍历工作正常")

    # ── 3d. 混合检索（search_memory，用假 embed client 直接给向量）─────
    print("[6] 混合检索 search_memory ...")
    class _FakeEmbed:
        async def embed_one(self, text, dimensions=None):
            return vec
    hits = await search_memory(
        embed_client=_FakeEmbed(), user_id=TEST_USER,
        query="腾讯", top_k=5, query_vector=vec,
    )
    print(f"    命中: {[(h['name'], h['score']) for h in hits]}")
    assert hits and hits[0]["name"] == "腾讯", "混合检索未命中"
    print("    ✓ 混合检索工作正常（含 access 回写）")

    # ── 4. 可视化查询 ──
    print("[7] 可视化查询 graph_full_nodes/edges ...")
    nodes = await repo.graph_full_nodes(TEST_USER)
    edges = await repo.graph_full_edges(TEST_USER)
    print(f"    nodes={len(nodes)} edges={len(edges)}")
    # 预期：Dialogue + Chunk + Statement + 2 Entity = 5 节点；
    # HAS_CHUNK + HAS_STATEMENT + 2 MENTIONS + 1 RELATION = 5 边
    assert len(nodes) == 5 and len(edges) == 5, "可视化查询结果不完整"
    print("    ✓ 可视化查询工作正常")

    # ── 5. 反思计数器（优先 Redis，回退 SQLite）──
    print("[8] 反思计数器（Redis/SQLite）...")
    # 先 reset 保证幂等（Redis 键/SQLite 行可能残留自上次运行）
    await runtime.reset_reflection_counter(TEST_USER)
    total = await runtime.bump_reflection_counter(TEST_USER, 7)
    total2 = await runtime.bump_reflection_counter(TEST_USER, 13)
    await runtime.reset_reflection_counter(TEST_USER)
    after = await runtime.get_reflection_counter(TEST_USER)
    print(f"    7 -> 20 -> reset -> {after}")
    assert total == 7 and total2 == 20 and after == 0, "计数器行为异常"
    print("    ✓ 计数器工作正常")

    # ── 6. 清理 ──
    print("[9] 清理测试数据...")
    await repo.delete_user_graph(TEST_USER)
    remain = await repo.count_entities(TEST_USER)
    print(f"    剩余实体: {remain}")
    assert remain == 0, "清理未彻底"

    await memory_graph.close_memory_graph()
    print("\n全部通过 ✓ 存储链路（Neo4j 图/向量/全文/遍历 + SQLite 审计库）工作正常")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

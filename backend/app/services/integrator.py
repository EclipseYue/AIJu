import hashlib
import json
import math
import re
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models.schemas import (
    DecisionAction,
    IntegrationRequest,
    IntegrationResult,
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeNode,
    MergeDecision,
    TeacherFeedback,
)
from app.services.graph_builder import graph_service


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", "", name).lower()


def _embed_text(text: str, dimensions: int = 384) -> list[float]:
    vector = [0.0] * dimensions
    words = re.findall(r"[a-z0-9]+|[一-龥]", text.lower())
    for word in words:
        digest = hashlib.blake2b(word.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "little") % dimensions
        sign = 1 if digest[4] % 2 == 0 else -1
        vector[index] += sign
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def _cosine(a: list[float], b: list[float]) -> float:
    return max(0.0, sum(x * y for x, y in zip(a, b)))


class IntegrationService:
    def __init__(self) -> None:
        self._result = IntegrationResult()
        self._feedback_history: list[TeacherFeedback] = []
        self._cache_path = settings.resolve_path("data/cache/integration")

    async def run(self, payload: IntegrationRequest) -> IntegrationResult:
        graph = graph_service.current_graph()
        if not graph.nodes:
            return IntegrationResult(
                original_chars=0,
                integrated_chars=0,
                compression_ratio=0,
                decisions=[],
                graph=KnowledgeGraph(),
            )

        concept_nodes = [n for n in graph.nodes if n.category in ("核心概念", "机制", "分类", "方法")]
        all_edges = graph.edges

        # Phase 1: Name normalization + embedding similarity
        candidates = self._find_similar_pairs(concept_nodes)

        # Phase 2: LLM verification for borderline pairs
        decisions: list[MergeDecision] = []
        merged_ids: set[str] = set()
        kept_ids: set[str] = set()

        for pair in candidates:
            node_a, node_b, score, method = pair
            if node_a.id in merged_ids or node_b.id in merged_ids:
                continue

            if method == "llm":
                is_equivalent = await self._llm_judge_equivalence(node_a, node_b)
                if not is_equivalent:
                    decisions.append(MergeDecision(
                        decision_id=f"keep_{uuid.uuid4().hex[:8]}",
                        action=DecisionAction.keep,
                        affected_nodes=[node_a.id, node_b.id],
                        result_node=None,
                        reason=f"LLM 判定为相关但不等价的知识点，分别保留。",
                        confidence=score,
                    ))
                    kept_ids.add(node_a.id)
                    kept_ids.add(node_b.id)
                    continue

            # Merge: keep the node with better definition
            winner, loser = self._pick_winner(node_a, node_b, all_edges)
            merged_ids.add(loser.id)
            decisions.append(MergeDecision(
                decision_id=f"merge_{uuid.uuid4().hex[:8]}",
                action=DecisionAction.merge,
                affected_nodes=[node_a.id, node_b.id],
                result_node=winner.id,
                reason=f"名称/定义语义相似（相似度 {score:.2f}），保留定义更完整的版本。",
                confidence=score,
            ))

        # Phase 3: Identify removed nodes (low frequency, isolated)
        for node in concept_nodes:
            if node.id in merged_ids or node.id in kept_ids:
                continue
            if node.frequency <= 1 and not self._has_edges(node.id, all_edges):
                merged_ids.add(node.id)
                decisions.append(MergeDecision(
                    decision_id=f"remove_{uuid.uuid4().hex[:8]}",
                    action=DecisionAction.remove,
                    affected_nodes=[node.id],
                    result_node=None,
                    reason="低频且无关联的孤立知识点，整合时移除。",
                    confidence=0.7,
                ))

        # Phase 4: Build integrated graph
        keep_nodes = [n for n in graph.nodes if n.id not in merged_ids]
        keep_edges = [
            e for e in all_edges
            if e.source not in merged_ids and e.target not in merged_ids
        ]
        integrated_graph = KnowledgeGraph(nodes=keep_nodes, edges=keep_edges)

        # Phase 5: Compression ratio
        original_chars = sum(n.definition.__len__() for n in graph.nodes if n.category != "教材")
        integrated_chars = sum(n.definition.__len__() for n in integrated_graph.nodes if n.category != "教材")
        compression_ratio = integrated_chars / original_chars if original_chars > 0 else 0

        self._result = IntegrationResult(
            original_chars=original_chars,
            integrated_chars=integrated_chars,
            compression_ratio=round(compression_ratio, 4),
            decisions=decisions,
            graph=integrated_graph,
        )
        self._save_result()
        return self._result

    async def apply_feedback(self, payload: TeacherFeedback) -> IntegrationResult:
        self._feedback_history.append(payload)

        if not self._result.decisions:
            return self._result

        message = payload.message.strip()
        target_id = payload.decision_id

        # Parse feedback intent
        if target_id:
            for decision in self._result.decisions:
                if decision.decision_id == target_id:
                    if any(kw in message for kw in ("拆分", "分开", "不要合并", "不要merge")):
                        decision.action = DecisionAction.keep
                        decision.reason += f" 教师反馈：{message}"
                    elif any(kw in message for kw in ("保留", "恢复")):
                        decision.action = DecisionAction.keep
                        decision.reason += f" 教师反馈：{message}"
                    elif any(kw in message for kw in ("删除", "移除", "去掉")):
                        decision.action = DecisionAction.remove
                        decision.reason += f" 教师反馈：{message}"
                    elif any(kw in message for kw in ("合并", "merge")):
                        decision.action = DecisionAction.merge
                        decision.reason += f" 教师反馈：{message}"
                    else:
                        decision.reason += f" 教师反馈：{message}"
                    break
        else:
            # General feedback applied to the whole result
            self._result.decisions.append(MergeDecision(
                decision_id=f"feedback_{uuid.uuid4().hex[:8]}",
                action=DecisionAction.keep,
                affected_nodes=[],
                result_node=None,
                reason=f"教师一般性反馈：{message}",
                confidence=1.0,
            ))

        # Rebuild integrated graph based on updated decisions
        graph = graph_service.current_graph()
        removed_ids: set[str] = set()
        for d in self._result.decisions:
            if d.action == DecisionAction.remove:
                removed_ids.update(d.affected_nodes)
            elif d.action == DecisionAction.merge and d.result_node:
                for nid in d.affected_nodes:
                    if nid != d.result_node:
                        removed_ids.add(nid)

        keep_nodes = [n for n in graph.nodes if n.id not in removed_ids]
        keep_edges = [
            e for e in graph.edges
            if e.source not in removed_ids and e.target not in removed_ids
        ]
        self._result.graph = KnowledgeGraph(nodes=keep_nodes, edges=keep_edges)

        original_chars = sum(len(n.definition) for n in graph.nodes if n.category != "教材")
        integrated_chars = sum(len(n.definition) for n in self._result.graph.nodes if n.category != "教材")
        self._result.original_chars = original_chars
        self._result.integrated_chars = integrated_chars
        self._result.compression_ratio = round(
            integrated_chars / original_chars if original_chars > 0 else 0, 4
        )

        self._save_result()
        return self._result

    def _find_similar_pairs(
        self, nodes: list[KnowledgeNode]
    ) -> list[tuple[KnowledgeNode, KnowledgeNode, float, str]]:
        pairs: list[tuple[KnowledgeNode, KnowledgeNode, float, str]] = []
        n = len(nodes)
        if n < 2:
            return pairs

        # Pre-compute embeddings
        embeddings: dict[str, list[float]] = {}
        for node in nodes:
            key = node.id
            text = f"{node.name} {node.definition}"
            embeddings[key] = _embed_text(text)

        for i in range(n):
            for j in range(i + 1, n):
                a, b = nodes[i], nodes[j]
                # Quick name check
                na, nb = _normalize_name(a.name), _normalize_name(b.name)
                if na == nb:
                    pairs.append((a, b, 1.0, "exact_name"))
                    continue

                sim = _cosine(embeddings[a.id], embeddings[b.id])
                if sim >= 0.82:
                    pairs.append((a, b, sim, "embedding"))
                elif sim >= 0.78:
                    pairs.append((a, b, sim, "llm"))

        pairs.sort(key=lambda x: x[2], reverse=True)
        return pairs

    async def _llm_judge_equivalence(self, a: KnowledgeNode, b: KnowledgeNode) -> bool:
        if not settings.openai_api_key:
            return False
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                timeout=30,
            )
            response = client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是学科知识对齐专家。判断两个知识点是否等价（同一教学概念）。"
                            "只输出 JSON：{\"equivalent\": true/false, \"reason\": \"一句话理由\"}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"知识点A：名称={a.name}，定义={a.definition}，教材={a.textbook_title}，章节={a.chapter}\n"
                            f"知识点B：名称={b.name}，定义={b.definition}，教材={b.textbook_title}，章节={b.chapter}"
                        ),
                    },
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            text = response.choices[0].message.content.strip()
            result = json.loads(text)
            return bool(result.get("equivalent", False))
        except Exception:
            return False

    def _pick_winner(
        self, a: KnowledgeNode, b: KnowledgeNode, edges: list[KnowledgeEdge]
    ) -> tuple[KnowledgeNode, KnowledgeNode]:
        score_a = self._node_score(a, edges)
        score_b = self._node_score(b, edges)
        if score_a >= score_b:
            return a, b
        return b, a

    def _node_score(self, node: KnowledgeNode, edges: list[KnowledgeEdge]) -> float:
        edge_count = sum(1 for e in edges if e.source == node.id or e.target == node.id)
        return node.frequency * 2 + len(node.definition) * 0.01 + edge_count * 1.5

    def _has_edges(self, node_id: str, edges: list[KnowledgeEdge]) -> bool:
        return any(e.source == node_id or e.target == node_id for e in edges)

    def _save_result(self) -> None:
        self._cache_path.mkdir(parents=True, exist_ok=True)
        path = self._cache_path / "latest.json"
        path.write_text(self._result.model_dump_json(indent=2), encoding="utf-8")

    def load_result(self) -> IntegrationResult:
        path = self._cache_path / "latest.json"
        if path.exists():
            try:
                self._result = IntegrationResult.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except Exception:
                pass
        return self._result


integration_service = IntegrationService()

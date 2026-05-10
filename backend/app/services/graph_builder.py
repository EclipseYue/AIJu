import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models.schemas import (
    GraphBuildRequest,
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeNode,
    ParseStatus,
)
from app.services.textbook_parser import parser_service

_EXTRACT_SYSTEM_PROMPT = """你是一个学科知识抽取专家。你的任务是从教材章节正文中抽取知识点和它们之间的关系。

严格要求：
1. 只输出合法 JSON，不要输出 Markdown 代码块或任何额外文字。
2. 节点必须是可独立教学、可被问答引用的概念单元，不要抽取普通段落标题、例题、页眉页脚、参考文献。
3. 关系类型只能从以下白名单选择：prerequisite、parallel、contains、applies_to。
4. 如果章节没有可抽取的知识点，返回空 nodes 和空 edges。

输出 JSON schema：
{
  "nodes": [
    {
      "name": "知识点名称（中文）",
      "definition": "该知识点的定义或解释，50-200字",
      "category": "核心概念|机制|分类|方法"
    }
  ],
  "edges": [
    {
      "source": "起点节点name",
      "target": "终点节点name",
      "relation_type": "prerequisite|parallel|contains|applies_to",
      "description": "关系说明，一句话"
    }
  ]
}

示例输入片段：
"炎症(inflammation)是具有血管系统的活体组织对各种损伤因子的刺激所发生的以防御为主的反应。炎症的基本病理变化包括变质、渗出和增生。"

示例输出：
{
  "nodes": [
    {"name": "炎症", "definition": "具有血管系统的活体组织对各种损伤因子的刺激所发生的以防御为主的反应。", "category": "核心概念"},
    {"name": "变质", "definition": "炎症的基本病理变化之一，指炎症局部组织发生的变性和坏死。", "category": "机制"},
    {"name": "渗出", "definition": "炎症的基本病理变化之一，指炎症局部组织血管内的液体和细胞成分通过血管壁进入组织间隙。", "category": "机制"},
    {"name": "增生", "definition": "炎症的基本病理变化之一，指炎症局部组织细胞的再生和增殖。", "category": "机制"}
  ],
  "edges": [
    {"source": "炎症", "target": "变质", "relation_type": "contains", "description": "炎症包含变质这一基本病理变化。"},
    {"source": "炎症", "target": "渗出", "relation_type": "contains", "description": "炎症包含渗出这一基本病理变化。"},
    {"source": "炎症", "target": "增生", "relation_type": "contains", "description": "炎症包含增生这一基本病理变化。"},
    {"source": "变质", "target": "渗出", "relation_type": "parallel", "description": "变质、渗出、增生是炎症的三种并列基本病理变化。"}
  ]
}"""


class GraphBuilderService:
    def __init__(self) -> None:
        self._graph = KnowledgeGraph()
        self._cache_path = settings.resolve_path("data/cache/current_graph.json")
        self._chapter_cache_dir = settings.resolve_path("data/cache/graph")

    async def build(self, payload: GraphBuildRequest) -> KnowledgeGraph:
        self._chapter_cache_dir.mkdir(parents=True, exist_ok=True)
        nodes: list[KnowledgeNode] = []
        edges: list[KnowledgeEdge] = []
        concept_ids_by_chapter: dict[str, list[str]] = {}

        use_llm = bool(settings.openai_api_key)

        for textbook_id in payload.textbook_ids:
            textbook = parser_service.get_textbook(textbook_id)
            if textbook is None or textbook.parse_status != ParseStatus.completed:
                continue

            book_node_id = self._node_id("book", textbook.textbook_id)
            nodes.append(
                KnowledgeNode(
                    id=book_node_id,
                    name=textbook.title,
                    definition=f"{textbook.filename}，共 {textbook.total_pages or '-'} 页，{textbook.total_chars} 字。",
                    category="教材",
                    textbook_id=textbook.textbook_id,
                    textbook_title=textbook.title,
                    frequency=1,
                )
            )

            chapters = textbook.chapters
            if payload.max_chapters_per_book:
                chapters = chapters[: payload.max_chapters_per_book]

            previous_chapter_id: str | None = None
            for chapter in chapters:
                chapter_node_id = self._node_id("chapter", textbook.textbook_id, chapter.chapter_id)

                nodes.append(
                    KnowledgeNode(
                        id=chapter_node_id,
                        name=chapter.title,
                        definition=chapter.source_excerpt or chapter.content[:240],
                        category="章节",
                        textbook_id=textbook.textbook_id,
                        textbook_title=textbook.title,
                        chapter=chapter.title,
                        page=chapter.page_start,
                        frequency=1,
                    )
                )
                edges.append(
                    KnowledgeEdge(
                        source=book_node_id,
                        target=chapter_node_id,
                        relation_type="contains",
                        description=f"《{textbook.title}》包含章节“{chapter.title}”。",
                    )
                )
                if previous_chapter_id:
                    edges.append(
                        KnowledgeEdge(
                            source=previous_chapter_id,
                            target=chapter_node_id,
                            relation_type="prerequisite",
                            description="教材章节顺序形成默认学习前置关系。",
                        )
                    )
                previous_chapter_id = chapter_node_id

                # Try LLM extraction first, fall back to heuristic
                if use_llm:
                    concepts, raw_edges = await self._llm_extract_chapter(
                        textbook, chapter
                    )
                else:
                    concepts = self._extract_concepts(chapter.title, chapter.content)
                    raw_edges = []

                concept_ids_by_chapter[chapter_node_id] = []
                concept_name_to_id: dict[str, str] = {}
                for concept in concepts:
                    concept_node_id = self._node_id(
                        "concept", textbook.textbook_id, chapter.chapter_id, concept["name"]
                    )
                    concept_ids_by_chapter[chapter_node_id].append(concept_node_id)
                    concept_name_to_id[concept["name"]] = concept_node_id
                    nodes.append(
                        KnowledgeNode(
                            id=concept_node_id,
                            name=concept["name"],
                            definition=concept["definition"],
                            category=concept.get("category", "核心概念"),
                            textbook_id=textbook.textbook_id,
                            textbook_title=textbook.title,
                            chapter=chapter.title,
                            page=chapter.page_start,
                            frequency=1,
                            source_ids=[chapter.chapter_id],
                        )
                    )
                    edges.append(
                        KnowledgeEdge(
                            source=chapter_node_id,
                            target=concept_node_id,
                            relation_type="contains",
                            description=f"“{chapter.title}”包含知识点“{concept['name']}”。",
                        )
                    )

                # Add LLM-detected edges
                for raw_edge in raw_edges:
                    src_id = concept_name_to_id.get(raw_edge["source"])
                    tgt_id = concept_name_to_id.get(raw_edge["target"])
                    if src_id and tgt_id:
                        edges.append(
                            KnowledgeEdge(
                                source=src_id,
                                target=tgt_id,
                                relation_type=raw_edge.get("relation_type", "parallel"),
                                description=raw_edge.get("description", ""),
                            )
                        )

        self._add_parallel_edges(edges, concept_ids_by_chapter)
        self._apply_frequency(nodes)
        self._graph = KnowledgeGraph(nodes=nodes, edges=self._dedupe_edges(edges))
        self._save_graph()
        return self._graph

    async def _llm_extract_chapter(
        self, textbook: Any, chapter: Any
    ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        """Extract concepts and edges from a chapter using LLM. Returns (concepts, edges)."""
        cache_key = self._chapter_cache_key(textbook.textbook_id, chapter.chapter_id)
        cached = self._load_chapter_cache(cache_key)
        if cached is not None:
            return cached["nodes"], cached["edges"]

        content = chapter.content[:6000]
        if len(content.strip()) < 40:
            return [], []

        for attempt in range(2):
            try:
                result = await self._call_llm_extract(chapter.title, content)
                concepts = result.get("nodes", [])
                raw_edges = result.get("edges", [])
                # Validate: each node must have name and definition
                valid_concepts = [
                    c for c in concepts
                    if c.get("name") and c.get("definition") and len(c["name"]) <= 30
                ]
                valid_edges = [
                    e for e in raw_edges
                    if e.get("source") and e.get("target")
                    and e.get("relation_type") in ("prerequisite", "parallel", "contains", "applies_to")
                ]
                self._save_chapter_cache(cache_key, valid_concepts, valid_edges)
                return valid_concepts, valid_edges
            except Exception:
                if attempt == 1:
                    break
        # Fallback to heuristic
        concepts = self._extract_concepts(chapter.title, chapter.content)
        return concepts, []

    async def _call_llm_extract(
        self, chapter_title: str, content: str
    ) -> dict[str, Any]:
        """Call OpenAI-compatible API for knowledge extraction."""
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=60,
        )
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"请从以下教材章节中抽取知识点和关系：\n\n章节标题：{chapter_title}\n\n正文：\n{content}",
                },
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content.strip()
        # Strip markdown code fence if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return json.loads(text)

    def _chapter_cache_key(self, textbook_id: str, chapter_id: str) -> str:
        raw = f"{textbook_id}:{chapter_id}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def _load_chapter_cache(self, cache_key: str) -> dict[str, Any] | None:
        path = self._chapter_cache_dir / f"{cache_key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _save_chapter_cache(
        self, cache_key: str, nodes: list[dict], edges: list[dict]
    ) -> None:
        path = self._chapter_cache_dir / f"{cache_key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def current_graph(self) -> KnowledgeGraph:
        if not self._graph.nodes and self._cache_path.exists():
            self._graph = KnowledgeGraph.model_validate_json(self._cache_path.read_text(encoding="utf-8"))
        return self._graph

    def _extract_concepts(self, chapter_title: str, content: str, limit: int = 8) -> list[dict[str, str]]:
        candidates: list[str] = []
        candidates.extend(self._title_terms(chapter_title))

        parenthetical = re.findall(
            r"([\u4e00-\u9fa5][\u4e00-\u9fa5A-Za-z0-9·\-]{1,20})[（(][A-Za-z][A-Za-z0-9 ,;:·/\-]{1,80}[）)]",
            content,
        )
        candidates.extend(parenthetical)

        heading_terms = re.findall(
            r"(?:第[一二三四五六七八九十百千万0-9]+节\s*[|｜]?\s*|[一二三四五六七八九十]+、\s*)([\u4e00-\u9fa5][\u4e00-\u9fa5、和与及]{2,28})",
            content,
        )
        candidates.extend(heading_terms)

        definition_terms = re.findall(
            r"([\u4e00-\u9fa5][\u4e00-\u9fa5A-Za-z0-9·]{1,18})(?:[（(][A-Za-z][^）)]{1,60}[）)])?[^。；\n]{0,12}(?:是|指|称为|即)",
            content,
        )
        candidates.extend(definition_terms)

        concepts: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw_name in candidates:
            name = self._clean_concept(raw_name)
            if not name or name in seen:
                continue
            seen.add(name)
            concepts.append({"name": name, "definition": self._definition_for(name, content)})
            if len(concepts) >= limit:
                break
        return concepts

    def _title_terms(self, chapter_title: str) -> list[str]:
        title = re.sub(r"^第[一二三四五六七八九十百千万0-9]+章\s*", "", chapter_title).strip()
        if not title or title in {"前言/目录", "全文"}:
            return []
        return [title]

    def _clean_concept(self, value: str) -> str:
        name = re.sub(r"\s+", "", value)
        name = name.strip("，。；：:、（）()[]【】")
        blocked = {"本章数字资源", "单位", "图", "表", "教材", "医学", "人体", "功能", "结构"}
        if name in blocked or len(name) < 2 or len(name) > 24:
            return ""
        if re.fullmatch(r"\d+", name):
            return ""
        return name

    def _definition_for(self, name: str, content: str) -> str:
        sentences = re.split(r"(?<=[。！？])", content.replace("\n", " "))
        for sentence in sentences:
            sentence = re.sub(r"\s+", " ", sentence).strip()
            if name in sentence and 12 <= len(sentence) <= 220:
                return sentence
        return f"来自教材章节的知识点：{name}。"

    def _add_parallel_edges(
        self,
        edges: list[KnowledgeEdge],
        concept_ids_by_chapter: dict[str, list[str]],
    ) -> None:
        for concept_ids in concept_ids_by_chapter.values():
            for source, target in zip(concept_ids, concept_ids[1:]):
                edges.append(
                    KnowledgeEdge(
                        source=source,
                        target=target,
                        relation_type="parallel",
                        description="同一章节中并列出现的知识点。",
                    )
                )

    def _apply_frequency(self, nodes: list[KnowledgeNode]) -> None:
        concept_counts = Counter(
            self._normalize_name(node.name)
            for node in nodes
            if node.category == "核心概念"
        )
        for node in nodes:
            if node.category == "核心概念":
                node.frequency = concept_counts[self._normalize_name(node.name)]

    def _dedupe_edges(self, edges: list[KnowledgeEdge]) -> list[KnowledgeEdge]:
        deduped: list[KnowledgeEdge] = []
        seen: set[tuple[str, str, str]] = set()
        for edge in edges:
            key = (edge.source, edge.target, edge.relation_type)
            if edge.source == edge.target or key in seen:
                continue
            seen.add(key)
            deduped.append(edge)
        return deduped

    def _save_graph(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(self._graph.model_dump_json(indent=2), encoding="utf-8")

    def _node_id(self, *parts: str) -> str:
        raw = "::".join(parts)
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        return f"node_{digest}"

    def _normalize_name(self, name: str) -> str:
        return re.sub(r"\s+", "", name).lower()


graph_service = GraphBuilderService()

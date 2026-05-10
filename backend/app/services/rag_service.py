import hashlib
import json
import logging
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

from rank_bm25 import BM25Okapi

from app.core.config import settings
from app.models.schemas import (
    ChatMessage,
    Citation,
    PageSpan,
    ParseStatus,
    RagChatRequest,
    RagChatResponse,
    RagIndexRequest,
    RagQueryRequest,
    RagQueryResponse,
    RagStatus,
)
from app.services.textbook_parser import parser_service

_bge_model = None


def _get_bge_model():
    global _bge_model
    if _bge_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _bge_model = SentenceTransformer(settings.embedding_model)
        except Exception:
            _bge_model = False
    return _bge_model if _bge_model is not False else None


@dataclass
class RagChunk:
    chunk_id: str
    textbook_id: str
    textbook: str
    chapter: str
    page: int | None
    text: str
    start_char: int
    end_char: int
    vector: list[float]


class RagService:
    def __init__(self) -> None:
        self._cache_path = settings.resolve_path("data/cache/rag_index.json")
        self._chunks: list[RagChunk] = []
        self._bm25: BM25Okapi | None = None
        self._status = RagStatus()
        self._chroma_collection = None
        self._init_chroma()
        self._load_index()

    def _init_chroma(self) -> None:
        try:
            import chromadb

            client = chromadb.PersistentClient(path=str(settings.resolve_path(settings.chroma_dir)))
            self._chroma_collection = client.get_or_create_collection(
                name="textbook_chunks",
                metadata={"hnsw:space": "cosine"},
            )
        except Exception:
            self._chroma_collection = None

    async def index(self, payload: RagIndexRequest) -> RagStatus:
        chunk_size = min(800, max(500, payload.chunk_size))
        overlap_size = min(100, max(50, payload.overlap_size))
        chunks: list[RagChunk] = []
        indexed_textbooks = 0

        for textbook_id in payload.textbook_ids:
            textbook = parser_service.get_textbook(textbook_id)
            if textbook is None or textbook.parse_status != ParseStatus.completed:
                continue
            indexed_textbooks += 1
            for chapter in textbook.chapters:
                if not chapter.content.strip():
                    continue
                chunks.extend(
                    self._chunk_chapter(
                        textbook_id=textbook.textbook_id,
                        textbook_title=textbook.title,
                        chapter_title=chapter.title,
                        page_start=chapter.page_start,
                        page_end=chapter.page_end,
                        page_spans=chapter.page_spans,
                        content=chapter.content,
                        chunk_size=chunk_size,
                        overlap_size=overlap_size,
                    )
                )

        self._chunks = chunks
        self._rebuild_bm25()
        self._status = RagStatus(
            indexed_textbooks=indexed_textbooks,
            chunk_count=len(chunks),
            status="ready" if chunks else "empty",
        )
        self._save_index()
        return self._status

    async def query(self, payload: RagQueryRequest) -> RagQueryResponse:
        self._ensure_loaded()
        if not self._chunks:
            return RagQueryResponse(answer="当前知识库中未找到相关信息")

        ranked = self._retrieve(payload.question, payload.top_k, payload.textbook_ids)
        if not ranked or ranked[0][1] < 0.05:
            return RagQueryResponse(answer="当前知识库中未找到相关信息")

        source_chunks = [chunk.text for chunk, _score in ranked]
        citations = [
            Citation(
                textbook=chunk.textbook,
                chapter=chunk.chapter,
                page=chunk.page,
                relevance_score=round(float(score), 4),
            )
            for chunk, score in ranked
        ]
        answer = self._compose_answer(payload.question, ranked, citations)
        return RagQueryResponse(answer=answer, citations=citations, source_chunks=source_chunks)

    async def chat(self, payload: RagChatRequest) -> RagChatResponse:
        self._ensure_loaded()
        if not self._chunks:
            history = payload.history + [
                ChatMessage(role="user", content=payload.message),
                ChatMessage(role="assistant", content="当前知识库中未找到相关信息"),
            ]
            return RagChatResponse(answer="当前知识库中未找到相关信息", history=history)

        ranked = self._retrieve(payload.message, payload.top_k, payload.textbook_ids)
        citations = [
            Citation(
                textbook=chunk.textbook,
                chapter=chunk.chapter,
                page=chunk.page,
                relevance_score=round(float(score), 4),
            )
            for chunk, score in ranked
        ]
        answer = self._llm_chat_answer(payload.message, payload.history, ranked) or self._compose_answer(payload.message, ranked, citations)
        history = payload.history + [
            ChatMessage(role="user", content=payload.message),
            ChatMessage(role="assistant", content=answer),
        ]
        return RagChatResponse(
            answer=answer,
            history=history[-12:],
            citations=citations,
            source_chunks=[chunk.text for chunk, _score in ranked],
        )

    def status(self) -> RagStatus:
        self._ensure_loaded()
        return self._status

    def _chunk_chapter(
        self,
        textbook_id: str,
        textbook_title: str,
        chapter_title: str,
        page_start: int | None,
        page_end: int | None,
        page_spans: list[PageSpan],
        content: str,
        chunk_size: int,
        overlap_size: int,
    ) -> list[RagChunk]:
        text = self._normalize_text(content)
        if not text:
            return []
        chunks: list[RagChunk] = []
        step = max(1, chunk_size - overlap_size)
        for start in range(0, len(text), step):
            end = min(len(text), start + chunk_size)
            chunk_text = text[start:end].strip()
            if len(chunk_text) < 40 and chunks:
                break
            page = self._page_for_chunk(page_spans, page_start, page_end, start, end, len(text))
            chunk_id = self._chunk_id(textbook_id, chapter_title, start, end)
            chunks.append(
                RagChunk(
                    chunk_id=chunk_id,
                    textbook_id=textbook_id,
                    textbook=textbook_title,
                    chapter=chapter_title,
                    page=page,
                    text=chunk_text,
                    start_char=start,
                    end_char=end,
                    vector=self._embed(chunk_text),
                )
            )
            if end == len(text):
                break
        return chunks

    def _retrieve(self, question: str, top_k: int, textbook_ids: list[str] | None = None) -> list[tuple[RagChunk, float]]:
        allowed = set(textbook_ids or [])
        chunks = [chunk for chunk in self._chunks if not allowed or chunk.textbook_id in allowed]
        if not chunks:
            return []
        query_vector = self._embed(question)
        vector_scores = [self._cosine(query_vector, chunk.vector) for chunk in chunks]
        scoped_bm25 = BM25Okapi([self._tokenize(chunk.text) for chunk in chunks])
        bm25_scores = scoped_bm25.get_scores(self._tokenize(question)).tolist()
        normalized_bm25 = self._normalize_scores(bm25_scores)
        combined = [
            (chunk, 0.68 * vector_scores[index] + 0.32 * normalized_bm25[index])
            for index, chunk in enumerate(chunks)
        ]
        combined.sort(key=lambda item: item[1], reverse=True)
        deduped: list[tuple[RagChunk, float]] = []
        seen: set[tuple[str, str, int | None]] = set()
        for chunk, score in combined:
            key = (chunk.textbook, chunk.chapter, chunk.page)
            if key in seen:
                continue
            seen.add(key)
            deduped.append((chunk, score))
            if len(deduped) >= max(1, top_k):
                break
        return deduped

    def _compose_answer(
        self,
        question: str,
        ranked: list[tuple[RagChunk, float]],
        citations: list[Citation],
    ) -> str:
        query_terms = set(self._tokenize(question))
        sentences: list[str] = []
        for chunk, _score in ranked:
            for sentence in self._split_sentences(chunk.text):
                sentence_terms = set(self._tokenize(sentence))
                if query_terms & sentence_terms and 18 <= len(sentence) <= 220:
                    sentences.append(sentence)
                if len(sentences) >= 3:
                    break
            if len(sentences) >= 3:
                break
        if not sentences:
            sentences = [ranked[0][0].text[:220]]

        fallback_body = " ".join(sentences)
        citation_text = " ".join(
            f"[{item.textbook}, {item.chapter}, 第{item.page or '-'}页]"
            for item in citations[: min(2, len(citations))]
        )
        answer_body = self._llm_answer(question, ranked) or fallback_body
        return f"{answer_body} {citation_text}".strip()

    def _llm_answer(self, question: str, ranked: list[tuple[RagChunk, float]]) -> str:
        if not settings.openai_api_key:
            return ""
        try:
            from openai import OpenAI

            context = "\n\n".join(
                f"[来源{i + 1}] {chunk.textbook} / {chunk.chapter} / 第{chunk.page or '-'}页\n{chunk.text}"
                for i, (chunk, _score) in enumerate(ranked)
            )
            client = OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                timeout=20,
            )
            response = client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是教材 RAG 问答助手。只能基于提供的上下文回答；"
                            "如果上下文不足，回答“当前知识库中未找到相关信息”。"
                            "回答要简洁，不要编造来源。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"问题：{question}\n\n上下文：\n{context}",
                    },
                ],
                temperature=0.2,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            return ""

    def _llm_chat_answer(
        self,
        message: str,
        history: list[ChatMessage],
        ranked: list[tuple[RagChunk, float]],
    ) -> str:
        if settings.anthropic_auth_token:
            return self._anthropic_answer(message, history, ranked)
        return self._llm_answer(message, ranked)

    def _anthropic_answer(
        self,
        message: str,
        history: list[ChatMessage],
        ranked: list[tuple[RagChunk, float]],
    ) -> str:
        if not settings.anthropic_base_url or not settings.anthropic_model:
            return ""
        try:
            import httpx

            context = "\n\n".join(
                f"[来源{i + 1}] {chunk.textbook} / {chunk.chapter} / 第{chunk.page or '-'}页\n{chunk.text}"
                for i, (chunk, _score) in enumerate(ranked)
            )
            messages = [
                {"role": item.role if item.role in {"user", "assistant"} else "user", "content": item.content}
                for item in history[-8:]
            ]
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"用户问题：{message}\n\n"
                        f"可用教材上下文：\n{context}\n\n"
                        "请只基于上下文回答，必要时说明依据的教材章节页码；"
                        "如果上下文不足，回答“当前知识库中未找到相关信息”。"
                    ),
                }
            )
            response = httpx.post(
                f"{settings.anthropic_base_url.rstrip('/')}/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_auth_token,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": settings.anthropic_model,
                    "max_tokens": 1200,
                    "temperature": 0.2,
                    "system": "你是教材范围内的教学助理，必须基于提供的教材上下文回答。",
                    "messages": messages,
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            parts = data.get("content", [])
            return "".join(part.get("text", "") for part in parts if part.get("type") == "text").strip()
        except Exception:
            return ""

    def _rebuild_bm25(self) -> None:
        tokenized = [self._tokenize(chunk.text) for chunk in self._chunks]
        self._bm25 = BM25Okapi(tokenized) if tokenized else None

    def _embed(self, text: str, dimensions: int = 384) -> list[float]:
        bge = _get_bge_model()
        if bge is not None:
            try:
                vec = bge.encode(text, normalize_embeddings=True)
                return vec.tolist()
            except Exception:
                pass
        # Fallback: hash-based pseudo-embedding
        vector = [0.0] * dimensions
        tokens = self._tokenize(text)
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % dimensions
            sign = 1 if digest[4] % 2 == 0 else -1
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def _cosine(self, left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        return max(0.0, sum(a * b for a, b in zip(left, right)))

    def _normalize_scores(self, scores: list[float]) -> list[float]:
        if not scores:
            return []
        high = max(scores)
        if high <= 0:
            return [0.0 for _ in scores]
        return [float(score) / high for score in scores]

    def _tokenize(self, text: str) -> list[str]:
        text = text.lower()
        words = re.findall(r"[a-z0-9]+|[\u4e00-\u9fa5]", text)
        bigrams = [text[index:index + 2] for index in range(max(0, len(text) - 1)) if self._is_chinese_bigram(text[index:index + 2])]
        return words + bigrams

    def _is_chinese_bigram(self, value: str) -> bool:
        return len(value) == 2 and all("\u4e00" <= char <= "\u9fff" for char in value)

    def _split_sentences(self, text: str) -> list[str]:
        return [
            sentence.strip()
            for sentence in re.split(r"(?<=[。！？；])", text)
            if sentence.strip()
        ]

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()

    def _page_for_chunk(
        self,
        page_spans: list[PageSpan],
        page_start: int | None,
        page_end: int | None,
        start_char: int,
        end_char: int,
        total_chars: int,
    ) -> int | None:
        if page_spans:
            midpoint = (start_char + end_char) // 2
            for span in page_spans:
                if span.start_char <= midpoint <= span.end_char:
                    return span.page
            for span in page_spans:
                if span.start_char <= start_char <= span.end_char:
                    return span.page
        if page_start is None:
            return None
        if not page_end or page_end <= page_start or total_chars <= 0:
            return page_start
        offset = int((page_end - page_start) * (start_char / total_chars))
        return page_start + offset

    def _chunk_id(self, textbook_id: str, chapter_title: str, start: int, end: int) -> str:
        raw = f"{textbook_id}:{chapter_title}:{start}:{end}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _save_index(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": self._status.model_dump(mode="json"),
            "chunks": [asdict(chunk) for chunk in self._chunks],
        }
        self._cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        # Also push to Chroma if available
        if self._chroma_collection is not None and self._chunks:
            try:
                self._chroma_collection.delete(where={})
                batch_size = 128
                for i in range(0, len(self._chunks), batch_size):
                    batch = self._chunks[i : i + batch_size]
                    self._chroma_collection.add(
                        ids=[c.chunk_id for c in batch],
                        embeddings=[c.vector for c in batch],
                        documents=[c.text for c in batch],
                        metadatas=[
                            {
                                "textbook_id": c.textbook_id,
                                "textbook": c.textbook,
                                "chapter": c.chapter,
                                "page": c.page or 0,
                            }
                            for c in batch
                        ],
                    )
            except Exception:
                pass

    def _load_index(self) -> None:
        if not self._cache_path.exists():
            return
        data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        self._status = RagStatus.model_validate(data.get("status", {}))
        self._chunks = [RagChunk(**chunk) for chunk in data.get("chunks", [])]
        self._rebuild_bm25()

    def _ensure_loaded(self) -> None:
        if not self._chunks and self._cache_path.exists():
            self._load_index()


rag_service = RagService()

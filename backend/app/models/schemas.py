from enum import Enum

from pydantic import BaseModel, Field


class ParseStatus(str, Enum):
    pending = "pending"
    parsing = "parsing"
    completed = "completed"
    failed = "failed"


class DecisionAction(str, Enum):
    merge = "merge"
    keep = "keep"
    remove = "remove"


class Chapter(BaseModel):
    chapter_id: str
    title: str
    page_start: int | None = None
    page_end: int | None = None
    content: str = ""
    char_count: int = 0
    source_excerpt: str | None = None
    page_spans: list["PageSpan"] = Field(default_factory=list)


class PageSpan(BaseModel):
    page: int
    start_char: int
    end_char: int


class TextbookSummary(BaseModel):
    textbook_id: str
    filename: str
    title: str
    file_format: str
    size_bytes: int = 0
    total_pages: int | None = None
    total_chars: int = 0
    parse_status: ParseStatus = ParseStatus.pending
    chapters: list[Chapter] = Field(default_factory=list)
    error: str | None = None
    source_path: str | None = None
    content_hash: str | None = None


class ParseRequest(BaseModel):
    force: bool = False
    chapter_pattern: str = r"第[一二三四五六七八九十百千万0-9]+章"


class KnowledgeNode(BaseModel):
    id: str
    name: str
    definition: str = ""
    category: str = "核心概念"
    textbook_id: str | None = None
    textbook_title: str | None = None
    chapter: str | None = None
    page: int | None = None
    frequency: int = 1
    source_ids: list[str] = Field(default_factory=list)


class KnowledgeEdge(BaseModel):
    source: str
    target: str
    relation_type: str
    description: str = ""


class KnowledgeGraph(BaseModel):
    nodes: list[KnowledgeNode] = Field(default_factory=list)
    edges: list[KnowledgeEdge] = Field(default_factory=list)


class GraphBuildRequest(BaseModel):
    textbook_ids: list[str]
    max_chapters_per_book: int | None = None


class MergeDecision(BaseModel):
    decision_id: str
    action: DecisionAction
    affected_nodes: list[str]
    result_node: str | None = None
    reason: str
    confidence: float = Field(ge=0, le=1)


class IntegrationRequest(BaseModel):
    textbook_ids: list[str]
    compression_target: float = Field(default=0.30, gt=0, le=1)


class IntegrationResult(BaseModel):
    original_chars: int = 0
    integrated_chars: int = 0
    compression_ratio: float = 0
    decisions: list[MergeDecision] = Field(default_factory=list)
    graph: KnowledgeGraph = Field(default_factory=KnowledgeGraph)


class TeacherFeedback(BaseModel):
    session_id: str = "default"
    message: str
    decision_id: str | None = None


class RagIndexRequest(BaseModel):
    textbook_ids: list[str]
    chunk_size: int = 650
    overlap_size: int = 80


class Citation(BaseModel):
    textbook: str
    chapter: str
    page: int | None = None
    relevance_score: float


class RagQueryRequest(BaseModel):
    question: str
    top_k: int = 5
    textbook_ids: list[str] = Field(default_factory=list)


class RagQueryResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    source_chunks: list[str] = Field(default_factory=list)


class RagStatus(BaseModel):
    indexed_textbooks: int = 0
    chunk_count: int = 0
    status: str = "not_started"


class ChatMessage(BaseModel):
    role: str
    content: str


class RagChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = Field(default_factory=list)
    textbook_ids: list[str] = Field(default_factory=list)
    top_k: int = 5


class RagChatResponse(BaseModel):
    answer: str
    history: list[ChatMessage] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    source_chunks: list[str] = Field(default_factory=list)


class CleanupResult(BaseModel):
    removed_records: int = 0
    removed_files: int = 0
    cleared_cache_files: int = 0
    remaining_textbooks: int = 0


class ReportSummary(BaseModel):
    textbook_count: int = 0
    original_chars: int = 0
    integrated_chars: int = 0
    compression_ratio: float = 0
    merge_count: int = 0
    keep_count: int = 0
    remove_count: int = 0

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pypdf import PdfReader

from app.core.config import settings
from app.models.schemas import Chapter, CleanupResult, PageSpan, ParseRequest, ParseStatus, TextbookSummary
from app.storage.database import database

if TYPE_CHECKING:
    from fastapi import UploadFile


@dataclass(frozen=True)
class PageText:
    page_number: int
    lines: list[str]


class TextbookParserService:
    """Textbook registry backed by SQLite, with parsed chapter payloads persisted."""

    def __init__(self) -> None:
        self._cache_dir = settings.resolve_path("data/cache")
        self._registry_path = self._cache_dir / "textbooks.json"
        self._textbooks: dict[str, TextbookSummary] = {}
        self._load_registry()

    async def register_upload(self, file: "UploadFile") -> TextbookSummary:
        upload_dir = settings.resolve_path(settings.upload_dir)
        upload_dir.mkdir(parents=True, exist_ok=True)
        content = await file.read()
        safe_name = Path(file.filename or "uploaded_textbook").name
        content_hash = self._content_hash(content)
        existing = self._find_by_hash(content_hash)
        if existing:
            return existing
        textbook_id = f"book_{uuid4().hex[:8]}"
        target = upload_dir / f"{textbook_id}_{safe_name}"
        target.write_bytes(content)
        summary = TextbookSummary(
            textbook_id=textbook_id,
            filename=safe_name,
            title=Path(safe_name).stem,
            file_format=Path(safe_name).suffix.lower().lstrip("."),
            size_bytes=len(content),
            source_path=str(target),
            content_hash=content_hash,
        )
        self._textbooks[textbook_id] = summary
        self._save_registry()
        return summary

    def register_local_file(self, path: str | Path) -> TextbookSummary:
        source = Path(path)
        content = source.read_bytes()
        content_hash = self._content_hash(content)
        existing = self._find_by_hash(content_hash)
        if existing:
            # Update source_path if the file has moved (e.g., pytest tmp_path)
            if existing.source_path != str(source) and Path(str(source)).exists():
                existing.source_path = str(source)
                self._save_registry()
            return existing
        textbook_id = f"book_{uuid4().hex[:8]}"
        summary = TextbookSummary(
            textbook_id=textbook_id,
            filename=source.name,
            title=source.stem,
            file_format=source.suffix.lower().lstrip("."),
            size_bytes=source.stat().st_size,
            source_path=str(source),
            content_hash=content_hash,
        )
        self._textbooks[textbook_id] = summary
        self._save_registry()
        return summary

    def list_textbooks(self) -> list[TextbookSummary]:
        return list(self._textbooks.values())

    def get_textbook(self, textbook_id: str) -> TextbookSummary | None:
        return self._textbooks.get(textbook_id)

    def cleanup_duplicates_and_runtime_cache(self) -> CleanupResult:
        removed_records = 0
        removed_files = 0
        seen_hashes: set[str] = set()
        duplicate_ids: list[str] = []

        for summary in list(self._textbooks.values()):
            if not summary.content_hash and summary.source_path and Path(summary.source_path).exists():
                summary.content_hash = self._hash_file(Path(summary.source_path))
                database.upsert_textbook(summary)
            if not summary.content_hash:
                continue
            if summary.content_hash in seen_hashes:
                duplicate_ids.append(summary.textbook_id)
                if summary.source_path and self._safe_unlink(Path(summary.source_path)):
                    removed_files += 1
            else:
                seen_hashes.add(summary.content_hash)

        for textbook_id in duplicate_ids:
            self._textbooks.pop(textbook_id, None)
        removed_records += database.delete_textbooks(duplicate_ids)

        for cache_name in ("current_graph.json", "rag_index.json"):
            cache_path = self._cache_dir / cache_name
            if self._safe_unlink(cache_path):
                removed_files += 1

        if self._safe_unlink(self._registry_path):
            removed_files += 1
        self._save_registry()
        return CleanupResult(
            removed_records=removed_records,
            removed_files=removed_files,
            cleared_cache_files=removed_files,
            remaining_textbooks=len(self._textbooks),
        )

    async def parse_textbook(self, textbook_id: str, payload: ParseRequest) -> TextbookSummary:
        summary = self._textbooks.get(textbook_id)
        if summary is None:
            return TextbookSummary(
                textbook_id=textbook_id,
                filename="",
                title="Unknown",
                file_format="",
                parse_status=ParseStatus.failed,
                error="Textbook not found",
            )
        if summary.parse_status == ParseStatus.completed and not payload.force:
            return summary
        summary.parse_status = ParseStatus.parsing
        self._save_registry()
        try:
            parsed = self._parse_path(Path(summary.source_path or ""), payload)
            summary.total_pages = parsed["total_pages"]
            summary.chapters = parsed["chapters"]
            summary.total_chars = sum(ch.char_count for ch in summary.chapters)
            summary.parse_status = ParseStatus.completed
            summary.error = None
        except Exception as exc:  # Keep API resilient during hackathon demos.
            summary.parse_status = ParseStatus.failed
            summary.error = str(exc)
        self._save_registry()
        return summary

    def parse_local_file(self, path: str | Path, payload: ParseRequest | None = None) -> TextbookSummary:
        summary = self.register_local_file(path)
        parsed = self._parse_path(Path(summary.source_path or ""), payload or ParseRequest())
        summary.total_pages = parsed["total_pages"]
        summary.chapters = parsed["chapters"]
        summary.total_chars = sum(ch.char_count for ch in summary.chapters)
        summary.parse_status = ParseStatus.completed
        self._textbooks[summary.textbook_id] = summary
        self._save_registry()
        return summary

    def _parse_path(self, path: Path, payload: ParseRequest) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Textbook file not found: {path}")
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._parse_pdf(path, payload.chapter_pattern)
        if suffix in {".md", ".markdown"}:
            return self._parse_markdown(path, payload.chapter_pattern)
        if suffix == ".txt":
            return self._parse_plain_text(path, payload.chapter_pattern)
        raise ValueError(f"Unsupported file format for parser scaffold: {suffix}")

    def _parse_pdf(self, path: Path, chapter_pattern: str) -> dict[str, Any]:
        raw_pages = self._read_pdf_pages(path)
        pages = self._filter_repeated_headers(raw_pages)
        chapters = self._chapters_from_pages(pages, chapter_pattern)
        return {"total_pages": len(raw_pages), "chapters": chapters}

    def _read_pdf_pages(self, path: Path) -> list[PageText]:
        try:
            import fitz

            with fitz.open(path) as document:
                return [
                    PageText(page_number=index + 1, lines=self._normal_lines(page.get_text("text")))
                    for index, page in enumerate(document)
                ]
        except Exception:
            reader = PdfReader(str(path))
            return [
                PageText(page_number=index + 1, lines=self._normal_lines(page.extract_text() or ""))
                for index, page in enumerate(reader.pages)
            ]

    def _parse_markdown(self, path: Path, chapter_pattern: str) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        chapters = self._chapters_from_text(text, chapter_pattern, markdown=True)
        return {"total_pages": None, "chapters": chapters}

    def _parse_plain_text(self, path: Path, chapter_pattern: str) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        chapters = self._chapters_from_text(text, chapter_pattern, markdown=False)
        return {"total_pages": None, "chapters": chapters}

    def _chapters_from_pages(self, pages: list[PageText], chapter_pattern: str) -> list[Chapter]:
        pattern = re.compile(chapter_pattern)
        markers: list[tuple[int, int, str]] = []
        seen_titles: set[str] = set()
        for page_index, page in enumerate(pages):
            page_matches = [
                (line_index, line)
                for line_index, line in enumerate(page.lines)
                if self._is_chapter_line(line, pattern)
            ]
            if len(page_matches) > 3 or self._looks_like_toc(page.lines):
                continue
            for line_index, line in page_matches:
                title = self._chapter_title_from_line(page.lines, line_index, pattern)
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                markers.append((page_index, line_index, title))

        if not markers:
            full_text = "\n".join("\n".join(page.lines) for page in pages).strip()
            return [self._chapter("ch_001", "全文", 1, len(pages), full_text)]

        chapters: list[Chapter] = []
        if markers[0][0] > 0:
            preface_text, preface_spans = self._collect_page_segment(pages, (0, 0), markers[0][:2])
            if preface_text.strip():
                chapters.append(self._chapter("ch_001", "前言/目录", 1, pages[markers[0][0]].page_number, preface_text, preface_spans))

        for marker_index, marker in enumerate(markers):
            next_marker = markers[marker_index + 1] if marker_index + 1 < len(markers) else None
            start = marker[:2]
            end = next_marker[:2] if next_marker else (len(pages) - 1, len(pages[-1].lines))
            content, page_spans = self._collect_page_segment(pages, start, end)
            page_start = pages[marker[0]].page_number
            page_end = pages[end[0]].page_number if next_marker and end[1] > 0 else pages[end[0]].page_number
            chapters.append(self._chapter(f"ch_{len(chapters) + 1:03d}", marker[2], page_start, page_end, content, page_spans))
        return [chapter for chapter in chapters if chapter.char_count > 0]

    def _chapters_from_text(self, text: str, chapter_pattern: str, markdown: bool) -> list[Chapter]:
        lines = self._normal_lines(text)
        chapter_re = re.compile(chapter_pattern)
        heading_re = re.compile(r"^#{1,6}\s+(.+)$")
        markers: list[tuple[int, str]] = []
        for index, line in enumerate(lines):
            if markdown and (match := heading_re.match(line)):
                markers.append((index, self._clean_title(match.group(1))))
            elif self._is_chapter_line(line, chapter_re):
                markers.append((index, self._clean_title(line)))
        if not markers:
            return [self._chapter("ch_001", "全文", None, None, "\n".join(lines))]

        chapters: list[Chapter] = []
        for marker_index, marker in enumerate(markers):
            next_line = markers[marker_index + 1][0] if marker_index + 1 < len(markers) else len(lines)
            content = "\n".join(lines[marker[0]:next_line])
            chapters.append(self._chapter(f"ch_{marker_index + 1:03d}", marker[1], None, None, content))
        return [chapter for chapter in chapters if chapter.char_count > 0]

    def _chapter(
        self,
        chapter_id: str,
        title: str,
        page_start: int | None,
        page_end: int | None,
        content: str,
        page_spans: list[PageSpan] | None = None,
    ) -> Chapter:
        normalized = self._normalize_text(content)
        return Chapter(
            chapter_id=chapter_id,
            title=title,
            page_start=page_start,
            page_end=page_end,
            content=normalized,
            char_count=len(normalized),
            source_excerpt=normalized[:240],
            page_spans=page_spans or [],
        )

    def _collect_page_segment(
        self,
        pages: list[PageText],
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> tuple[str, list[PageSpan]]:
        chunks: list[str] = []
        page_spans: list[PageSpan] = []
        cursor = 0
        start_page, start_line = start
        end_page, end_line = end
        for page_index in range(start_page, end_page + 1):
            lines = pages[page_index].lines
            left = start_line if page_index == start_page else 0
            right = end_line if page_index == end_page else len(lines)
            page_text = self._normalize_text("\n".join(lines[left:right]))
            if not page_text:
                continue
            if chunks:
                cursor += 1
            start_char = cursor
            cursor += len(page_text)
            page_spans.append(PageSpan(page=pages[page_index].page_number, start_char=start_char, end_char=cursor))
            chunks.append(page_text)
        return " ".join(chunks), page_spans

    def _filter_repeated_headers(self, pages: list[PageText]) -> list[PageText]:
        counts: dict[str, int] = {}
        for page in pages:
            candidates = page.lines[:2] + page.lines[-2:]
            for line in candidates:
                key = self._header_key(line)
                if key:
                    counts[key] = counts.get(key, 0) + 1
        threshold = max(3, int(len(pages) * 0.18))
        repeated = {key for key, count in counts.items() if count >= threshold}
        filtered: list[PageText] = []
        for page in pages:
            lines = [
                line
                for line in page.lines
                if self._header_key(line) not in repeated and not re.fullmatch(r"第?\s*\d+\s*页?", line)
            ]
            filtered.append(PageText(page_number=page.page_number, lines=lines))
        return filtered

    def _normal_lines(self, text: str) -> list[str]:
        return [line for raw in text.splitlines() if (line := self._normalize_text(raw))]

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()

    def _header_key(self, line: str) -> str:
        key = re.sub(r"\d+", "#", self._normalize_text(line))
        return key if 2 <= len(key) <= 80 else ""

    def _looks_like_toc(self, lines: list[str]) -> bool:
        joined = " ".join(lines[:20])
        dotted_lines = sum(1 for line in lines if "..." in line or "…" in line)
        return "目录" in joined or dotted_lines >= 3

    def _is_chapter_line(self, line: str, pattern: re.Pattern[str]) -> bool:
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith(('"', "'", "{", "}", "[", "]")):
            return False
        if '"chapter"' in lowered or "'chapter'" in lowered or "chapter_id" in lowered:
            return False
        match = pattern.match(stripped)
        if not match:
            return False
        after = stripped[match.end():].strip()
        if after.startswith((")", "）", "，", "。", "、", "；", ",", ".", "：", ":")):
            return False
        if len(stripped) > 50:
            return False
        if "..." in line or "…" in line:
            return False
        return True

    def _clean_title(self, line: str) -> str:
        return re.sub(r"\s+", " ", line).strip(" -—\t")

    def _chapter_title_from_line(self, lines: list[str], line_index: int, pattern: re.Pattern[str]) -> str:
        title = self._clean_title(lines[line_index])
        if pattern.fullmatch(title):
            fragments: list[str] = []
            for next_line in lines[line_index + 1: line_index + 4]:
                fragment = self._clean_title(next_line)
                if not fragment or pattern.match(fragment):
                    break
                if fragment in {"本章数字资源"} or re.fullmatch(r"\d+", fragment):
                    break
                if len(fragment) > 16 or re.search(r"[，。；：,.!?！？]", fragment):
                    break
                fragments.append(fragment)
            if fragments:
                return f"{title} {''.join(fragments)}"
        return title

    def _load_registry(self) -> None:
        database.migrate_json_registry(self._registry_path)
        self._textbooks = {summary.textbook_id: summary for summary in database.list_textbooks()}
        for summary in self._textbooks.values():
            if not summary.content_hash and summary.source_path and Path(summary.source_path).exists():
                summary.content_hash = self._hash_file(Path(summary.source_path))
                database.upsert_textbook(summary)

    def _save_registry(self) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        for summary in self._textbooks.values():
            database.upsert_textbook(summary)

    def _find_by_hash(self, content_hash: str) -> TextbookSummary | None:
        for summary in self._textbooks.values():
            if summary.content_hash == content_hash:
                return summary
        existing = database.get_by_hash(content_hash)
        if existing:
            self._textbooks[existing.textbook_id] = existing
        return existing

    def _content_hash(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def _hash_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _safe_unlink(self, path: Path) -> bool:
        try:
            if path.exists() and path.is_file():
                path.unlink()
                return True
        except OSError:
            return False
        return False


parser_service = TextbookParserService()

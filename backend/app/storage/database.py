import json
import sqlite3
from pathlib import Path
from typing import Iterable

from app.core.config import settings
from app.models.schemas import TextbookSummary


class AppDatabase:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = settings.resolve_path(path or settings.database_path) if not path or not Path(path).is_absolute() else Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS textbooks (
                    textbook_id TEXT PRIMARY KEY,
                    content_hash TEXT,
                    filename TEXT NOT NULL,
                    title TEXT NOT NULL,
                    file_format TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    total_pages INTEGER,
                    total_chars INTEGER NOT NULL,
                    parse_status TEXT NOT NULL,
                    error TEXT,
                    source_path TEXT,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_textbooks_content_hash
                ON textbooks(content_hash)
                WHERE content_hash IS NOT NULL
                """
            )

    def list_textbooks(self) -> list[TextbookSummary]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM textbooks ORDER BY updated_at DESC, filename ASC"
            ).fetchall()
        return [TextbookSummary.model_validate_json(row["payload_json"]) for row in rows]

    def get_by_hash(self, content_hash: str) -> TextbookSummary | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM textbooks WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
        return TextbookSummary.model_validate_json(row["payload_json"]) if row else None

    def upsert_textbook(self, summary: TextbookSummary) -> None:
        payload = summary.model_dump_json()
        with self.connect() as connection:
            if summary.content_hash:
                duplicate = connection.execute(
                    "SELECT textbook_id FROM textbooks WHERE content_hash = ?",
                    (summary.content_hash,),
                ).fetchone()
                if duplicate and duplicate["textbook_id"] != summary.textbook_id:
                    return
            connection.execute(
                """
                INSERT INTO textbooks (
                    textbook_id, content_hash, filename, title, file_format, size_bytes,
                    total_pages, total_chars, parse_status, error, source_path, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(textbook_id) DO UPDATE SET
                    content_hash=excluded.content_hash,
                    filename=excluded.filename,
                    title=excluded.title,
                    file_format=excluded.file_format,
                    size_bytes=excluded.size_bytes,
                    total_pages=excluded.total_pages,
                    total_chars=excluded.total_chars,
                    parse_status=excluded.parse_status,
                    error=excluded.error,
                    source_path=excluded.source_path,
                    payload_json=excluded.payload_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    summary.textbook_id,
                    summary.content_hash,
                    summary.filename,
                    summary.title,
                    summary.file_format,
                    summary.size_bytes,
                    summary.total_pages,
                    summary.total_chars,
                    summary.parse_status.value,
                    summary.error,
                    summary.source_path,
                    payload,
                ),
            )

    def delete_textbooks(self, textbook_ids: Iterable[str]) -> int:
        ids = list(textbook_ids)
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as connection:
            cursor = connection.execute(f"DELETE FROM textbooks WHERE textbook_id IN ({placeholders})", ids)
            return cursor.rowcount

    def migrate_json_registry(self, registry_path: Path) -> None:
        if not registry_path.exists():
            return
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        for item in data:
            summary = TextbookSummary.model_validate(item)
            if summary.content_hash and self.get_by_hash(summary.content_hash):
                continue
            self.upsert_textbook(summary)


database = AppDatabase()

"""Parse one external textbook and print the detected chapter summary."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models.schemas import ParseRequest
from app.services.textbook_parser import TextbookParserService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="PDF, Markdown, or TXT file path")
    parser.add_argument("--max-chapters", type=int, default=12)
    args = parser.parse_args()

    service = TextbookParserService()
    summary = service.parse_local_file(args.path, ParseRequest())
    print(f"{summary.filename}: status={summary.parse_status}, pages={summary.total_pages}, chars={summary.total_chars}")
    for chapter in summary.chapters[: args.max_chapters]:
        print(
            f"{chapter.chapter_id}\t{chapter.title}\t"
            f"pages={chapter.page_start}-{chapter.page_end}\tchars={chapter.char_count}"
        )


if __name__ == "__main__":
    main()

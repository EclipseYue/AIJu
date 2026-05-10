from pathlib import Path

from app.models.schemas import ParseStatus
from app.services.textbook_parser import TextbookParserService


def test_plain_text_chapter_split(tmp_path: Path) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text(
        "第一章 绪论\n生理学是研究生命活动规律的科学。\n"
        "第二章 细胞\n细胞膜具有选择通透性。\n",
        encoding="utf-8",
    )
    service = TextbookParserService()
    summary = service.parse_local_file(sample)

    assert summary.parse_status == ParseStatus.completed
    assert len(summary.chapters) == 2
    assert summary.chapters[0].title == "第一章 绪论"
    assert "选择通透性" in summary.chapters[1].content

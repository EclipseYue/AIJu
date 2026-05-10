import asyncio
from pathlib import Path

from app.models.schemas import RagIndexRequest, RagQueryRequest
from app.services.rag_service import RagService
from app.services.textbook_parser import parser_service


def test_rag_index_and_query_with_citations(tmp_path: Path) -> None:
    textbook = tmp_path / "pathology.txt"
    textbook.write_text(
        "第一章 炎症\n"
        "炎症（inflammation）是具有血管系统的活体组织对损伤因子所发生的防御性反应。"
        "炎症反应包括变质、渗出和增生，并与免疫应答密切相关。\n",
        encoding="utf-8",
    )
    summary = parser_service.parse_local_file(textbook)
    service = RagService()

    status = asyncio.run(service.index(RagIndexRequest(textbook_ids=[summary.textbook_id])))
    response = asyncio.run(service.query(RagQueryRequest(question="炎症是什么？")))

    assert status.status == "ready"
    assert status.chunk_count >= 1
    assert "炎症" in response.answer
    assert response.citations
    assert response.source_chunks

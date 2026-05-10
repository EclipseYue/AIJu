import asyncio
from pathlib import Path

from app.models.schemas import GraphBuildRequest
from app.services.graph_builder import GraphBuilderService
from app.services.textbook_parser import parser_service


def test_graph_builder_from_parsed_textbook(tmp_path: Path) -> None:
    textbook = tmp_path / "physiology.txt"
    textbook.write_text(
        "第一章 绪论\n"
        "生理学（physiology）是研究机体生命活动规律的科学。\n"
        "第二章 细胞\n"
        "细胞膜（cell membrane）是分隔细胞质与环境的一层膜结构。\n",
        encoding="utf-8",
    )
    summary = parser_service.parse_local_file(textbook)
    graph = asyncio.run(
        GraphBuilderService().build(GraphBuildRequest(textbook_ids=[summary.textbook_id]))
    )

    assert graph.nodes
    assert any(node.name == "生理学" for node in graph.nodes)
    assert any(edge.relation_type == "contains" for edge in graph.edges)
    assert any(edge.relation_type == "prerequisite" for edge in graph.edges)

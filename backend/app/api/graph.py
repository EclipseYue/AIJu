from fastapi import APIRouter

from app.models.schemas import GraphBuildRequest, KnowledgeGraph
from app.services.graph_builder import graph_service


router = APIRouter()


@router.post("/build", response_model=KnowledgeGraph)
async def build_graph(payload: GraphBuildRequest) -> KnowledgeGraph:
    return await graph_service.build(payload)


@router.get("", response_model=KnowledgeGraph)
async def get_graph() -> KnowledgeGraph:
    return graph_service.current_graph()

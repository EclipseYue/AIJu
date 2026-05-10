from fastapi import APIRouter

from app.models.schemas import RagChatRequest, RagChatResponse, RagIndexRequest, RagQueryRequest, RagQueryResponse, RagStatus
from app.services.rag_service import rag_service


router = APIRouter()


@router.post("/index", response_model=RagStatus)
async def build_index(payload: RagIndexRequest) -> RagStatus:
    return await rag_service.index(payload)


@router.post("/query", response_model=RagQueryResponse)
async def query(payload: RagQueryRequest) -> RagQueryResponse:
    return await rag_service.query(payload)


@router.post("/chat", response_model=RagChatResponse)
async def chat(payload: RagChatRequest) -> RagChatResponse:
    return await rag_service.chat(payload)


@router.get("/status", response_model=RagStatus)
async def status() -> RagStatus:
    return rag_service.status()

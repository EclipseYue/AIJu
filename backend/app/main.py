from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import graph, integration, rag, report, textbooks
from app.core.config import settings


app = FastAPI(
    title="AIJu API",
    description="Subject textbook integration agent for knowledge graph, compression, and cited RAG.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(textbooks.router, prefix="/api/textbooks", tags=["textbooks"])
app.include_router(graph.router, prefix="/api/graph", tags=["graph"])
app.include_router(integration.router, prefix="/api/integration", tags=["integration"])
app.include_router(rag.router, prefix="/api/rag", tags=["rag"])
app.include_router(report.router, prefix="/api/report", tags=["report"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "AIJu"}

from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.models.schemas import Chapter, CleanupResult, ParseRequest, TextbookSummary
from app.services.textbook_parser import parser_service


router = APIRouter()


@router.post("/upload", response_model=TextbookSummary, response_model_exclude={"source_path"})
async def upload_textbook(file: Annotated[UploadFile, File(...)]) -> TextbookSummary:
    return await parser_service.register_upload(file)


@router.get("", response_model=list[TextbookSummary], response_model_exclude={"__all__": {"source_path"}})
async def list_textbooks() -> list[TextbookSummary]:
    textbooks = parser_service.list_textbooks()
    for tb in textbooks:
        tb.chapters = [
            Chapter(
                chapter_id=ch.chapter_id,
                title=ch.title,
                page_start=ch.page_start,
                page_end=ch.page_end,
                char_count=ch.char_count,
            )
            for ch in tb.chapters
        ]
    return textbooks


@router.post("/{textbook_id}/parse", response_model=TextbookSummary, response_model_exclude={"source_path"})
async def parse_textbook(textbook_id: str, payload: ParseRequest | None = None) -> TextbookSummary:
    return await parser_service.parse_textbook(textbook_id, payload or ParseRequest())


@router.post("/cleanup", response_model=CleanupResult)
async def cleanup_textbooks() -> CleanupResult:
    return parser_service.cleanup_duplicates_and_runtime_cache()

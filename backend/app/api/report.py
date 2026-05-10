from fastapi import APIRouter

from app.models.schemas import ReportSummary
from app.services.report_service import report_service


router = APIRouter()


@router.get("/summary", response_model=ReportSummary)
async def summary() -> ReportSummary:
    return report_service.summary()

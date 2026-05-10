from fastapi import APIRouter

from app.models.schemas import IntegrationRequest, IntegrationResult, TeacherFeedback
from app.services.integrator import integration_service


router = APIRouter()


@router.post("/run", response_model=IntegrationResult)
async def run_integration(payload: IntegrationRequest) -> IntegrationResult:
    return await integration_service.run(payload)


@router.post("/feedback", response_model=IntegrationResult)
async def apply_feedback(payload: TeacherFeedback) -> IntegrationResult:
    return await integration_service.apply_feedback(payload)

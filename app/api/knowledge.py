"""Clinic knowledge API routes."""
from fastapi import APIRouter, status
from app.models.knowledge import ClinicKnowledgeRequest, ClinicKnowledgeResponse
from app.services.knowledge_service import knowledge_service

router = APIRouter(prefix="/api/knowledge", tags=["Clinic Knowledge"])


@router.post(
    "/answer",
    response_model=ClinicKnowledgeResponse,
    status_code=status.HTTP_200_OK,
    summary="Query Clinic Knowledge Base",
    description="Answer patient questions on hours, location, insurance, etc., using strictly approved clinic facts without hallucination.",
)
async def query_clinic_knowledge(payload: ClinicKnowledgeRequest) -> ClinicKnowledgeResponse:
    """Answer clinic general questions."""
    return knowledge_service.answer_question(payload)

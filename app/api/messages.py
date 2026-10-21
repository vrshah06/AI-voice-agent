"""Message API routes for taking messages for clinic doctors and staff."""
from fastapi import APIRouter, status
from app.models.messages import TakeMessageRequest, TakeMessageResponse
from app.services.message_service import message_service

router = APIRouter(prefix="/api/messages", tags=["Messages"])


@router.post(
    "",
    response_model=TakeMessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Record Caller Message",
    description="Record a message from the caller to be delivered to clinic doctors, nurses, or staff.",
)
async def take_message(payload: TakeMessageRequest) -> TakeMessageResponse:
    """Store caller message."""
    return message_service.take_message(payload)

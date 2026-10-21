"""Data models for taking messages for clinic doctors and staff."""
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from app.models.common import BaseDemoResponse


class TakeMessageRequest(BaseModel):
    """Payload to leave a message for clinic staff or doctors."""
    caller_name: str = Field(..., min_length=2, max_length=100, description="Name of caller leaving message.")
    callback_number: str = Field(..., min_length=7, max_length=25, description="Return phone number.")
    recipient: Optional[str] = Field(
        default="Clinic Staff",
        max_length=100,
        description="Target recipient (e.g., 'Dr. Chintan Shah', 'Nursing', 'Billing', 'Front Desk').",
    )
    message: str = Field(..., min_length=3, max_length=1000, description="The message content to deliver.")
    urgency: Optional[str] = Field(default="routine", description="Urgency: routine, high, urgent.")

    @field_validator("caller_name", "callback_number", "message")
    @classmethod
    def clean_fields(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Field cannot be blank.")
        return cleaned


class TakeMessageResponse(BaseDemoResponse):
    """Structured response confirming message recording."""
    status: str = Field(default="recorded", description="Message status.")
    message_id: str = Field(..., description="Simulated message tracking code.", examples=["MSG-DEMO-84210"])
    caller_name: str = Field(..., description="Caller name.")
    callback_number: str = Field(..., description="Phone number.")
    recipient: str = Field(..., description="Target doctor or team.")
    message: str = Field(..., description="Natural language spoken confirmation for the agent.")

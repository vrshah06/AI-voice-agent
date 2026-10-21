"""Data models for clinic knowledge base queries."""
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from app.models.common import BaseDemoResponse


class ClinicKnowledgeRequest(BaseModel):
    """Payload to ask a general question about clinic hours, location, insurance, etc."""
    question: str = Field(..., min_length=2, max_length=500, description="The caller's question.")

    @field_validator("question")
    @classmethod
    def clean_question(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Question cannot be empty.")
        return cleaned


class ClinicKnowledgeResponse(BaseDemoResponse):
    """Structured response for clinic knowledge inquiries."""
    answer_found: bool = Field(..., description="Whether approved clinic information addresses the question.")
    topic: Optional[str] = Field(default=None, description="Identified clinic topic category.")
    answer: str = Field(..., description="Approved clinic answer or unavailable notice.")
    source: str = Field(default="Md Primary Care INC. Official Practice Policies", description="Information source.")
    escalate_to_staff: bool = Field(default=False, description="Whether caller should be transferred or leave a message.")
    message: str = Field(..., description="Conversational text the voice agent speaks.")

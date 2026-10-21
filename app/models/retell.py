"""Retell AI payload models and adapter schemas."""
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class RetellCallContext(BaseModel):
    """Contextual metadata injected by Retell during active calls."""
    call_id: Optional[str] = Field(default=None, description="Unique Retell call session ID.")
    agent_id: Optional[str] = Field(default=None, description="Retell agent configuration ID.")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Custom metadata.")
    transcript: Optional[Any] = Field(default=None, description="Live conversation transcript.")


class RetellWebhookRequest(BaseModel):
    """Retell AI default tool invocation payload format."""
    name: Optional[str] = Field(default=None, description="Custom function tool name.")
    call: Optional[RetellCallContext] = Field(default=None, description="Call context.")
    args: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Parameters extracted by LLM corresponding to tool schema."
    )


class RetellToolResponse(BaseModel):
    """Standardized response delivered back to Retell LLM context."""
    status: str = Field(default="success", description="Execution status: 'success' or 'error'.")
    message: str = Field(..., description="Conversational text the voice agent can speak.")
    data: Optional[Dict[str, Any]] = Field(default=None, description="Raw structured payload data.")
    error: Optional[str] = Field(default=None, description="Error detail if execution failed.")

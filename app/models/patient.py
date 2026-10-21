"""Patient data models for identification and lookup."""
from datetime import date
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from app.models.common import BaseDemoResponse, validate_dob_not_future


class PatientIdentifyRequest(BaseModel):
    """Payload to identify a patient by name and date of birth."""
    patient_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Full legal name of the patient.",
        examples=["Eleanor Vance"]
    )
    date_of_birth: date = Field(
        ...,
        description="Patient date of birth in YYYY-MM-DD format.",
        examples=["1985-04-12"]
    )

    @field_validator("patient_name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Patient name cannot be blank or whitespace.")
        return cleaned

    @field_validator("date_of_birth")
    @classmethod
    def validate_dob(cls, v: date) -> date:
        return validate_dob_not_future(v)


class PatientIdentifyResponse(BaseDemoResponse):
    """Structured response for patient identification."""
    status: str = Field(
        default="identified",
        description="Status of the lookup (e.g., identified, synthetic_match, new_demo_record)."
    )
    patient_id: str = Field(
        ...,
        description="Simulated patient chart identifier.",
        examples=["PAT-DEMO-001"]
    )
    patient_name: str = Field(..., description="Echoed normalized patient name.")
    date_of_birth: str = Field(..., description="Date of birth formatted as YYYY-MM-DD.")
    identity_verified: bool = Field(
        default=False,
        description="Explicit flag confirming identity has NOT been authenticated via government ID or OTP."
    )
    message: str = Field(
        ...,
        description="Spoken confirmation message suitable for the voice agent to read."
    )

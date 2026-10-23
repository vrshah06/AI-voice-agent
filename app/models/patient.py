"""Patient data models for identification, lookup, and eCW FHIR retrieval."""
from datetime import date
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
from app.models.common import BaseDemoResponse, validate_dob_not_future


# =====================================================================
# Real eCW FHIR Demographics Models (Receptionist Minimum Necessary)
# =====================================================================

class PatientAddress(BaseModel):
    """Permitted address demographic fields for receptionist routing."""
    line: Optional[str] = Field(default=None, description="Street address line(s).")
    city: Optional[str] = Field(default=None, description="City.")
    state: Optional[str] = Field(default=None, description="State or province.")
    postal_code: Optional[str] = Field(default=None, description="Postal / ZIP code.")


class PatientDemographicsResponse(BaseModel):
    """Minimum necessary demographic information for receptionist patient retrieval.

    Strictly excludes sensitive medical information (no clinical notes, diagnoses,
    conditions, prescriptions, medications, observation results, or lab data).
    """
    patient_id: str = Field(
        ...,
        description="eCW / FHIR Patient logical identifier.",
        examples=["12345"]
    )
    first_name: Optional[str] = Field(default=None, description="Patient given / first name.")
    last_name: Optional[str] = Field(default=None, description="Patient family / last name.")
    full_name: str = Field(
        ...,
        description="Formatted full legal name.",
        examples=["Eleanor Vance"]
    )
    date_of_birth: Optional[str] = Field(
        default=None,
        description="Date of birth in YYYY-MM-DD format.",
        examples=["1985-04-12"]
    )
    gender: Optional[str] = Field(
        default=None,
        description="Administrative sex / gender as recorded in EHR.",
        examples=["female"]
    )
    phone: Optional[str] = Field(
        default=None,
        description="Primary contact phone number.",
        examples=["561-555-0199"]
    )
    email: Optional[str] = Field(
        default=None,
        description="Contact email address.",
        examples=["patient@example.com"]
    )
    address: Optional[PatientAddress] = Field(
        default=None,
        description="Patient mailing address."
    )
    active: Optional[bool] = Field(
        default=True,
        description="Whether this patient record is active in the EHR."
    )
    preferred_language: Optional[str] = Field(
        default=None,
        description="Patient preferred spoken/written language.",
        examples=["English"]
    )


class PatientSearchResponse(BaseModel):
    """Response containing matched patient demographic records from eCW FHIR."""
    total: int = Field(..., description="Number of patients found.")
    patients: List[PatientDemographicsResponse] = Field(
        default_factory=list,
        description="List of retrieved patient demographic records."
    )


# =====================================================================
# Retell AI Voice Tool Compatibility Models
# =====================================================================

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


class PatientInfoRequest(BaseModel):
    """Payload to retrieve patient information following identity verification."""
    patient_name: str = Field(..., min_length=2, max_length=100, description="Full legal name.")
    date_of_birth: date = Field(..., description="Date of birth in YYYY-MM-DD format.")
    patient_id: Optional[str] = Field(None, description="Optional patient chart ID if already identified.")

    @field_validator("patient_name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Patient name cannot be blank.")
        return cleaned

    @field_validator("date_of_birth")
    @classmethod
    def validate_dob(cls, v: date) -> date:
        return validate_dob_not_future(v)


class PatientInfoResponse(BaseDemoResponse):
    """Structured response for patient information retrieval."""
    status: str = Field(default="success")
    patient_id: str = Field(...)
    patient_name: str = Field(...)
    date_of_birth: str = Field(...)
    is_verified: bool = Field(default=False)
    message: str = Field(...)
    details: Optional[dict] = Field(default=None)

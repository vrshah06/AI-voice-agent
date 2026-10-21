"""Medication refill request and response models."""
from datetime import date
from pydantic import BaseModel, Field, field_validator
from app.models.common import BaseDemoResponse, validate_dob_not_future


class MedicationRefillRequest(BaseModel):
    """Payload to initiate a simulated prescription refill request."""
    patient_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Patient's full legal name.",
        examples=["Eleanor Vance"]
    )
    date_of_birth: date = Field(
        ...,
        description="Patient's date of birth (YYYY-MM-DD).",
        examples=["1985-04-12"]
    )
    medication_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Name of medication requested.",
        examples=["Lisinopril 10mg"]
    )
    preferred_pharmacy_name: str = Field(
        ...,
        min_length=2,
        max_length=120,
        description="Name of preferred pharmacy.",
        examples=["CVS Pharmacy #4102"]
    )
    pharmacy_location: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description="Pharmacy address, cross street, or city location.",
        examples=["742 Evergreen Terrace, Springfield"]
    )

    @field_validator("patient_name", "medication_name", "preferred_pharmacy_name", "pharmacy_location")
    @classmethod
    def clean_strings(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or whitespace.")
        return cleaned

    @field_validator("date_of_birth")
    @classmethod
    def check_dob(cls, v: date) -> date:
        return validate_dob_not_future(v)


class MedicationRefillResponse(BaseDemoResponse):
    """Structured response for medication refill request submission."""
    status: str = Field(
        default="pending_prescriber_review",
        description="Status indicating request is recorded for clinical review."
    )
    refill_reference: str = Field(
        ...,
        description="Simulated refill request tracking code.",
        examples=["REF-DEMO-94821"]
    )
    patient_name: str = Field(..., description="Patient name.")
    medication_name: str = Field(..., description="Medication requested.")
    preferred_pharmacy_name: str = Field(..., description="Pharmacy name.")
    pharmacy_location: str = Field(..., description="Pharmacy address.")
    requires_prescriber_approval: bool = Field(
        default=True,
        description="Safety flag: All refills require explicit clinical authorization."
    )
    clinic_notice: str = Field(
        default=(
            "Simulated request recorded. The clinic clinical staff and authorized "
            "prescriber must review and approve this refill. Refills are typically "
            "processed within 24 to 48 business hours. For urgent needs, contact the clinic directly."
        ),
        description="Clinical safety disclaimer."
    )
    message: str = Field(
        ...,
        description="Spoken summary for the AI receptionist."
    )

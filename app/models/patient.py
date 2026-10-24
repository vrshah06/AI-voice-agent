"""Patient data models for identification, lookup, and eCW FHIR retrieval."""
from datetime import date, datetime
from typing import Any, List, Optional
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
# eCW Targeted Search & Paginated Listing Models
# =====================================================================

class PatientMatchSummary(BaseModel):
    """Minimal demographic identity summary for matching and directory listing.

    Contains only authorized fields strictly necessary for receptionist identification.
    Excludes all medical records, clinical notes, medications, and sensitive addresses.
    """
    patient_id: str = Field(..., description="eCW / FHIR Patient identifier.", examples=["12345"])
    first_name: Optional[str] = Field(default=None, description="First / given name.", examples=["Alex"])
    last_name: Optional[str] = Field(default=None, description="Last / family name.", examples=["Smith"])
    full_name: str = Field(..., description="Formatted full name.", examples=["Alex Smith"])
    date_of_birth: Optional[str] = Field(default=None, description="Date of birth (YYYY-MM-DD).", examples=["1985-06-15"])
    active: Optional[bool] = Field(default=True, description="Whether record is active in EHR.")


class PatientSearchMatchResponse(BaseModel):
    """Structured response for patient search by First Name, Last Name, and DOB.

    Follows healthcare safety rules: matching name & DOB confirms record existence only;
    receptionist must perform secondary verification before disclosing PHI.
    """
    match_status: str = Field(
        ...,
        description="Status of search: 'no_match', 'single_match', or 'multiple_matches'.",
        examples=["single_match"]
    )
    match_count: int = Field(..., description="Number of matching patient records found in eCW.")
    patients: List[PatientMatchSummary] = Field(
        default_factory=list,
        description="List of matched patient summaries (minimum necessary demographics)."
    )
    identity_verification_required: bool = Field(
        default=True,
        description="Flag indicating receptionist must verify identity before disclosing clinical info."
    )
    notice: str = Field(
        ...,
        description="Safety notice and clinical instructions for the receptionist."
    )


class PatientListResponse(BaseModel):
    """Paginated list of patient records available through eCW FHIR."""
    items: List[PatientMatchSummary] = Field(
        default_factory=list,
        description="List of patient records on the current page."
    )
    count: int = Field(..., description="Number of patient records in the current page.")
    page_size: int = Field(..., description="Configured page size.")
    next_page_token: Optional[str] = Field(
        default=None,
        description="Continuation token or URL for the next page of results, if available."
    )
    has_more: bool = Field(
        default=False,
        description="Whether additional patient records are available."
    )
    enumeration_note: str = Field(
        default="Patient listing is subject to practice tenant authorization and search window limits.",
        description="Explanatory note regarding population enumeration capability."
    )


# =====================================================================
# Retell AI Voice Tool Compatibility Models
# =====================================================================

class PatientIdentifyRequest(BaseModel):
    """Payload to identify a patient by name and date of birth."""
    patient_name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Full legal name of the patient (e.g. Kokila Shah).",
        examples=["Kokila Shah"]
    )
    first_name: Optional[str] = Field(
        default=None,
        description="Patient legal first / given name.",
        examples=["Kokila"]
    )
    last_name: Optional[str] = Field(
        default=None,
        description="Patient legal last / family name.",
        examples=["Shah"]
    )
    date_of_birth: Any = Field(
        ...,
        description="Patient date of birth in YYYY-MM-DD format (or date object).",
        examples=["1951-08-27"]
    )

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def parse_dob(cls, v: Any) -> date:
        if isinstance(v, date):
            return validate_dob_not_future(v)
        if isinstance(v, str):
            clean_str = v.strip()
            # Try YYYY-MM-DD
            try:
                parsed = datetime.strptime(clean_str, "%Y-%m-%d").date()
                return validate_dob_not_future(parsed)
            except ValueError:
                pass
            # Try MM/DD/YYYY
            try:
                parsed = datetime.strptime(clean_str, "%m/%d/%Y").date()
                return validate_dob_not_future(parsed)
            except ValueError:
                pass
            # Try standard date.fromisoformat
            try:
                parsed = date.fromisoformat(clean_str)
                return validate_dob_not_future(parsed)
            except ValueError:
                raise ValueError(f"Invalid date of birth format: '{clean_str}'. Expected format is YYYY-MM-DD.")
        raise ValueError("Date of birth must be a valid date or YYYY-MM-DD string.")

    def get_names(self) -> tuple[str, str, str]:
        """Returns normalized (first_name, last_name, full_name)."""
        f = (self.first_name or "").strip()
        l = (self.last_name or "").strip()
        full = (self.patient_name or "").strip()

        if f and l:
            return f, l, f"{f} {l}"
        if full:
            parts = full.split(None, 1)
            first = parts[0]
            last = parts[1] if len(parts) > 1 else ""
            return first, last, full
        if f:
            return f, "", f
        if l:
            return "", l, l
        raise ValueError("Either patient_name, or both first_name and last_name must be provided.")


class PatientIdentifyResponse(BaseModel):
    """Structured response for patient identification and verification."""
    status: str = Field(
        default="identified",
        description="Status of the lookup (verified_patient, not_found, multiple_matches, error)."
    )
    patient_id: str = Field(
        default="",
        description="eCW patient chart identifier.",
        examples=["12345"]
    )
    patient_name: str = Field(..., description="Normalized patient full legal name.")
    first_name: Optional[str] = Field(default=None, description="Patient first name.")
    last_name: Optional[str] = Field(default=None, description="Patient last name.")
    date_of_birth: str = Field(..., description="Date of birth formatted as YYYY-MM-DD.")
    identity_verified: bool = Field(
        default=False,
        description="Whether a matching active chart was confirmed in EHR."
    )
    match_status: Optional[str] = Field(
        default=None,
        description="FHIR search match status ('single_match', 'no_match', 'multiple_matches')."
    )
    message: str = Field(
        ...,
        description="Spoken confirmation message suitable for the voice agent to read."
    )
    is_demo_data: bool = Field(
        default=False,
        description="Whether this result originates from synthetic demo data."
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

"""eClinicalWorks FHIR Patient Retrieval, Search, and Listing API routes.

Provides endpoints for receptionists to:
1. GET /api/patients/search: Search patients by first_name, last_name, and dob (YYYY-MM-DD).
2. GET /api/patients: Retrieve paginated patient directory from actual eCW environment (authenticated).
3. GET /api/patients/{patient_id}: Retrieve authorized minimal demographic details by FHIR ID.

Exposes only minimum necessary demographic fields, strictly preventing disclosure
of clinical diagnoses, conditions, notes, medications, or lab results.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Path, Query, status

from app.core.security import verify_retell_or_api_key
from app.models.patient import (
    PatientDemographicsResponse,
    PatientListResponse,
    PatientSearchMatchResponse,
)
from app.services.ecw_client import ecw_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/patients", tags=["eCW Patient Demographics"])


# =====================================================================
# API One: Search Patient by First Name, Last Name, and DOB
# =====================================================================

@router.get(
    "/search",
    response_model=PatientSearchMatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search Patient by Name and Date of Birth",
    description=(
        "Search eClinicalWorks EHR for patients matching exact First Name, Last Name, and Date of Birth "
        "using official US Core FHIR search parameters (`given`, `family`, `birthdate`).\n\n"
        "**Clinical Safety Notice:** A matching Name and DOB confirms record existence only. "
        "The receptionist must follow an appropriate secondary identity-verification workflow "
        "before disclosing protected health information (PHI)."
    ),
    responses={
        200: {
            "description": "Patient search completed. Returns match status, count, and minimal demographic summary.",
            "model": PatientSearchMatchResponse,
        },
        400: {"description": "Invalid or missing search parameters (blank name or invalid DOB format)."},
        401: {"description": "eCW authentication failed or access token rejected."},
        403: {"description": "Insufficient permissions or practice tenant has not authorized this app."},
        429: {"description": "eClinicalWorks API rate limit reached."},
        502: {"description": "eClinicalWorks upstream FHIR server failure or malformed response."},
        503: {"description": "eClinicalWorks service temporarily unavailable or request timed out."},
    },
)
async def search_patient_by_name_and_dob(
    first_name: str = Query(
        ...,
        min_length=1,
        description="Patient legal first / given name.",
        examples=["Alex"],
    ),
    last_name: str = Query(
        ...,
        min_length=1,
        description="Patient legal last / family name.",
        examples=["Smith"],
    ),
    dob: str = Query(
        ...,
        description="Patient date of birth formatted as YYYY-MM-DD.",
        examples=["1985-06-15"],
    ),
) -> PatientSearchMatchResponse:
    """Search for patient in eCW EHR by given name, family name, and birthdate."""
    return await ecw_client.search_patient_by_name_dob(
        first_name=first_name,
        last_name=last_name,
        dob=dob,
    )


# =====================================================================
# API Two: List Patients Available Through eCW (Paginated & Secured)
# =====================================================================

@router.get(
    "",
    response_model=PatientListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Patients from eCW EHR",
    description=(
        "Retrieve patient records from the actual eCW environment accessible to the registered application.\n\n"
        "**Security & Authorization:** This endpoint requires API key or Bearer token authorization "
        "(via `X-Api-Key` or `Authorization: Bearer <key>`) to protect patient directory data.\n\n"
        "**Pagination & Limitations:** Supports FHIR Bundle pagination via `page_size` and `page_token`. "
        "If eCW restricts population-wide patient listing without search criteria, returns a clear 400 error "
        "explaining the restriction rather than silently returning an incomplete list."
    ),
    dependencies=[Depends(verify_retell_or_api_key)],
    responses={
        200: {
            "description": "Paginated patient records for the current page.",
            "model": PatientListResponse,
        },
        400: {
            "description": (
                "Population-wide search restricted by eCW practice policy without search parameters, "
                "or invalid page token."
            )
        },
        401: {"description": "Unauthorized: Missing/invalid API key or eCW authentication failure."},
        403: {"description": "Insufficient permissions or practice tenant has not activated directory access."},
        429: {"description": "eClinicalWorks API rate limit reached."},
        502: {"description": "eClinicalWorks upstream listing error."},
        503: {"description": "eClinicalWorks service temporarily unavailable."},
    },
)
async def list_patients(
    page_size: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Number of patient records to retrieve per page (max 100).",
    ),
    page_token: Optional[str] = Query(
        default=None,
        description="Continuation token or FHIR next-page link from a previous response.",
    ),
) -> PatientListResponse:
    """Retrieve paginated patient directory from actual eCW FHIR server."""
    return await ecw_client.list_patients(
        page_size=page_size,
        page_token=page_token,
    )


# =====================================================================
# Existing Endpoint: Get Patient Demographics by ID
# =====================================================================

@router.get(
    "/{patient_id}",
    response_model=PatientDemographicsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Patient Demographics by ID",
    description=(
        "Retrieve authorized patient demographic details from eClinicalWorks EHR using "
        "the FHIR R4 Patient resource. Returns only the minimum necessary information "
        "(name, date of birth, gender, contact information, language) needed for receptionist triage. "
        "Does NOT return sensitive clinical details (no diagnoses, conditions, notes, or medications)."
    ),
    responses={
        200: {
            "description": "Patient demographic record retrieved successfully.",
            "model": PatientDemographicsResponse,
        },
        400: {"description": "Invalid or blank patient ID supplied."},
        401: {"description": "eCW authentication failed or access token rejected."},
        403: {"description": "Insufficient permissions or practice tenant has not authorized this app."},
        404: {"description": "Patient not found in eClinicalWorks EHR."},
        502: {"description": "eClinicalWorks upstream FHIR server failure or malformed response."},
        503: {"description": "eClinicalWorks service temporarily unavailable or request timed out."},
    },
)
async def get_patient_by_id(
    patient_id: str = Path(
        ...,
        min_length=1,
        description="eCW / FHIR Patient logical identifier.",
        examples=["12345"],
    ),
) -> PatientDemographicsResponse:
    """Retrieve verified patient demographics from eCW FHIR by ID."""
    return await ecw_client.get_patient_by_id(patient_id=patient_id)

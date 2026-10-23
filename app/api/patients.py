"""eClinicalWorks FHIR Patient Retrieval and Search API routes.

Provides endpoints for receptionists to retrieve authorized patient demographic
records directly from eClinicalWorks EHR via FHIR R4.

Exposes only minimum necessary demographic fields, strictly preventing disclosure
of clinical diagnoses, conditions, notes, medications, or lab results.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Path, Query, status

from app.models.patient import (
    PatientDemographicsResponse,
    PatientSearchResponse,
)
from app.services.ecw_client import ecw_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/patients", tags=["eCW Patient Demographics"])


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


@router.get(
    "",
    response_model=PatientSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search Patients by Demographics",
    description=(
        "Search eClinicalWorks EHR for patients matching officially supported US Core FHIR "
        "search parameters (e.g., family name, given name, birthdate, identifier). "
        "At least one search parameter must be specified."
    ),
    responses={
        200: {
            "description": "Patient search completed successfully.",
            "model": PatientSearchResponse,
        },
        400: {"description": "Missing search parameters: at least one filter is required."},
        401: {"description": "eCW authentication failed or access token rejected."},
        403: {"description": "Insufficient search permissions or practice tenant access withheld."},
        502: {"description": "eClinicalWorks upstream search error."},
        503: {"description": "eClinicalWorks search service temporarily unavailable."},
    },
)
async def search_patients(
    family: Optional[str] = Query(
        default=None,
        description="Patient last / family name.",
        examples=["Smith"],
    ),
    given: Optional[str] = Query(
        default=None,
        description="Patient first / given name.",
        examples=["John"],
    ),
    birthdate: Optional[str] = Query(
        default=None,
        description="Patient date of birth in YYYY-MM-DD format.",
        examples=["1980-05-15"],
    ),
    identifier: Optional[str] = Query(
        default=None,
        description="Patient MRN or official identifier.",
        examples=["MRN12345"],
    ),
    name: Optional[str] = Query(
        default=None,
        description="Free-text patient name query.",
        examples=["John Smith"],
    ),
    gender: Optional[str] = Query(
        default=None,
        description="Administrative sex / gender (male, female, other, unknown).",
        examples=["female"],
    ),
    _id: Optional[str] = Query(
        default=None,
        description="Specific FHIR Patient resource ID.",
        examples=["12345"],
    ),
) -> PatientSearchResponse:
    """Execute US Core patient demographic search in eClinicalWorks FHIR."""
    return await ecw_client.search_patients(
        family=family,
        given=given,
        birthdate=birthdate,
        identifier=identifier,
        name=name,
        gender=gender,
        _id=_id,
    )

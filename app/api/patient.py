"""Patient API routes."""
from fastapi import APIRouter, status
from app.models.patient import PatientIdentifyRequest, PatientIdentifyResponse
from app.services.patient_service import patient_service

router = APIRouter(prefix="/api/patient", tags=["Patient Identification"])


@router.post(
    "/identify",
    response_model=PatientIdentifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Identify Patient",
    description=(
        "Collect and normalize caller name and date of birth. Returns a synthetic chart ID. "
        "NOTE: identity_verified is strictly false as this is unauthenticated demo data."
    ),
)
async def identify_patient(payload: PatientIdentifyRequest) -> PatientIdentifyResponse:
    """Identify or register a synthetic demo patient profile."""
    return patient_service.identify_patient(payload)

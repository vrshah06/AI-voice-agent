"""Medication refill API routes."""
from fastapi import APIRouter, status
from app.models.medications import MedicationRefillRequest, MedicationRefillResponse
from app.services.refill_service import refill_service

router = APIRouter(prefix="/api/medications", tags=["Medications"])


@router.post(
    "/refill",
    response_model=MedicationRefillResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit Medication Refill Request",
    description=(
        "Simulate logging a prescription refill request for clinical staff review. "
        "Strictly simulated; no actual pharmacies or electronic prescriptions are contacted."
    ),
)
async def request_medication_refill(payload: MedicationRefillRequest) -> MedicationRefillResponse:
    """Submit a medication refill request for clinical review."""
    return refill_service.request_refill(payload)

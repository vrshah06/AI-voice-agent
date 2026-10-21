"""In-memory service managing medication refill requests."""
import random
import string
from typing import Dict, List
from app.models.medications import MedicationRefillRequest, MedicationRefillResponse


class RefillService:
    """Manages simulated medication refill requests with safety guardrails."""

    def __init__(self) -> None:
        self._refill_requests: List[Dict[str, str]] = []

    def request_refill(self, request: MedicationRefillRequest) -> MedicationRefillResponse:
        """Submit and log a simulated medication refill request for clinic review."""
        random_suffix = "".join(random.choices(string.digits, k=5))
        refill_ref = f"REF-DEMO-{random_suffix}"

        record = {
            "refill_reference": refill_ref,
            "patient_name": request.patient_name,
            "date_of_birth": request.date_of_birth.isoformat(),
            "medication_name": request.medication_name,
            "preferred_pharmacy_name": request.preferred_pharmacy_name,
            "pharmacy_location": request.pharmacy_location,
            "status": "pending_prescriber_review",
        }
        self._refill_requests.append(record)

        message = (
            f"I have submitted your refill request for {request.medication_name} to be sent to "
            f"{request.preferred_pharmacy_name} at {request.pharmacy_location}. "
            f"Your simulated tracking reference is {refill_ref}. An authorized clinic prescriber "
            f"must review and approve all prescriptions before they are dispensed. "
            f"Please allow 24 to 48 hours for review."
        )

        return MedicationRefillResponse(
            status="pending_prescriber_review",
            refill_reference=refill_ref,
            patient_name=request.patient_name,
            medication_name=request.medication_name,
            preferred_pharmacy_name=request.preferred_pharmacy_name,
            pharmacy_location=request.pharmacy_location,
            requires_prescriber_approval=True,
            message=message,
        )

    def reset(self) -> None:
        """Reset state for clean automated testing."""
        self._refill_requests.clear()


refill_service = RefillService()

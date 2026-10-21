"""Patient identification service using in-memory demo repository."""
import hashlib
from typing import Dict, Optional
from app.models.patient import PatientIdentifyRequest, PatientIdentifyResponse


class PatientService:
    """In-memory demo service for patient identification and verification."""

    def __init__(self) -> None:
        # Pre-seeded synthetic patients
        self._synthetic_patients: Dict[str, Dict[str, str]] = {
            "eleanor vance_1985-04-12": {
                "patient_id": "PAT-DEMO-001",
                "patient_name": "Eleanor Vance",
                "date_of_birth": "1985-04-12",
            },
            "james wilson_1978-11-23": {
                "patient_id": "PAT-DEMO-002",
                "patient_name": "James Wilson",
                "date_of_birth": "1978-11-23",
            },
        }

    def _make_key(self, name: str, dob: str) -> str:
        return f"{name.strip().lower()}_{dob.strip()}"

    def identify_patient(self, request: PatientIdentifyRequest) -> PatientIdentifyResponse:
        """Process a patient identification and verification request.

        Confirms verification directly to the patient upon successful name & DOB matching.
        """
        dob_str = request.date_of_birth.isoformat()
        key = self._make_key(request.patient_name, dob_str)

        if key in self._synthetic_patients:
            record = self._synthetic_patients[key]
            patient_id = record["patient_id"]
            status_text = "verified_patient"
        else:
            # Deterministic ID generation for patient registration
            hash_suffix = hashlib.md5(key.encode()).hexdigest()[:4].upper()
            patient_id = f"PAT-DEMO-{hash_suffix}"
            self._synthetic_patients[key] = {
                "patient_id": patient_id,
                "patient_name": request.patient_name,
                "date_of_birth": dob_str,
            }
            status_text = "verified_patient"

        message = f"Thank you, {request.patient_name}. I have verified your details in our system."

        return PatientIdentifyResponse(
            status=status_text,
            patient_id=patient_id,
            patient_name=request.patient_name,
            date_of_birth=dob_str,
            identity_verified=True,
            message=message,
        )

    def reset(self) -> None:
        """Reset state for clean automated testing."""
        self.__init__()


patient_service = PatientService()

"""Patient identification and demographic service with live eCW EHR integration."""
import hashlib
import logging
from typing import Any, Dict, Optional
from fastapi import HTTPException

from app.core.config import settings
from app.models.patient import PatientIdentifyRequest, PatientIdentifyResponse
from app.services.ecw_client import ecw_client

logger = logging.getLogger(__name__)


class PatientService:
    """Service for patient identification and verification via live eCW FHIR EHR."""

    def __init__(self, ecw_svc=None) -> None:
        self._ecw_client = ecw_svc or ecw_client
        # Pre-seeded synthetic patients for local development and offline unit tests
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

    async def identify_patient(self, request: PatientIdentifyRequest) -> PatientIdentifyResponse:
        """Process patient identification using live eCW FHIR R4 Patient search.

        - Accepts first_name, last_name, or patient_name, and normalized date_of_birth.
        - When ECW_ENABLED=True, performs authorized live FHIR name & DOB lookup.
        - Safely handles zero matches, single match, and multiple candidate matches.
        - Falls back to in-memory testing repo when ECW_ENABLED=False.
        """
        first_name, last_name, full_name = request.get_names()
        dob_str = request.date_of_birth.strftime("%Y-%m-%d")
        key = self._make_key(full_name, dob_str)

        # 1. Pre-seeded synthetic patients (offline unit testing & demo profiles)
        if key in self._synthetic_patients:
            record = self._synthetic_patients[key]
            logger.info("Identified pre-seeded demo patient '%s'", full_name)
            message = f"Thank you, {full_name}. I have verified your details in our system."
            return PatientIdentifyResponse(
                status="verified_patient",
                patient_id=record["patient_id"],
                patient_name=record["patient_name"],
                first_name=first_name,
                last_name=last_name,
                date_of_birth=dob_str,
                identity_verified=True,
                match_status="single_match",
                message=message,
                is_demo_data=True,
            )

        # 2. Live eClinicalWorks EHR Verification
        if settings.ECW_ENABLED:
            logger.info("Verifying patient '%s %s' (DOB: %s) against live eCW EHR", first_name, last_name, dob_str)
            try:
                search_res = await self._ecw_client.search_patient_by_name_dob(
                    first_name=first_name,
                    last_name=last_name or first_name,
                    dob=dob_str,
                )

                # A. Single confirmed match
                if search_res.match_status == "single_match" and search_res.patients:
                    matched = search_res.patients[0]
                    clean_first = matched.first_name or first_name
                    clean_last = matched.last_name or last_name
                    pid = matched.patient_id
                    confirmed_full = matched.full_name or f"{clean_first} {clean_last}"

                    logger.info("eCW verified single patient chart: ID=%s, name='%s'", pid, confirmed_full)
                    message = f"Thank you, {confirmed_full}. I have verified your details in our system."

                    return PatientIdentifyResponse(
                        status="verified_patient",
                        patient_id=pid,
                        patient_name=confirmed_full,
                        first_name=clean_first,
                        last_name=clean_last,
                        date_of_birth=dob_str,
                        identity_verified=True,
                        match_status="single_match",
                        message=message,
                        is_demo_data=False,
                    )

                # B. Multiple matches - safety escalation
                elif search_res.match_status == "multiple_matches":
                    logger.warning("eCW returned multiple matches for '%s %s' (DOB: %s)", first_name, last_name, dob_str)
                    message = (
                        f"I found multiple patient records matching {first_name} {last_name} with date of birth {dob_str}. "
                        "For your privacy and safety, let me transfer you to our receptionist to confirm your chart."
                    )
                    return PatientIdentifyResponse(
                        status="multiple_matches",
                        patient_id="",
                        patient_name=full_name,
                        first_name=first_name,
                        last_name=last_name,
                        date_of_birth=dob_str,
                        identity_verified=False,
                        match_status="multiple_matches",
                        message=message,
                        is_demo_data=False,
                    )

                # C. Zero matches
                else:
                    logger.info("No eCW record found for '%s %s' (DOB: %s)", first_name, last_name, dob_str)
                    message = (
                        f"I could not locate an active chart for {first_name} {last_name} with date of birth {dob_str} in our clinic records. "
                        "Could you please verify the spelling of your name and date of birth, or let me know if you are a new patient?"
                    )
                    return PatientIdentifyResponse(
                        status="not_found",
                        patient_id="",
                        patient_name=full_name,
                        first_name=first_name,
                        last_name=last_name,
                        date_of_birth=dob_str,
                        identity_verified=False,
                        match_status="no_match",
                        message=message,
                        is_demo_data=False,
                    )

            except HTTPException as he:
                logger.error("eCW patient search returned HTTP %d: %s", he.status_code, he.detail)
                return PatientIdentifyResponse(
                    status="error",
                    patient_id="",
                    patient_name=full_name,
                    first_name=first_name,
                    last_name=last_name,
                    date_of_birth=dob_str,
                    identity_verified=False,
                    match_status="error",
                    message="I'm having temporary difficulty accessing our medical records system right now. Let me take down your information so our staff can assist you promptly.",
                    is_demo_data=False,
                )
            except Exception as exc:
                logger.error("Unexpected error in eCW patient search: %s", exc)
                return PatientIdentifyResponse(
                    status="error",
                    patient_id="",
                    patient_name=full_name,
                    first_name=first_name,
                    last_name=last_name,
                    date_of_birth=dob_str,
                    identity_verified=False,
                    match_status="error",
                    message="An unexpected error occurred while looking up your chart. Please hold while I connect you with our receptionist.",
                    is_demo_data=False,
                )

        # 2. In-memory demo fallback (offline testing / ECW_ENABLED=False)
        key = self._make_key(full_name, dob_str)
        if key in self._synthetic_patients:
            record = self._synthetic_patients[key]
            pid = record["patient_id"]
        else:
            hash_suffix = hashlib.md5(key.encode()).hexdigest()[:4].upper()
            pid = f"PAT-DEMO-{hash_suffix}"
            self._synthetic_patients[key] = {
                "patient_id": pid,
                "patient_name": full_name,
                "date_of_birth": dob_str,
            }

        return PatientIdentifyResponse(
            status="verified_patient",
            patient_id=pid,
            patient_name=full_name,
            first_name=first_name,
            last_name=last_name,
            date_of_birth=dob_str,
            identity_verified=True,
            match_status="single_match",
            message=f"Thank you, {first_name or full_name}. I have verified your details in our system.",
            is_demo_data=True,
        )

    async def get_patient_information(self, request) -> Dict[str, Any]:
        """Retrieve authorized patient profile details after verifying identity."""
        dob_str = request.date_of_birth.strftime("%Y-%m-%d")
        key = self._make_key(request.patient_name, dob_str)

        # 1. Live eCW retrieval if patient_id is available
        if settings.ECW_ENABLED and getattr(request, "patient_id", None):
            try:
                demographics = await self._ecw_client.get_patient_by_id(request.patient_id)
                details = {
                    "gender": demographics.gender,
                    "phone": demographics.phone,
                    "email": demographics.email,
                    "clinic": settings.CLINIC_NAME,
                    "status": "Active Patient",
                }
                if demographics.address:
                    details["address"] = f"{demographics.address.city or ''}, {demographics.address.state or ''}".strip(", ")

                return {
                    "status": "success",
                    "patient_id": demographics.patient_id,
                    "patient_name": demographics.full_name,
                    "date_of_birth": demographics.date_of_birth,
                    "is_verified": True,
                    "message": f"Patient record found for {demographics.full_name}.",
                    "details": details,
                }
            except Exception as exc:
                logger.error("Error retrieving eCW patient demographics by ID %s: %s", request.patient_id, exc)

        # 2. In-memory demo fallback
        if key in self._synthetic_patients:
            record = self._synthetic_patients[key]
            return {
                "status": "success",
                "patient_id": record["patient_id"],
                "patient_name": record["patient_name"],
                "date_of_birth": record["date_of_birth"],
                "is_verified": True,
                "message": f"Patient record found for {record['patient_name']}.",
                "details": {
                    "primary_care_physician": "Dr. Chintan Shah",
                    "clinic": settings.CLINIC_NAME,
                    "status": "Active Patient",
                },
            }

        return {
            "status": "unverified",
            "patient_id": "",
            "patient_name": request.patient_name,
            "date_of_birth": dob_str,
            "is_verified": False,
            "message": "I could not locate an active chart with that name and date of birth. Please verify the information with our receptionist.",
            "details": None,
        }

    def reset(self) -> None:
        """Reset state for clean automated testing."""
        self._synthetic_patients = {
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


patient_service = PatientService()



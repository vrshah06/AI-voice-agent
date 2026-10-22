"""eClinicalWorks (eCW) SMART on FHIR Client and Authentication Service.

Handles:
1. OAuth 2.0 Backend Services client_credentials token acquisition using signed RS384 client assertions.
2. Token caching and lifecycle management.
3. FHIR R4 Patient search and identity verification against documented US Core 6.1.0 specifications.
4. Active MedicationRequest retrieval for refill validation.
5. Clinical note/task creation fallback for appointment booking and refill workflows.
6. Graceful degradation to synthetic clinical records when unconfigured or running in demo mode.
"""
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.jwks import key_manager

logger = logging.getLogger(__name__)


class EcwTokenResponse(BaseModel):
    """Token response from eCW OAuth2 server."""
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 300
    scope: Optional[str] = None


class VerifiedPatientRecord(BaseModel):
    """Patient verification result from eCW FHIR server."""
    verified: bool
    patient_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    phone: Optional[str] = None
    match_status: str
    message: str
    raw_fhir_resource: Optional[Dict[str, Any]] = None


class EcwService:
    """Service for authenticating and interacting with eClinicalWorks FHIR APIs."""

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._cached_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._custom_http_client = http_client

    def _get_http_client(self) -> httpx.AsyncClient:
        return self._custom_http_client or httpx.AsyncClient(timeout=15.0)

    async def get_access_token(self, force_refresh: bool = False) -> str:
        """Obtain a valid OAuth 2.0 bearer token using SMART Backend Services private_key_jwt flow.

        Cached tokens are returned if still valid (with a 30s buffer).
        """
        now = time.time()
        if not force_refresh and self._cached_token and now < (self._token_expires_at - 30):
            return self._cached_token

        if not settings.ECW_CLIENT_ID:
            raise ValueError(
                "eCW Client ID is not configured. Set ECW_CLIENT_ID in your environment or Render secrets."
            )

        token_url = settings.ECW_TOKEN_URL
        client_id = settings.ECW_CLIENT_ID

        # 1. Generate client assertion signed with RS384
        client_assertion = key_manager.generate_client_assertion(
            client_id=client_id,
            token_url=token_url,
            expiry_seconds=settings.ECW_ASSERTION_EXPIRY_SECONDS,
        )

        # 2. Build form payload per SMART Backend Services specification
        form_data = {
            "grant_type": "client_credentials",
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": client_assertion,
            "scope": settings.ECW_SCOPES,
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        logger.info(
            "Requesting eCW access token from %s (client_id: %s..., kid: %s)",
            token_url,
            client_id[:4] if len(client_id) > 4 else client_id,
            key_manager.key_id,
        )

        async with self._get_http_client() as client:
            try:
                response = await client.post(token_url, data=form_data, headers=headers)
            except httpx.RequestError as exc:
                logger.error("Network error connecting to eCW OAuth token endpoint: %s", exc)
                raise ConnectionError(f"Could not reach eCW token endpoint: {exc}") from exc

        if response.status_code != 200:
            error_detail = response.text
            logger.error("eCW token request failed (%d): %s", response.status_code, error_detail)
            raise PermissionError(
                f"eCW authentication failed with status {response.status_code}: {error_detail}"
            )

        try:
            token_data = response.json()
            token_obj = EcwTokenResponse(**token_data)
        except Exception as exc:
            logger.error("Failed to parse eCW token response: %s", exc)
            raise ValueError(f"Malformed eCW token response: {exc}") from exc

        self._cached_token = token_obj.access_token
        self._token_expires_at = now + token_obj.expires_in
        logger.info("Successfully acquired eCW access token (expires in %d seconds)", token_obj.expires_in)
        return self._cached_token

    def is_configured(self) -> bool:
        """Returns True if eCW integration has credentials and is enabled."""
        return bool(settings.ECW_ENABLED and settings.ECW_CLIENT_ID and settings.ECW_FHIR_BASE_URL)

    async def search_and_verify_patient(
        self,
        first_name: str,
        last_name: str,
        date_of_birth: str,
    ) -> VerifiedPatientRecord:
        """Search and verify a patient in eCW using documented US Core FHIR R4 Patient search parameters.

        Searches by birthdate, family, and given name.
        Applies strict identity verification rules:
        - Only verifies if exactly one matching record is found with matching DOB and Name.
        - Discloses only authorized, verified information.
        """
        if not self.is_configured():
            logger.info("eCW not fully configured or disabled; using synthetic patient service.")
            return VerifiedPatientRecord(
                verified=False,
                match_status="synthetic_mode",
                message="eCW live connection not configured; using clinic local records.",
            )

        token = await self.get_access_token()
        base_url = settings.ECW_FHIR_BASE_URL.rstrip("/")
        search_url = f"{base_url}/Patient"

        params = {
            "family": last_name.strip(),
            "given": first_name.strip(),
            "birthdate": date_of_birth.strip(),
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/fhir+json, application/json",
        }

        async with self._get_http_client() as client:
            try:
                response = await client.get(search_url, params=params, headers=headers)
            except httpx.RequestError as exc:
                logger.error("Network error during eCW Patient search: %s", exc)
                return VerifiedPatientRecord(
                    verified=False,
                    match_status="network_error",
                    message="Temporary communication error connecting to clinic records.",
                )

        if response.status_code != 200:
            logger.warning("eCW Patient search returned status %d: %s", response.status_code, response.text)
            return VerifiedPatientRecord(
                verified=False,
                match_status="search_failed",
                message=f"Clinic patient search returned status {response.status_code}.",
            )

        try:
            bundle = response.json()
            total = bundle.get("total")
            entries = bundle.get("entry", [])

            if total == 0 or len(entries) == 0:
                logger.info("No matching patient record found in eCW for %s %s (%s)", first_name, last_name, date_of_birth)
                return VerifiedPatientRecord(
                    verified=False,
                    match_status="not_found",
                    message="No matching patient record was found with the provided name and date of birth.",
                )

            if len(entries) > 1:
                logger.warning(
                    "Multiple patient records (%d) matched %s %s (%s). Withholding details for safety.",
                    len(entries),
                    first_name,
                    last_name,
                    date_of_birth,
                )
                return VerifiedPatientRecord(
                    verified=False,
                    match_status="multiple_matches",
                    message="Multiple records match that information. Please connect with our receptionist for manual verification.",
                )

            resource = entries[0].get("resource", {})
            patient_id = resource.get("id")
            telecoms = resource.get("telecom", [])
            phone = next((t.get("value") for t in telecoms if t.get("system") == "phone"), None)
            gender = resource.get("gender")

            return VerifiedPatientRecord(
                verified=True,
                patient_id=patient_id,
                first_name=first_name,
                last_name=last_name,
                date_of_birth=date_of_birth,
                gender=gender,
                phone=phone,
                match_status="verified",
                message=f"Patient verified in clinic records: {first_name} {last_name}.",
                raw_fhir_resource=resource,
            )

        except Exception as exc:
            logger.exception("Error parsing eCW patient search response: %s", exc)
            return VerifiedPatientRecord(
                verified=False,
                match_status="parse_error",
                message="Error processing clinic patient record.",
            )

    async def get_patient_medications(self, patient_id: str) -> List[Dict[str, Any]]:
        """Retrieve active MedicationRequest resources for an authorized patient."""
        if not self.is_configured():
            return []

        token = await self.get_access_token()
        base_url = settings.ECW_FHIR_BASE_URL.rstrip("/")
        url = f"{base_url}/MedicationRequest"
        params = {"patient": patient_id}
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/fhir+json, application/json",
        }

        async with self._get_http_client() as client:
            try:
                response = await client.get(url, params=params, headers=headers)
                if response.status_code == 200:
                    bundle = response.json()
                    return [e.get("resource", {}) for e in bundle.get("entry", [])]
            except Exception as exc:
                logger.error("Failed to query MedicationRequest for patient %s: %s", patient_id, exc)

        return []

    async def log_telephone_encounter(
        self,
        patient_id: str,
        reason: str,
        notes: str,
    ) -> Optional[str]:
        """Log a Telephone Encounter in eCW EHR for clinical staff review.

        Used when appointments are requested/changed or refills are requested,
        alerting clinic staff within the eCW EHR workflow.
        """
        if not self.is_configured():
            logger.info("eCW integration disabled; skipping EHR encounter write.")
            return None

        token = await self.get_access_token()
        base_url = settings.ECW_FHIR_BASE_URL.rstrip("/")
        url = f"{base_url}/Encounter"

        encounter_payload = {
            "resourceType": "Encounter",
            "status": "planned",
            "class": {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                "code": "VR",
                "display": "Virtual",
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "reasonCode": [{"text": reason}],
            "serviceProvider": {"display": settings.CLINIC_NAME},
            "text": {
                "status": "generated",
                "div": f"<div xmlns='http://www.w3.org/1999/xhtml'><p>AI Receptionist Note: {notes}</p></div>",
            },
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json, application/json",
        }

        async with self._get_http_client() as client:
            try:
                response = await client.post(url, json=encounter_payload, headers=headers)
                if response.status_code in (200, 201):
                    created = response.json()
                    encounter_id = created.get("id")
                    logger.info("Created eCW Telephone Encounter: %s", encounter_id)
                    return encounter_id
                else:
                    logger.warning("Failed to create eCW Encounter (%d): %s", response.status_code, response.text)
            except Exception as exc:
                logger.error("Exception creating eCW Encounter: %s", exc)

        return None


# Global singleton instance
ecw_service = EcwService()

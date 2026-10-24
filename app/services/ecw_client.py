"""eClinicalWorks (eCW) SMART Backend Services FHIR Client.

Implements standards-compliant SMART Backend Services (RFC 7523) authentication
using signed RS384 client assertions, access-token caching, and authorized
FHIR R4 Patient retrieval, targeted search, and paginated listing against eClinicalWorks EHR.

Strictly enforces:
1. Rejection of mock/synthetic fallback upon live EHR failure.
2. Receptionist minimal necessary demographic extraction (no sensitive medical data).
3. Standardized error mapping (401, 403, 404, 429, 502, 503).
4. No logging of patient PHI (names, DOBs), access tokens, or private keys.
"""
import asyncio
from datetime import date, datetime
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import HTTPException, status
import httpx

from app.core.config import settings as default_settings
from app.core.jwks import key_manager as default_key_manager
from app.models.patient import (
    PatientAddress,
    PatientDemographicsResponse,
    PatientListResponse,
    PatientMatchSummary,
    PatientSearchMatchResponse,
    PatientSearchResponse,
)

logger = logging.getLogger(__name__)


# =====================================================================
# Specialized eCW Exception Classes (Mapped to Standard HTTP Statuses)
# =====================================================================

class EcwClientError(HTTPException):
    """Base exception for eCW client operations, exposing status_code and detail."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        blocker: Optional[str] = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.blocker = blocker


class EcwAuthError(EcwClientError):
    """401 Unauthorized: Authentication failed, token expired/rejected, or credentials missing."""

    def __init__(
        self,
        detail: str = "Authentication failed with eClinicalWorks OAuth server.",
        blocker: Optional[str] = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            blocker=blocker or "Invalid or unconfigured eCW client credentials",
        )


class EcwPermissionError(EcwClientError):
    """403 Forbidden: Insufficient permissions, missing scopes, or practice not activated."""

    def __init__(
        self,
        detail: str = "Insufficient permissions or access not granted by eClinicalWorks practice.",
        blocker: Optional[str] = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            blocker=blocker or "Practice activation pending or scopes missing",
        )


class EcwNotFoundError(EcwClientError):
    """404 Not Found: Patient record not found in eClinicalWorks EHR."""

    def __init__(
        self,
        detail: str = "Patient record was not found in eClinicalWorks EHR.",
    ) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail,
            blocker=None,
        )


class EcwUpstreamError(EcwClientError):
    """502 Bad Gateway: Upstream eClinicalWorks server error, invalid FHIR payload, or gateway failure."""

    def __init__(
        self,
        detail: str = "Upstream eClinicalWorks server returned an invalid or error response.",
        blocker: Optional[str] = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
            blocker=blocker,
        )


class EcwServiceUnavailableError(EcwClientError):
    """503 Service Unavailable: eCW upstream unavailable, timeout, network failure, or missing practice URL."""

    def __init__(
        self,
        detail: str = "eClinicalWorks service is temporarily unavailable or timed out.",
        blocker: Optional[str] = None,
        status_code: int = status.HTTP_503_SERVICE_UNAVAILABLE,
    ) -> None:
        super().__init__(
            status_code=status_code,
            detail=detail,
            blocker=blocker,
        )


# =====================================================================
# eCW Reusable Service Client
# =====================================================================

class EcwClient:
    """Production client for authenticating with eCW SMART Backend Services and fetching Patient resources."""

    def __init__(
        self,
        http_client: Optional[httpx.AsyncClient] = None,
        settings_obj=None,
        key_mgr=None,
    ) -> None:
        self._custom_http_client = http_client
        self._settings = settings_obj or default_settings
        self._key_manager = key_mgr or default_key_manager

        # Token caching state
        self._cached_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

    def _get_http_client(self) -> httpx.AsyncClient:
        """Return injected or dedicated AsyncClient with standard timeout."""
        if self._custom_http_client is not None:
            return self._custom_http_client
        return httpx.AsyncClient(timeout=15.0)

    def _check_configuration(self) -> None:
        """Verify that necessary credentials and URLs are configured.

        Never substitutes mock data if credentials or practice endpoints are missing.
        """
        client_id = self._settings.ECW_CLIENT_ID
        if not client_id or not client_id.strip() or client_id.strip() == "your-ecw-client-id-here":
            raise EcwAuthError(
                detail=(
                    "eClinicalWorks integration is not configured: ECW_CLIENT_ID is missing. "
                    "Please register your Provider Backend App on https://fhir.eclinicalworks.com/ecwopendev/ "
                    "and provide ECW_CLIENT_ID."
                ),
                blocker="Missing ECW_CLIENT_ID in environment / configuration",
            )

        token_url = self._settings.ECW_TOKEN_URL
        if not token_url or not token_url.strip():
            raise EcwServiceUnavailableError(
                detail="eClinicalWorks OAuth token endpoint is not configured (ECW_TOKEN_URL is empty).",
                blocker="Missing ECW_TOKEN_URL in configuration",
            )

    async def get_access_token(self, force_refresh: bool = False) -> str:
        """Obtain an authorized OAuth 2.0 access token using SMART Backend Services private_key_jwt.

        Generates an RS384 client assertion signed with the registered private key.
        Caches valid tokens with a 30-second expiration safety margin.
        """
        async with self._token_lock:
            now = time.time()
            if not force_refresh and self._cached_token and now < (self._token_expires_at - 30):
                return self._cached_token

            self._check_configuration()

            client_id = self._settings.ECW_CLIENT_ID.strip()
            token_url = self._settings.ECW_TOKEN_URL.strip()

            # 1. Generate client assertion signed with RS384
            try:
                client_assertion = self._key_manager.generate_client_assertion(
                    client_id=client_id,
                    token_url=token_url,
                    expiry_seconds=self._settings.ECW_ASSERTION_EXPIRY_SECONDS,
                )
            except Exception as exc:
                logger.error("Failed to generate RS384 client assertion: %s", exc)
                raise EcwAuthError(
                    detail="Cryptographic signing failed: unable to sign client assertion with RSA private key.",
                    blocker=f"RSA private key signing failed: {exc}",
                ) from exc

            # 2. Form payload per SMART Backend Services specification (RFC 7523)
            form_data = {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                "client_assertion": client_assertion,
                "scope": self._settings.ECW_SCOPES,
            }
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            }

            logger.info(
                "Requesting eCW OAuth bearer token from %s (client_id: %s..., kid: %s)",
                token_url,
                client_id[:6] if len(client_id) > 6 else client_id,
                self._key_manager.key_id,
            )

            client = self._get_http_client()
            try:
                response = await client.post(token_url, data=form_data, headers=headers)
            except httpx.TimeoutException as exc:
                logger.error("Timeout connecting to eCW OAuth server: %s", exc)
                raise EcwServiceUnavailableError(
                    detail="Connection timed out while reaching eClinicalWorks OAuth token endpoint.",
                    blocker="eCW OAuth server network timeout",
                ) from exc
            except httpx.RequestError as exc:
                logger.error("Network error reaching eCW OAuth server: %s", exc)
                raise EcwServiceUnavailableError(
                    detail=f"Unable to reach eClinicalWorks OAuth token endpoint: {exc}",
                    blocker="eCW OAuth server network unreachable",
                ) from exc
            finally:
                if self._custom_http_client is None:
                    await client.aclose()

            # 3. Handle OAuth error responses
            if response.status_code in (400, 401):
                logger.error("eCW OAuth token request failed (%d): %s", response.status_code, response.text)
                raise EcwAuthError(
                    detail=f"eClinicalWorks token request rejected ({response.status_code}): {response.text}",
                    blocker="eCW OAuth server rejected client assertion or client ID",
                )

            if response.status_code == 403:
                logger.error("eCW OAuth token request forbidden (403): %s", response.text)
                raise EcwPermissionError(
                    detail=f"eClinicalWorks token request forbidden (403): {response.text}",
                    blocker="Registered app lacks requested scopes or practice activation",
                )

            if response.status_code == 429:
                logger.warning("eCW OAuth server rate limit reached (429)")
                raise EcwServiceUnavailableError(
                    detail="eClinicalWorks OAuth token endpoint rate limit reached (HTTP 429).",
                    blocker="eCW OAuth rate limit",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                )

            if response.status_code >= 500:
                logger.error("eCW OAuth token server error (%d): %s", response.status_code, response.text)
                raise EcwUpstreamError(
                    detail=f"eClinicalWorks OAuth server internal error ({response.status_code}).",
                    blocker="eCW OAuth server internal outage",
                )

            if response.status_code != 200:
                logger.error("Unexpected eCW OAuth response status (%d): %s", response.status_code, response.text)
                raise EcwUpstreamError(
                    detail=f"Unexpected status ({response.status_code}) from eClinicalWorks OAuth token endpoint.",
                    blocker="eCW OAuth server unexpected response",
                )

            # 4. Parse token payload
            try:
                token_data = response.json()
                access_token = token_data["access_token"]
                expires_in = int(token_data.get("expires_in", 300))
            except Exception as exc:
                logger.error("Malformed eCW token response: %s", exc)
                raise EcwUpstreamError(
                    detail="eClinicalWorks OAuth server returned a malformed token response.",
                    blocker="eCW OAuth payload parse failure",
                ) from exc

            self._cached_token = access_token
            self._token_expires_at = now + expires_in
            logger.info("Successfully acquired eCW access token (expires in %d seconds)", expires_in)
            return self._cached_token

    def _get_fhir_base_url(self) -> str:
        """Validate and return practice FHIR base URL."""
        base_url = self._settings.ECW_FHIR_BASE_URL
        if not base_url or base_url.strip() in ("", "https://staging-fhir.ecwcloud.com/fhir/r4/"):
            raise EcwServiceUnavailableError(
                detail=(
                    "eClinicalWorks practice FHIR base URL is not configured. "
                    "Set ECW_FHIR_BASE_URL to your activated practice endpoint "
                    "(e.g., https://staging-fhir.ecwcloud.com/fhir/r4/YOUR_PRACTICE_ID)."
                ),
                blocker="Missing or placeholder ECW_FHIR_BASE_URL",
            )
        return base_url.rstrip("/")

    async def get_patient_by_id(self, patient_id: str) -> PatientDemographicsResponse:
        """Retrieve a Patient resource by ID from eCW FHIR R4 and return minimal demographics.

        Performs token acquisition, authorized GET request, token auto-refresh on 401,
        and rigorous status code handling. Never returns mock data on failure.
        """
        pid = patient_id.strip() if patient_id else ""
        if not pid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Patient ID cannot be blank.",
            )

        base_url = self._get_fhir_base_url()
        url = f"{base_url}/Patient/{pid}"

        token = await self.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/fhir+json",
        }

        client = self._get_http_client()
        try:
            response = await client.get(url, headers=headers)

            # Auto-retry once on 401 with refreshed token in case server invalidated token early
            if response.status_code == 401:
                logger.warning("eCW FHIR returned 401. Refreshing access token and retrying request once...")
                fresh_token = await self.get_access_token(force_refresh=True)
                headers["Authorization"] = f"Bearer {fresh_token}"
                response = await client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            logger.error("Timeout fetching patient from eCW: %s", exc)
            raise EcwServiceUnavailableError(
                detail=f"Connection timed out while fetching patient '{pid}' from eClinicalWorks.",
                blocker="eCW FHIR server timeout",
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Network error fetching patient from eCW: %s", exc)
            raise EcwServiceUnavailableError(
                detail=f"Communication failure connecting to eClinicalWorks FHIR server: {exc}",
                blocker="eCW FHIR server network failure",
            ) from exc
        finally:
            if self._custom_http_client is None:
                await client.aclose()

        # Handle HTTP status codes
        if response.status_code == 401:
            logger.error("eCW FHIR request rejected with 401 Unauthorized: %s", response.text)
            raise EcwAuthError(
                detail=f"eClinicalWorks authentication failed (401 Unauthorized) when retrieving patient '{pid}'.",
                blocker="eCW FHIR server rejected access token",
            )

        if response.status_code == 403:
            logger.error("eCW FHIR access forbidden (403): %s", response.text)
            raise EcwPermissionError(
                detail=(
                    f"eClinicalWorks denied access (403 Forbidden) for patient '{pid}'. "
                    "Ensure your Provider App has been granted 'system/Patient.read' scope and practice activation."
                ),
                blocker="eCW FHIR 403 Forbidden - insufficient scopes or practice not activated",
            )

        if response.status_code == 404:
            logger.info("Patient '%s' not found in eCW FHIR (404)", pid)
            raise EcwNotFoundError(detail=f"Patient with ID '{pid}' was not found in eClinicalWorks EHR.")

        if response.status_code == 429:
            raise EcwServiceUnavailableError(
                detail="eClinicalWorks FHIR rate limit reached (HTTP 429). Please retry shortly.",
                blocker="eCW FHIR rate limit",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        if response.status_code == 503:
            logger.warning("eCW FHIR server temporarily unavailable (503): %s", response.text)
            raise EcwServiceUnavailableError(
                detail="eClinicalWorks FHIR service is temporarily unavailable (503). Please retry shortly.",
                blocker="eCW upstream service unavailable",
            )

        if response.status_code in (500, 502, 504):
            logger.error("eCW upstream FHIR server error (%d): %s", response.status_code, response.text)
            raise EcwUpstreamError(
                detail=f"eClinicalWorks upstream FHIR server error (HTTP {response.status_code}).",
                blocker=f"eCW upstream error: {response.status_code}",
            )

        if response.status_code != 200:
            logger.error("Unexpected eCW FHIR response status (%d): %s", response.status_code, response.text)
            raise EcwUpstreamError(
                detail=f"eClinicalWorks FHIR server returned unexpected status code {response.status_code}: {response.text}",
                blocker="eCW unexpected status code",
            )

        # Parse and validate FHIR Patient resource
        try:
            fhir_resource = response.json()
        except Exception as exc:
            logger.error("Failed to parse JSON from eCW FHIR response: %s", exc)
            raise EcwUpstreamError(
                detail="eClinicalWorks FHIR server returned non-JSON or malformed payload.",
                blocker="Invalid JSON payload from eCW",
            ) from exc

        if fhir_resource.get("resourceType") != "Patient":
            logger.error("Expected FHIR 'Patient' resource, got '%s'", fhir_resource.get("resourceType"))
            raise EcwUpstreamError(
                detail=f"Invalid FHIR resource returned: expected 'Patient', received '{fhir_resource.get('resourceType')}'.",
                blocker="Invalid FHIR resourceType",
            )

        return self.extract_patient_demographics(fhir_resource)

    async def search_patient_by_name_dob(
        self,
        first_name: str,
        last_name: str,
        dob: str,
    ) -> PatientSearchMatchResponse:
        """Search patient by First Name, Last Name, and Date of Birth using eCW US Core search parameters.

        Upstream query:
            GET {ECW_FHIR_BASE_URL}/Patient?given={first_name}&family={last_name}&birthdate={dob}

        Safety rules:
        - Input validation: verifies non-blank name and valid past ISO YYYY-MM-DD date.
        - Matching name and DOB confirms record existence only.
        - Returns structured PatientSearchMatchResponse with match_status ('no_match', 'single_match', 'multiple_matches').
        - Never substitutes mock data on failure.
        - Never logs patient names or DOBs.
        """
        clean_first = first_name.strip() if first_name else ""
        clean_last = last_name.strip() if last_name else ""
        clean_dob = dob.strip() if dob else ""

        if not clean_first:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Query parameter 'first_name' is required and cannot be blank.",
            )
        if not clean_last:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Query parameter 'last_name' is required and cannot be blank.",
            )
        if not clean_dob:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Query parameter 'dob' is required and cannot be blank.",
            )

        # Validate DOB format and reasonableness
        try:
            parsed_dob = datetime.strptime(clean_dob, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid date format for 'dob': '{clean_dob}'. Expected format is YYYY-MM-DD.",
            )

        today = date.today()
        if parsed_dob >= today:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Date of birth ({clean_dob}) must be in the past.",
            )
        if today.year - parsed_dob.year > 125 or parsed_dob.year < 1890:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Date of birth ({clean_dob}) is out of reasonable range.",
            )

        base_url = self._get_fhir_base_url()
        url = f"{base_url}/Patient"
        params = {
            "given": clean_first,
            "family": clean_last,
            "birthdate": clean_dob,
        }

        token = await self.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/fhir+json",
        }

        client = self._get_http_client()
        try:
            response = await client.get(url, params=params, headers=headers)
            if response.status_code == 401:
                fresh_token = await self.get_access_token(force_refresh=True)
                headers["Authorization"] = f"Bearer {fresh_token}"
                response = await client.get(url, params=params, headers=headers)

            # If rejected with 400, test alternative US Core parameter combinations
            if response.status_code == 400:
                # 1. Try explicit 'eq' comparator prefix (mandated by some eCW versions)
                eq_params = {
                    "given": clean_first,
                    "family": clean_last,
                    "birthdate": f"eq{clean_dob}",
                }
                logger.info("eCW rejected standard date search with 400. Retrying with 'eq' birthdate comparator...")
                resp_eq = await client.get(url, params=eq_params, headers=headers)
                if resp_eq.status_code == 200:
                    response = resp_eq
                elif resp_eq.status_code != 400:
                    response = resp_eq
                else:
                    # 2. Try US Core combination 'name' and 'birthdate'
                    name_params = {
                        "name": f"{clean_first} {clean_last}",
                        "birthdate": clean_dob,
                    }
                    logger.info("Retrying eCW Patient search with 'name' and 'birthdate' parameter combination...")
                    resp_name = await client.get(url, params=name_params, headers=headers)
                    if resp_name.status_code == 200:
                        response = resp_name
                    elif resp_name.status_code != 400:
                        response = resp_name
        except httpx.TimeoutException as exc:
            logger.error("Timeout during eCW Patient name/dob search: %s", exc)
            raise EcwServiceUnavailableError(
                detail="Connection timed out while searching patient records in eClinicalWorks.",
                blocker="eCW Patient search timeout",
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Network error during eCW Patient name/dob search: %s", exc)
            raise EcwServiceUnavailableError(
                detail=f"Communication error connecting to eClinicalWorks Patient search: {exc}",
                blocker="eCW Patient search network error",
            ) from exc
        finally:
            if self._custom_http_client is None:
                await client.aclose()

        if response.status_code == 401:
            raise EcwAuthError(
                detail="eClinicalWorks authentication failed (401) during patient search.",
                blocker="Invalid or expired access token",
            )
        if response.status_code == 403:
            raise EcwPermissionError(
                detail="eClinicalWorks permission denied (403) for patient search. Ensure 'system/Patient.read' scope is active.",
                blocker="Insufficient scope or practice authorization",
            )
        if response.status_code == 429:
            raise EcwServiceUnavailableError(
                detail="eClinicalWorks FHIR search rate limit reached (HTTP 429).",
                blocker="eCW search rate limit",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if response.status_code in (500, 502, 504):
            raise EcwUpstreamError(
                detail=f"eClinicalWorks Patient search upstream failure (HTTP {response.status_code}).",
                blocker=f"eCW upstream status {response.status_code}",
            )
        if response.status_code == 503:
            raise EcwServiceUnavailableError(
                detail="eClinicalWorks Patient search service is temporarily unavailable (503).",
                blocker="eCW search service unavailable",
            )
        if response.status_code == 400:
            logger.error("eCW Patient search returned 400: %s", response.text)
            err_msg = response.text
            try:
                outcome = response.json()
                if outcome.get("resourceType") == "OperationOutcome":
                    issues = outcome.get("issue", [])
                    diags = [
                        i.get("diagnostics") or i.get("details", {}).get("text")
                        for i in issues
                        if i.get("diagnostics") or i.get("details", {}).get("text")
                    ]
                    if diags:
                        err_msg = "; ".join(diags)
            except Exception:
                pass
            raise EcwClientError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"eClinicalWorks FHIR server rejected search request (400): {err_msg}",
                blocker="eCW rejected search parameters or criteria",
            )
        if response.status_code != 200:
            raise EcwUpstreamError(
                detail=f"eClinicalWorks Patient search returned unexpected status {response.status_code}: {response.text}",
                blocker="Unexpected status code",
            )

        try:
            bundle = response.json()
        except Exception as exc:
            raise EcwUpstreamError(detail="Malformed JSON returned from eCW Patient search.") from exc

        if bundle.get("resourceType") != "Bundle":
            raise EcwUpstreamError(detail="Expected FHIR searchset 'Bundle' from eCW Patient search.")

        entries = bundle.get("entry", [])
        matched_summaries: List[PatientMatchSummary] = []
        for entry in entries:
            res = entry.get("resource")
            if res and res.get("resourceType") == "Patient":
                summary = self._extract_patient_summary(res)
                matched_summaries.append(summary)

        count = len(matched_summaries)
        if count == 0:
            match_status_text = "no_match"
            notice_text = (
                "No matching patient records found with the provided name and date of birth in clinic EHR. "
                "Verify spelling or check if patient is registered under an alternative name."
            )
        elif count == 1:
            match_status_text = "single_match"
            notice_text = (
                "Single patient match confirmed. Notice: Matching name and DOB confirms record existence only. "
                "Receptionist must perform secondary verification (e.g., phone or address confirmation) before disclosing protected information."
            )
        else:
            match_status_text = "multiple_matches"
            notice_text = (
                f"Multiple ({count}) matching patient records found with identical name and date of birth. "
                "Protected demographic disclosure withheld for patient safety. Transfer caller to receptionist for manual chart verification."
            )

        return PatientSearchMatchResponse(
            match_status=match_status_text,
            match_count=count,
            patients=matched_summaries,
            identity_verification_required=True,
            notice=notice_text,
        )

    async def list_patients(
        self,
        page_size: int = 20,
        page_token: Optional[str] = None,
    ) -> PatientListResponse:
        """Retrieve paginated patient records from actual eCW EHR environment.

        Supports FHIR Bundle pagination links.
        If eCW restricts population-wide patient search, returns a clear error explaining
        the practice restriction rather than silently returning an incomplete list.
        """
        clamped_size = min(max(page_size, 1), 100)
        base_url = self._get_fhir_base_url()

        # Build request URL: either follow validated next link or query base with _count
        if page_token and page_token.strip():
            token_clean = page_token.strip()
            # If page_token is a continuation URL, ensure it belongs to the verified FHIR base URL
            if token_clean.startswith("http://") or token_clean.startswith("https://"):
                parsed_base = urlparse(base_url)
                parsed_token = urlparse(token_clean)
                if parsed_token.netloc != parsed_base.netloc or not parsed_token.path.startswith(parsed_base.path):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid next_page_token: URL domain or path does not match configured practice FHIR base.",
                    )
                url = token_clean
                params = None
            else:
                url = f"{base_url}/Patient"
                params = {"_count": str(clamped_size), "page": token_clean}
        else:
            url = f"{base_url}/Patient"
            params = {"_count": str(clamped_size)}

        token = await self.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/fhir+json",
        }

        client = self._get_http_client()
        try:
            response = await client.get(url, params=params, headers=headers)
            if response.status_code == 401:
                fresh_token = await self.get_access_token(force_refresh=True)
                headers["Authorization"] = f"Bearer {fresh_token}"
                response = await client.get(url, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            logger.error("Timeout during eCW Patient listing: %s", exc)
            raise EcwServiceUnavailableError(
                detail="Connection timed out while retrieving patient list from eClinicalWorks.",
                blocker="eCW Patient list timeout",
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Network error during eCW Patient listing: %s", exc)
            raise EcwServiceUnavailableError(
                detail=f"Communication error connecting to eClinicalWorks Patient list: {exc}",
                blocker="eCW Patient list network error",
            ) from exc
        finally:
            if self._custom_http_client is None:
                await client.aclose()

        # Handle eCW restriction on population-wide listing without search criteria
        if response.status_code in (400, 403):
            err_text = response.text.lower()
            if (
                "search criteria" in err_text
                or "search without" in err_text
                or "not supported" in err_text
                or "parameter required" in err_text
                or "operationoutcome" in err_text
                or response.status_code == 400
            ):
                raise EcwClientError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "eClinicalWorks EHR server restricts population-wide patient listing without search criteria. "
                        "Practice security policy mandates searching by specific parameters (e.g., given, family, birthdate, identifier) "
                        "rather than unrestricted population enumeration."
                    ),
                    blocker="eCW restricts unfiltered population queries without search parameters",
                )
            if response.status_code == 403:
                raise EcwPermissionError(
                    detail="eClinicalWorks denied permission (403) to list patient directory. Check provider app permissions.",
                    blocker="App not authorized for patient directory enumeration",
                )

        if response.status_code == 401:
            raise EcwAuthError(detail="eClinicalWorks authentication failed (401) during patient list retrieval.")
        if response.status_code == 429:
            raise EcwServiceUnavailableError(
                detail="eClinicalWorks patient listing rate limit reached (HTTP 429).",
                blocker="eCW list rate limit",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if response.status_code in (500, 502, 504):
            raise EcwUpstreamError(detail=f"eClinicalWorks patient listing upstream failure (HTTP {response.status_code}).")
        if response.status_code == 503:
            raise EcwServiceUnavailableError(detail="eClinicalWorks Patient list service is temporarily unavailable (503).")
        if response.status_code != 200:
            raise EcwUpstreamError(detail=f"eClinicalWorks Patient list returned unexpected status {response.status_code}.")

        try:
            bundle = response.json()
        except Exception as exc:
            raise EcwUpstreamError(detail="Malformed JSON returned from eCW Patient list.") from exc

        if bundle.get("resourceType") != "Bundle":
            raise EcwUpstreamError(detail="Expected FHIR searchset 'Bundle' from eCW Patient list.")

        entries = bundle.get("entry", [])
        items: List[PatientMatchSummary] = []
        for entry in entries:
            res = entry.get("resource")
            if res and res.get("resourceType") == "Patient":
                items.append(self._extract_patient_summary(res))

        # Check for FHIR next page continuation link
        links = bundle.get("link", [])
        next_link: Optional[str] = None
        for link_entry in links:
            if link_entry.get("relation") == "next" and link_entry.get("url"):
                next_link = link_entry["url"]
                break

        return PatientListResponse(
            items=items,
            count=len(items),
            page_size=clamped_size,
            next_page_token=next_link,
            has_more=bool(next_link),
            enumeration_note=(
                "Patient listing is subject to practice tenant authorization and search window limits. "
                "Standard FHIR REST queries do not guarantee global population enumeration without bulk $export."
            ),
        )

    def _extract_patient_summary(self, resource: Dict[str, Any]) -> PatientMatchSummary:
        """Extract minimal authorized identity summary fields for search matches and listing."""
        patient_id = str(resource.get("id", "")).strip()

        names = resource.get("name", [])
        first_name: Optional[str] = None
        last_name: Optional[str] = None
        full_name = ""

        if names:
            chosen_name = next(
                (n for n in names if n.get("use") in ("official", "usual")),
                names[0]
            )
            last_name = chosen_name.get("family")
            given = chosen_name.get("given", [])
            first_name = " ".join(given).strip() if given else None

            if chosen_name.get("text"):
                full_name = chosen_name["text"].strip()
            else:
                parts = [p for p in [first_name, last_name] if p]
                full_name = " ".join(parts).strip()

        if not full_name:
            full_name = f"Patient {patient_id}"

        return PatientMatchSummary(
            patient_id=patient_id,
            first_name=first_name,
            last_name=last_name,
            full_name=full_name,
            date_of_birth=resource.get("birthDate"),
            active=resource.get("active", True),
        )

    def extract_patient_demographics(self, resource: Dict[str, Any]) -> PatientDemographicsResponse:
        """Extract only authorized, minimum-necessary receptionist demographic fields.

        Strictly prevents leakage of medical records (no diagnoses, conditions, clinical notes,
        allergies, observations, or medication orders).
        """
        patient_id = str(resource.get("id", "")).strip()

        # 1. Name Parsing
        names = resource.get("name", [])
        first_name: Optional[str] = None
        last_name: Optional[str] = None
        full_name = ""

        if names:
            chosen_name = next(
                (n for n in names if n.get("use") in ("official", "usual")),
                names[0]
            )
            last_name = chosen_name.get("family")
            given = chosen_name.get("given", [])
            first_name = " ".join(given).strip() if given else None

            if chosen_name.get("text"):
                full_name = chosen_name["text"].strip()
            else:
                parts = [p for p in [first_name, last_name] if p]
                full_name = " ".join(parts).strip()

        if not full_name:
            full_name = f"Patient {patient_id}"

        # 2. Telecom parsing (Phone & Email)
        telecoms = resource.get("telecom", [])
        phone: Optional[str] = None
        email: Optional[str] = None

        for item in telecoms:
            system = item.get("system")
            val = item.get("value")
            if not val:
                continue
            if system == "phone" and not phone:
                phone = val.strip()
            elif system == "email" and not email:
                email = val.strip()

        # 3. Address parsing
        address_obj: Optional[PatientAddress] = None
        addresses = resource.get("address", [])
        if addresses:
            chosen_addr = addresses[0]
            lines = chosen_addr.get("line", [])
            line_str = ", ".join(lines) if isinstance(lines, list) else str(lines)
            address_obj = PatientAddress(
                line=line_str.strip() if line_str else None,
                city=chosen_addr.get("city"),
                state=chosen_addr.get("state"),
                postal_code=chosen_addr.get("postalCode"),
            )

        # 4. Language preference
        preferred_language: Optional[str] = None
        communications = resource.get("communication", [])
        if communications:
            chosen_comm = next(
                (c for c in communications if c.get("preferred") is True),
                communications[0]
            )
            lang_dict = chosen_comm.get("language", {})
            if lang_dict.get("text"):
                preferred_language = lang_dict["text"]
            elif lang_dict.get("coding") and len(lang_dict["coding"]) > 0:
                preferred_language = (
                    lang_dict["coding"][0].get("display")
                    or lang_dict["coding"][0].get("code")
                )

        return PatientDemographicsResponse(
            patient_id=patient_id,
            first_name=first_name,
            last_name=last_name,
            full_name=full_name,
            date_of_birth=resource.get("birthDate"),
            gender=resource.get("gender"),
            phone=phone,
            email=email,
            address=address_obj,
            active=resource.get("active", True),
            preferred_language=preferred_language,
        )


# Global singleton instance
ecw_client = EcwClient()

"""eClinicalWorks (eCW) Patient App OAuth 2.0 Authorization & Token Service.

Completely isolated from Provider App Backend Services:
- Dedicated Patient App credentials (ECW_PATIENT_CLIENT_ID, ECW_PATIENT_CLIENT_SECRET)
- PKCE (RFC 7636 S256) and anti-CSRF state tracking
- Safe backend token storage without leaking tokens, codes, or PHI
"""
import logging
import urllib.parse
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, status
import httpx

from app.core.config import settings
from app.services.ecw_client import (
    EcwAuthError,
    EcwPermissionError,
    EcwServiceUnavailableError,
    EcwUpstreamError,
)
from app.services.ecw_token_store import (
    ecw_patient_state_store,
    ecw_patient_token_store,
    generate_pkce_pair,
)

logger = logging.getLogger(__name__)


class EcwPatientAuthService:
    """Service handling eCW Patient App OAuth 2.0 Authorization Code flow with PKCE."""

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._custom_http_client = http_client

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._custom_http_client is not None:
            return self._custom_http_client
        return httpx.AsyncClient(timeout=15.0)

    def _validate_configuration(self) -> None:
        """Ensure Patient App client ID and endpoints are set."""
        client_id = settings.ECW_PATIENT_CLIENT_ID.strip()
        if not client_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ECW_PATIENT_CLIENT_ID is not configured. Set ECW_PATIENT_CLIENT_ID in your environment.",
            )

        token_url = settings.ECW_PATIENT_TOKEN_URL.strip()
        if not token_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ECW_PATIENT_TOKEN_URL is not configured. Set ECW_PATIENT_TOKEN_URL in your environment.",
            )

        auth_url = settings.ECW_PATIENT_AUTHORIZE_URL.strip()
        if not auth_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ECW_PATIENT_AUTHORIZE_URL is not configured. Set ECW_PATIENT_AUTHORIZE_URL in your environment.",
            )

    def initiate_authorization(
        self,
        scope: Optional[str] = None,
        practice_code: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate PKCE challenge, create anti-forgery state, and build authorization URL."""
        self._validate_configuration()

        client_id = settings.ECW_PATIENT_CLIENT_ID.strip()
        auth_base = settings.ECW_PATIENT_AUTHORIZE_URL.strip()
        target_redirect_uri = (redirect_uri or settings.ECW_PATIENT_REDIRECT_URI).strip()
        selected_scope = (scope or settings.ECW_PATIENT_SCOPES or "openid patient/*.read").strip()
        selected_practice = (practice_code or settings.ECW_PATIENT_PRACTICE_CODE or "BDGDCD").strip()

        # 1. Generate RFC 7636 PKCE pair
        code_verifier, code_challenge = generate_pkce_pair()

        # 2. Generate and store state with 15-minute TTL
        state = ecw_patient_state_store.create_state(
            redirect_uri=target_redirect_uri,
            code_verifier=code_verifier,
            scope=selected_scope,
            practice_code=selected_practice,
        )

        # 3. Construct SMART on FHIR authorization URL
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": target_redirect_uri,
            "scope": selected_scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "practice_code": selected_practice,
        }
        authorization_url = f"{auth_base}?{urllib.parse.urlencode(params)}"

        logger.info(
            "Initiated Patient App OAuth flow: client_id=%s..., redirect_uri=%s, practice_code=%s",
            client_id[:6] if len(client_id) > 6 else client_id,
            target_redirect_uri,
            selected_practice,
        )

        return {
            "status": "initiated",
            "authorization_url": authorization_url,
            "state": state,
            "redirect_uri": target_redirect_uri,
            "practice_code": selected_practice,
            "scope": selected_scope,
            "code_challenge_method": "S256",
            "expires_in_seconds": 900,
        }

    async def exchange_authorization_code(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Exchange authorization code for Patient App access and refresh tokens."""
        self._validate_configuration()

        if not code or not code.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Authorization code cannot be blank.",
            )

        client_id = settings.ECW_PATIENT_CLIENT_ID.strip()
        token_url = settings.ECW_PATIENT_TOKEN_URL.strip()
        target_redirect_uri = redirect_uri.strip()

        form_data = {
            "grant_type": "authorization_code",
            "code": code.strip(),
            "redirect_uri": target_redirect_uri,
            "client_id": client_id,
        }
        if code_verifier and code_verifier.strip():
            form_data["code_verifier"] = code_verifier.strip()

        # Include client secret if configured (confidential client)
        if settings.ECW_PATIENT_CLIENT_SECRET and settings.ECW_PATIENT_CLIENT_SECRET.strip():
            form_data["client_secret"] = settings.ECW_PATIENT_CLIENT_SECRET.strip()

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        logger.info(
            "Exchanging Patient App OAuth code at %s (client_id: %s..., redirect_uri: %s, pkce=%s, confidential=%s)",
            token_url,
            client_id[:6] if len(client_id) > 6 else client_id,
            target_redirect_uri,
            bool(code_verifier),
            bool(settings.ECW_PATIENT_CLIENT_SECRET),
        )

        client = self._get_http_client()
        try:
            response = await client.post(token_url, data=form_data, headers=headers)
        except httpx.TimeoutException as exc:
            logger.error("Timeout during Patient App code exchange: %s", exc)
            raise EcwServiceUnavailableError(
                detail="Connection timed out while exchanging authorization code with eClinicalWorks.",
                blocker="eCW OAuth server network timeout",
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Network error during Patient App code exchange: %s", exc)
            raise EcwServiceUnavailableError(
                detail=f"Unable to reach eClinicalWorks OAuth token endpoint: {exc}",
                blocker="eCW OAuth server unreachable",
            ) from exc
        finally:
            if self._custom_http_client is None:
                await client.aclose()

        if response.status_code in (400, 401):
            logger.error("Patient App code exchange rejected (%d): %s", response.status_code, response.text)
            raise EcwAuthError(
                detail=f"eClinicalWorks rejected authorization code ({response.status_code}): {response.text}",
                blocker="Invalid or expired authorization code, or client credentials mismatch",
            )

        if response.status_code == 403:
            logger.error("Patient App code exchange forbidden (403): %s", response.text)
            raise EcwPermissionError(
                detail=f"eClinicalWorks forbidden during code exchange (403): {response.text}",
                blocker="Patient App lacks requested scopes or practice authorization",
            )

        if response.status_code == 429:
            logger.warning("Patient App token endpoint rate limit reached (429)")
            raise EcwServiceUnavailableError(
                detail="eClinicalWorks OAuth token rate limit reached.",
                blocker="eCW OAuth rate limit",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        if response.status_code >= 500:
            logger.error("eCW OAuth server internal error (%d)", response.status_code)
            raise EcwUpstreamError(
                detail=f"eClinicalWorks OAuth server internal error ({response.status_code}).",
                blocker="eCW OAuth server internal outage",
            )

        if response.status_code != 200:
            logger.error("Unexpected status from eCW token endpoint: %d", response.status_code)
            raise EcwUpstreamError(
                detail=f"Unexpected status ({response.status_code}) from eClinicalWorks OAuth token endpoint.",
                blocker="eCW OAuth server unexpected response",
            )

        try:
            token_payload = response.json()
        except Exception as exc:
            logger.error("Failed to parse token payload JSON: %s", exc)
            raise EcwUpstreamError(
                detail="eClinicalWorks OAuth server returned a malformed token response.",
                blocker="eCW OAuth JSON parse failure",
            ) from exc

        if "access_token" not in token_payload:
            logger.error("Patient App token payload missing access_token")
            raise EcwUpstreamError(
                detail="eClinicalWorks OAuth response missing access_token.",
                blocker="Malformed token payload from eCW",
            )

        # Securely store tokens on backend (never returns secrets)
        return ecw_patient_token_store.save_tokens(token_payload)

    async def refresh_access_token(self) -> Dict[str, Any]:
        """Refresh active access token using stored refresh token."""
        self._validate_configuration()

        refresh_token = ecw_patient_token_store.get_refresh_token()
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No stored refresh token available to refresh Patient App access token.",
            )

        client_id = settings.ECW_PATIENT_CLIENT_ID.strip()
        token_url = settings.ECW_PATIENT_TOKEN_URL.strip()

        form_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        }
        if settings.ECW_PATIENT_CLIENT_SECRET and settings.ECW_PATIENT_CLIENT_SECRET.strip():
            form_data["client_secret"] = settings.ECW_PATIENT_CLIENT_SECRET.strip()

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        logger.info("Refreshing Patient App OAuth access token at %s (client_id: %s...)", token_url, client_id[:6])

        client = self._get_http_client()
        try:
            response = await client.post(token_url, data=form_data, headers=headers)
        except Exception as exc:
            logger.error("Error during Patient App token refresh: %s", exc)
            raise EcwServiceUnavailableError(
                detail=f"Unable to reach eCW OAuth token endpoint for refresh: {exc}",
                blocker="eCW OAuth refresh failure",
            ) from exc
        finally:
            if self._custom_http_client is None:
                await client.aclose()

        if response.status_code != 200:
            logger.error("Patient App token refresh failed (%d): %s", response.status_code, response.text)
            raise EcwAuthError(
                detail=f"eClinicalWorks token refresh rejected ({response.status_code}): {response.text}",
                blocker="Token refresh rejected by eCW OAuth server",
            )

        token_payload = response.json()
        return ecw_patient_token_store.save_tokens(token_payload)


ecw_patient_auth_service = EcwPatientAuthService()

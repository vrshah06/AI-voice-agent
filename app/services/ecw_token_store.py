"""eClinicalWorks Patient App OAuth 2.0 State and Token Storage Service.

Provides:
1. RFC 7636 compliant PKCE (Proof Key for Code Exchange) generation.
2. Anti-forgery OAuth state creation and single-use validation (prevents CSRF and replay attacks).
3. Secure backend token storage for SMART on FHIR Patient App OAuth 2.0 access & refresh tokens.
   - Strictly prevents exposure of raw access tokens, refresh tokens, or authorization codes in logs or API responses.
   - Thread-safe state and token management with expiration tracking.
"""
import base64
from datetime import datetime, timezone
import hashlib
import logging
import secrets
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def generate_pkce_pair() -> Tuple[str, str]:
    """Generate RFC 7636 compliant PKCE code_verifier and code_challenge (S256).

    Returns:
        Tuple of (code_verifier, code_challenge).
    """
    # RFC 7636 Section 4.1: code_verifier must be high-entropy cryptographic random string, 43-128 chars.
    # secrets.token_urlsafe(64) produces 86 URL-safe characters.
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return code_verifier, code_challenge


class OAuthStateStore:
    """Thread-safe store for OAuth 2.0 authorization state parameters."""

    def __init__(self, ttl_seconds: int = 900) -> None:
        self._states: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._ttl_seconds = ttl_seconds

    def _purge_expired(self, now: float) -> None:
        """Purge states that have passed their TTL."""
        expired_keys = [
            k for k, v in self._states.items()
            if now - v.get("created_at", 0) > self._ttl_seconds
        ]
        for k in expired_keys:
            self._states.pop(k, None)

    def create_state(
        self,
        redirect_uri: str,
        code_verifier: Optional[str] = None,
        scope: Optional[str] = None,
        practice_code: Optional[str] = None,
    ) -> str:
        """Create a secure random state, record metadata, and return the state string."""
        state = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._purge_expired(now)
            self._states[state] = {
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
                "scope": scope,
                "practice_code": practice_code,
                "created_at": now,
            }
        return state

    def validate_and_consume(self, state: Optional[str]) -> Optional[Dict[str, Any]]:
        """Validate state existence and expiration, consuming it upon successful lookup."""
        if not state or not state.strip():
            return None

        state_key = state.strip()
        now = time.time()
        with self._lock:
            self._purge_expired(now)
            entry = self._states.pop(state_key, None)

        if not entry:
            return None

        if now - entry.get("created_at", 0) > self._ttl_seconds:
            return None

        return entry

    def count(self) -> int:
        """Return the current number of active pending states."""
        with self._lock:
            return len(self._states)


class OAuthTokenStore:
    """Secure in-memory storage for eCW Patient App OAuth 2.0 tokens.

    Ensures access tokens and refresh tokens remain strictly within server memory
    and are never returned in client-facing responses or logs.
    """

    def __init__(self) -> None:
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_type: str = "Bearer"
        self._expires_at: float = 0.0
        self._expires_in: int = 0
        self._scope: Optional[str] = None
        self._patient_id: Optional[str] = None
        self._id_token: Optional[str] = None
        self._created_at: Optional[datetime] = None
        self._lock = threading.Lock()

    def save_tokens(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """Save received OAuth tokens and return a safe summary without secrets."""
        now = time.time()
        expires_in = int(token_data.get("expires_in", 3600))
        patient_context = token_data.get("patient") or token_data.get("patient_id")

        with self._lock:
            self._access_token = token_data.get("access_token")
            if token_data.get("refresh_token"):
                self._refresh_token = token_data.get("refresh_token")
            self._token_type = token_data.get("token_type", "Bearer")
            self._expires_in = expires_in
            self._expires_at = now + expires_in
            self._scope = token_data.get("scope")
            self._patient_id = str(patient_context) if patient_context else None
            self._id_token = token_data.get("id_token")
            self._created_at = datetime.now(timezone.utc)

        logger.info(
            "Saved eCW Patient App OAuth tokens: token_type=%s, expires_in=%ds, has_refresh_token=%s, has_patient_context=%s",
            self._token_type,
            expires_in,
            bool(self._refresh_token),
            bool(self._patient_id),
        )

        return self.get_safe_status()

    def get_access_token(self) -> Optional[str]:
        """Return valid access token if present and unexpired (30-second safety margin)."""
        with self._lock:
            if not self._access_token:
                return None
            if time.time() >= (self._expires_at - 30):
                return None
            return self._access_token

    def get_refresh_token(self) -> Optional[str]:
        """Return the stored refresh token if available."""
        with self._lock:
            return self._refresh_token

    def has_valid_token(self) -> bool:
        """Check whether an active, unexpired access token is available."""
        return self.get_access_token() is not None

    def get_patient_context(self) -> Optional[str]:
        """Return patient ID context if provided during authorization."""
        with self._lock:
            return self._patient_id

    def get_safe_status(self) -> Dict[str, Any]:
        """Return safe metadata about current OAuth token status.

        NEVER includes raw access_token, refresh_token, or id_token.
        """
        now = time.time()
        with self._lock:
            is_valid = bool(self._access_token and now < (self._expires_at - 30))
            remaining_seconds = max(0, int(self._expires_at - now)) if self._expires_at else 0
            return {
                "is_authorized": is_valid,
                "token_type": self._token_type,
                "expires_in_seconds": remaining_seconds,
                "scope": self._scope,
                "has_refresh_token": bool(self._refresh_token),
                "patient_context": self._patient_id,
                "last_authorized_at": self._created_at.isoformat() if self._created_at else None,
            }

    def clear_tokens(self) -> None:
        """Clear all stored tokens."""
        with self._lock:
            self._access_token = None
            self._refresh_token = None
            self._expires_at = 0.0
            self._expires_in = 0
            self._scope = None
            self._patient_id = None
            self._id_token = None
            self._created_at = None
        logger.info("Cleared stored eCW Patient App OAuth tokens.")


# Global singleton instances for Patient App
ecw_patient_state_store = OAuthStateStore(ttl_seconds=900)
ecw_patient_token_store = OAuthTokenStore()

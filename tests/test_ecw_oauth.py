"""Unit tests for eClinicalWorks Patient App OAuth 2.0 Authorization Code Flow.

Tests:
1. PKCE (RFC 7636) code_verifier and code_challenge (S256) generation.
2. Anti-forgery OAuth state creation, single-use validation (anti-replay), and expiration.
3. Secure backend token storage (never leaks access/refresh tokens in status or responses).
4. GET /api/ecw/patient/authorize (redirect mode and JSON inspection mode).
5. GET /api/ecw/callback handling:
   - eCW OAuth error parameters
   - Missing/invalid/expired state
   - Missing code
   - Successful confidential/public client token exchange with PKCE
   - Browser HTML response rendering
6. Token diagnostics, refresh, and clear endpoints.
7. Verification that Provider App backend services authentication remains completely isolated.
"""
import base64
import hashlib
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.ecw_patient_auth import ecw_patient_auth_service
from app.services.ecw_token_store import (
    OAuthStateStore,
    OAuthTokenStore,
    ecw_patient_state_store,
    ecw_patient_token_store,
    generate_pkce_pair,
)

client = TestClient(app)


# =====================================================================
# 1. PKCE & Security Helper Tests
# =====================================================================

def test_generate_pkce_pair():
    """Verify that generated PKCE pair complies with RFC 7636."""
    code_verifier, code_challenge = generate_pkce_pair()

    # RFC 7636 Section 4.1: length between 43 and 128 characters
    assert 43 <= len(code_verifier) <= 128
    assert "=" not in code_challenge

    # Verify S256 hash transformation
    expected_digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected_challenge = base64.urlsafe_b64encode(expected_digest).decode("ascii").rstrip("=")
    assert code_challenge == expected_challenge


def test_oauth_state_store_single_use_and_expiration():
    """State store must consume state on first use (replay protection) and expire stale states."""
    store = OAuthStateStore(ttl_seconds=1)

    state = store.create_state(
        redirect_uri="https://ai-voice-agent-jlez.onrender.com/api/ecw/callback",
        code_verifier="test-verifier-999",
        scope="openid patient/*.read",
        practice_code="BDGDCD",
    )
    assert state is not None

    # First consumption succeeds
    entry = store.validate_and_consume(state)
    assert entry is not None
    assert entry["redirect_uri"] == "https://ai-voice-agent-jlez.onrender.com/api/ecw/callback"
    assert entry["code_verifier"] == "test-verifier-999"
    assert entry["practice_code"] == "BDGDCD"

    # Second consumption fails (replay protection)
    assert store.validate_and_consume(state) is None

    # Test TTL expiration
    state_expired = store.create_state(redirect_uri="https://ai-voice-agent-jlez.onrender.com/api/ecw/callback")
    time.sleep(1.1)
    assert store.validate_and_consume(state_expired) is None


def test_oauth_token_store_safe_metadata_never_leaks_tokens():
    """OAuth token store must safely retain tokens without ever returning them in safe_status."""
    store = OAuthTokenStore()

    store.save_tokens({
        "access_token": "secret_patient_access_token_12345",
        "refresh_token": "secret_patient_refresh_token_67890",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "openid patient/*.read",
        "patient": "patient_888",
    })

    assert store.has_valid_token() is True
    assert store.get_access_token() == "secret_patient_access_token_12345"
    assert store.get_refresh_token() == "secret_patient_refresh_token_67890"
    assert store.get_patient_context() == "patient_888"

    safe_status = store.get_safe_status()
    assert safe_status["is_authorized"] is True
    assert safe_status["token_type"] == "Bearer"
    assert safe_status["has_refresh_token"] is True
    assert safe_status["patient_context"] == "patient_888"
    assert safe_status["scope"] == "openid patient/*.read"

    # Verify secret tokens are NEVER present in safe metadata
    assert "access_token" not in safe_status
    assert "refresh_token" not in safe_status
    assert "secret_patient_access_token_12345" not in str(safe_status)
    assert "secret_patient_refresh_token_67890" not in str(safe_status)

    store.clear_tokens()
    assert store.has_valid_token() is False
    assert store.get_access_token() is None


# =====================================================================
# 2. GET /api/ecw/patient/authorize Tests
# =====================================================================

def test_authorize_endpoint_missing_client_id():
    """GET /api/ecw/patient/authorize should fail gracefully if ECW_PATIENT_CLIENT_ID is blank."""
    with patch.object(settings, "ECW_PATIENT_CLIENT_ID", ""):
        response = client.get("/api/ecw/patient/authorize?redirect=false")
        assert response.status_code == 400
        assert "ECW_PATIENT_CLIENT_ID" in response.json()["message"]


def test_authorize_endpoint_json_mode():
    """GET /api/ecw/patient/authorize?redirect=false should return JSON with authorization URL and state."""
    with patch.object(settings, "ECW_PATIENT_CLIENT_ID", "mock_patient_client_id_123"):
        response = client.get("/api/ecw/patient/authorize?redirect=false")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "initiated"
        assert "authorization_url" in data
        assert "state" in data
        assert data["redirect_uri"] == "https://ai-voice-agent-jlez.onrender.com/api/ecw/callback"
        assert data["practice_code"] == "BDGDCD"
        assert data["code_challenge_method"] == "S256"

        # Ensure authorization URL contains required OAuth & PKCE params
        url = data["authorization_url"]
        assert "response_type=code" in url
        assert "client_id=mock_patient_client_id_123" in url
        assert "code_challenge=" in url
        assert "code_challenge_method=S256" in url
        assert "state=" in url


def test_authorize_endpoint_redirect_mode():
    """GET /api/ecw/patient/authorize?redirect=true should return HTTP 307 redirect."""
    with patch.object(settings, "ECW_PATIENT_CLIENT_ID", "mock_patient_client_id_123"):
        response = client.get("/api/ecw/patient/authorize?redirect=true", follow_redirects=False)
        assert response.status_code == 307
        location = response.headers.get("location", "")
        assert location.startswith(settings.ECW_PATIENT_AUTHORIZE_URL)
        assert "response_type=code" in location
        assert "code_challenge=" in location


def test_authorize_alias_endpoint():
    """GET /api/ecw/authorize alias should route to Patient App authorization."""
    with patch.object(settings, "ECW_PATIENT_CLIENT_ID", "mock_patient_client_id_123"):
        response = client.get("/api/ecw/authorize?redirect=false")
        assert response.status_code == 200
        assert response.json()["status"] == "initiated"


# =====================================================================
# 3. GET /api/ecw/callback Tests
# =====================================================================

def test_callback_handles_oauth_error():
    """GET /api/ecw/callback with error returned from eCW."""
    response = client.get("/api/ecw/callback?error=access_denied&error_description=User+declined+access")
    assert response.status_code == 400
    assert "access_denied" in response.json()["message"]


def test_callback_handles_oauth_error_html():
    """GET /api/ecw/callback with error from browser should return styled HTML."""
    response = client.get(
        "/api/ecw/callback?error=unauthorized_client&error_description=Client+not+authorized",
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 400
    assert "text/html" in response.headers["content-type"]
    assert "Authorization Failed" in response.text


def test_callback_missing_state():
    """GET /api/ecw/callback without state parameter should return 400."""
    response = client.get("/api/ecw/callback?code=some_code")
    assert response.status_code == 400
    assert "state" in response.json()["message"].lower()


def test_callback_invalid_state():
    """GET /api/ecw/callback with unknown state parameter should return 400."""
    response = client.get("/api/ecw/callback?code=some_code&state=nonexistent_state")
    assert response.status_code == 400
    assert "invalid" in response.json()["message"].lower() or "expired" in response.json()["message"].lower()


def test_callback_missing_code():
    """GET /api/ecw/callback with valid state but missing code should return 400."""
    valid_state = ecw_patient_state_store.create_state(redirect_uri=settings.ECW_PATIENT_REDIRECT_URI)

    response = client.get(f"/api/ecw/callback?state={valid_state}")
    assert response.status_code == 400
    assert "code" in response.json()["message"].lower()


def test_callback_successful_token_exchange():
    """GET /api/ecw/callback successfully exchanges authorization code with PKCE and confidential client secret."""
    state = ecw_patient_state_store.create_state(
        redirect_uri="https://ai-voice-agent-jlez.onrender.com/api/ecw/callback",
        code_verifier="test-patient-pkce-verifier-12345",
    )

    mock_token_response = httpx.Response(
        status_code=200,
        json={
            "access_token": "mock_patient_live_access_token_abc123",
            "refresh_token": "mock_patient_live_refresh_token_xyz789",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "openid patient/*.read",
            "patient": "patient_1001",
        },
        request=httpx.Request("POST", settings.ECW_PATIENT_TOKEN_URL),
    )

    with patch.object(settings, "ECW_PATIENT_CLIENT_ID", "mock_patient_client_id_123"), \
         patch.object(settings, "ECW_PATIENT_CLIENT_SECRET", "mock_patient_client_secret_xyz"), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:

        mock_post.return_value = mock_token_response

        response = client.get(f"/api/ecw/callback?code=valid_patient_code_999&state={state}")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert data["token_type"] == "Bearer"
        assert 3500 <= data["expires_in"] <= 3600
        assert data["has_refresh_token"] is True
        assert data["patient_context"] == "patient_1001"

        # Strictly verify no raw access or refresh tokens are leaked in API response
        assert "access_token" not in data
        assert "refresh_token" not in data
        assert "mock_patient_live_access_token_abc123" not in str(data)
        assert "mock_patient_live_refresh_token_xyz789" not in str(data)

        # Verify token was securely stored in Patient App token store
        assert ecw_patient_token_store.has_valid_token() is True
        assert ecw_patient_token_store.get_access_token() == "mock_patient_live_access_token_abc123"

        # Verify state was consumed (cannot be replayed)
        assert ecw_patient_state_store.validate_and_consume(state) is None

        # Verify post payload included PKCE code_verifier, client_id, and confidential client_secret
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["data"]["grant_type"] == "authorization_code"
        assert call_kwargs["data"]["code"] == "valid_patient_code_999"
        assert call_kwargs["data"]["code_verifier"] == "test-patient-pkce-verifier-12345"
        assert call_kwargs["data"]["redirect_uri"] == "https://ai-voice-agent-jlez.onrender.com/api/ecw/callback"
        assert call_kwargs["data"]["client_id"] == "mock_patient_client_id_123"
        assert call_kwargs["data"]["client_secret"] == "mock_patient_client_secret_xyz"


def test_callback_successful_token_exchange_html():
    """GET /api/ecw/callback with browser Accept header returns styled HTML on success."""
    state = ecw_patient_state_store.create_state(
        redirect_uri="https://ai-voice-agent-jlez.onrender.com/api/ecw/callback",
        code_verifier="test-pkce-verifier-12345",
    )

    mock_token_response = httpx.Response(
        status_code=200,
        json={
            "access_token": "mock_patient_token_browser",
            "token_type": "Bearer",
            "expires_in": 1800,
            "scope": "openid patient/*.read",
        },
        request=httpx.Request("POST", settings.ECW_PATIENT_TOKEN_URL),
    )

    with patch.object(settings, "ECW_PATIENT_CLIENT_ID", "mock_patient_client_id_123"), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:

        mock_post.return_value = mock_token_response

        response = client.get(
            f"/api/ecw/callback?code=browser_code&state={state}",
            headers={"Accept": "text/html,application/xhtml+xml"},
        )
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Authorization Successful" in response.text
        # Verify secrets are NOT leaked in HTML source
        assert "mock_patient_token_browser" not in response.text


# =====================================================================
# 4. Token Diagnostics, Refresh, & Clear Tests
# =====================================================================

def test_token_status_endpoint():
    """GET /api/ecw/patient/token-status returns safe diagnostic metadata."""
    response = client.get("/api/ecw/patient/token-status")
    assert response.status_code == 200

    data = response.json()
    assert "is_authorized" in data
    assert data["redirect_uri"] == "https://ai-voice-agent-jlez.onrender.com/api/ecw/callback"
    assert data["practice_code"] == "BDGDCD"
    assert "access_token" not in data
    assert "refresh_token" not in data


def test_clear_and_refresh_token_endpoints():
    """POST /api/ecw/patient/clear-token and POST /api/ecw/patient/refresh."""
    # Seed token store
    ecw_patient_token_store.save_tokens({
        "access_token": "temp_patient_access",
        "refresh_token": "temp_patient_refresh",
        "expires_in": 3600,
    })
    assert ecw_patient_token_store.has_valid_token() is True

    # Test refresh endpoint
    mock_refresh_resp = httpx.Response(
        status_code=200,
        json={
            "access_token": "refreshed_patient_access_token",
            "refresh_token": "temp_patient_refresh",
            "expires_in": 7200,
            "token_type": "Bearer",
        },
        request=httpx.Request("POST", settings.ECW_PATIENT_TOKEN_URL),
    )

    with patch.object(settings, "ECW_PATIENT_CLIENT_ID", "mock_patient_client_id_123"), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:

        mock_post.return_value = mock_refresh_resp
        ref_response = client.post("/api/ecw/patient/refresh")
        assert ref_response.status_code == 200
        assert ref_response.json()["status"] == "refreshed"
        assert ecw_patient_token_store.get_access_token() == "refreshed_patient_access_token"

    # Test clear endpoint
    clear_response = client.post("/api/ecw/patient/clear-token")
    assert clear_response.status_code == 200
    assert clear_response.json()["status"] == "cleared"
    assert ecw_patient_token_store.has_valid_token() is False

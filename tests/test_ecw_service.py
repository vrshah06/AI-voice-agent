"""Tests for eClinicalWorks (eCW) SMART Backend Services and FHIR operations."""
import asyncio
import pytest
import httpx
from unittest.mock import MagicMock

from app.core.config import settings
from app.services.ecw_service import EcwService, VerifiedPatientRecord


@pytest.fixture
def ecw_svc():
    return EcwService()


def test_token_acquisition_success(ecw_svc, monkeypatch):
    """Test successful OAuth 2.0 token acquisition via client_credentials."""
    monkeypatch.setattr(settings, "ECW_CLIENT_ID", "test-client-id-abc")
    monkeypatch.setattr(settings, "ECW_TOKEN_URL", "https://mock-oauth.ecw.com/token")

    mock_resp = httpx.Response(
        status_code=200,
        json={
            "access_token": "mock-ecw-access-token-xyz",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "system/Patient.read",
        },
        request=httpx.Request("POST", "https://mock-oauth.ecw.com/token"),
    )

    async def mock_post(*args, **kwargs):
        # Validate that client_assertion was passed in form data
        data = kwargs.get("data", {})
        assert data.get("grant_type") == "client_credentials"
        assert data.get("client_assertion_type") == "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
        assert "client_assertion" in data
        return mock_resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.post = mock_post
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    ecw_svc._custom_http_client = mock_client

    token = asyncio.run(ecw_svc.get_access_token())
    assert token == "mock-ecw-access-token-xyz"
    assert ecw_svc._cached_token == "mock-ecw-access-token-xyz"


def test_token_acquisition_failure(ecw_svc, monkeypatch):
    """Test handling of invalid_client or authentication failure."""
    monkeypatch.setattr(settings, "ECW_CLIENT_ID", "invalid-client")
    monkeypatch.setattr(settings, "ECW_TOKEN_URL", "https://mock-oauth.ecw.com/token")

    mock_resp = httpx.Response(
        status_code=401,
        text='{"error": "invalid_client", "error_description": "Client authentication failed"}',
        request=httpx.Request("POST", "https://mock-oauth.ecw.com/token"),
    )

    async def mock_post(*args, **kwargs):
        return mock_resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.post = mock_post
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    ecw_svc._custom_http_client = mock_client

    with pytest.raises(PermissionError) as exc_info:
        asyncio.run(ecw_svc.get_access_token(force_refresh=True))

    assert "eCW authentication failed with status 401" in str(exc_info.value)


def test_patient_search_verified_single_match(ecw_svc, monkeypatch):
    """Test patient search returning a single verified FHIR Patient resource."""
    monkeypatch.setattr(settings, "ECW_ENABLED", True)
    monkeypatch.setattr(settings, "ECW_CLIENT_ID", "test-client")
    monkeypatch.setattr(settings, "ECW_FHIR_BASE_URL", "https://staging-fhir.ecw.com/r4/12345")

    # Mock token cache
    ecw_svc._cached_token = "mock-valid-bearer-token"
    ecw_svc._token_expires_at = 9999999999.0

    mock_bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": 1,
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "ECW-PAT-987",
                    "name": [{"family": "Smith", "given": ["John"]}],
                    "birthDate": "1980-05-15",
                    "gender": "male",
                    "telecom": [{"system": "phone", "value": "555-123-4567"}],
                }
            }
        ],
    }

    mock_resp = httpx.Response(
        status_code=200,
        json=mock_bundle,
        request=httpx.Request("GET", "https://staging-fhir.ecw.com/r4/12345/Patient"),
    )

    async def mock_get(url, **kwargs):
        params = kwargs.get("params", {})
        assert params.get("family") == "Smith"
        assert params.get("given") == "John"
        assert params.get("birthdate") == "1980-05-15"
        headers = kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer mock-valid-bearer-token"
        return mock_resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = mock_get
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    ecw_svc._custom_http_client = mock_client

    result = asyncio.run(
        ecw_svc.search_and_verify_patient(
            first_name="John",
            last_name="Smith",
            date_of_birth="1980-05-15",
        )
    )

    assert result.verified is True
    assert result.patient_id == "ECW-PAT-987"
    assert result.match_status == "verified"
    assert "John Smith" in result.message


def test_patient_search_multiple_matches_safety(ecw_svc, monkeypatch):
    """Multiple matches must withhold details and return unverified for privacy and safety."""
    monkeypatch.setattr(settings, "ECW_ENABLED", True)
    monkeypatch.setattr(settings, "ECW_CLIENT_ID", "test-client")
    monkeypatch.setattr(settings, "ECW_FHIR_BASE_URL", "https://staging-fhir.ecw.com/r4/12345")

    ecw_svc._cached_token = "mock-valid-bearer-token"
    ecw_svc._token_expires_at = 9999999999.0

    mock_bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": 2,
        "entry": [
            {"resource": {"id": "PAT-1", "birthDate": "1980-05-15"}},
            {"resource": {"id": "PAT-2", "birthDate": "1980-05-15"}},
        ],
    }

    mock_resp = httpx.Response(
        status_code=200,
        json=mock_bundle,
        request=httpx.Request("GET", "https://staging-fhir.ecw.com/r4/12345/Patient"),
    )

    async def mock_get(url, **kwargs):
        return mock_resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = mock_get
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    ecw_svc._custom_http_client = mock_client

    result = asyncio.run(
        ecw_svc.search_and_verify_patient(
            first_name="John",
            last_name="Smith",
            date_of_birth="1980-05-15",
        )
    )

    assert result.verified is False
    assert result.match_status == "multiple_matches"
    assert "receptionist" in result.message.lower()


def test_patient_search_no_matches(ecw_svc, monkeypatch):
    """Patient search returning 0 matches must return not_found safely."""
    monkeypatch.setattr(settings, "ECW_ENABLED", True)
    monkeypatch.setattr(settings, "ECW_CLIENT_ID", "test-client")
    monkeypatch.setattr(settings, "ECW_FHIR_BASE_URL", "https://staging-fhir.ecw.com/r4/12345")

    ecw_svc._cached_token = "mock-valid-bearer-token"
    ecw_svc._token_expires_at = 9999999999.0

    mock_bundle = {"resourceType": "Bundle", "type": "searchset", "total": 0, "entry": []}
    mock_resp = httpx.Response(
        status_code=200,
        json=mock_bundle,
        request=httpx.Request("GET", "https://staging-fhir.ecw.com/r4/12345/Patient"),
    )

    async def mock_get(url, **kwargs):
        return mock_resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = mock_get
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    ecw_svc._custom_http_client = mock_client

    result = asyncio.run(
        ecw_svc.search_and_verify_patient(
            first_name="Nonexistent",
            last_name="Person",
            date_of_birth="1999-01-01",
        )
    )

    assert result.verified is False
    assert result.match_status == "not_found"

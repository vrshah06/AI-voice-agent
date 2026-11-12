"""Unit tests for eClinicalWorks (eCW) SMART Backend Services client (app/services/ecw_client.py)."""
import asyncio
import time
from unittest.mock import MagicMock
import httpx
import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.core.jwks import KeyManager
from app.models.patient import (
    PatientDemographicsResponse,
    PatientListResponse,
    PatientSearchMatchResponse,
    PatientSearchResponse,
)
from app.services.ecw_client import (
    EcwClient,
    EcwAuthError,
    EcwClientError,
    EcwPermissionError,
    EcwNotFoundError,
    EcwUpstreamError,
    EcwServiceUnavailableError,
)


@pytest.fixture
def mock_settings():
    """Create isolated settings for unit testing."""
    return Settings(
        ECW_CLIENT_ID="test-client-id-xyz",
        ECW_TOKEN_URL="https://staging-oauthserver.ecwcloud.com/oauth/oauth2/token",
        ECW_FHIR_BASE_URL="https://staging-fhir.ecwcloud.com/fhir/r4/TEST01",
        ECW_SCOPES="system/Patient.read",
        ECW_ASSERTION_EXPIRY_SECONDS=300,
    )


@pytest.fixture
def ecw_client_instance(mock_settings):
    """Instantiate EcwClient with isolated settings and default key manager."""
    return EcwClient(settings_obj=mock_settings)


# =====================================================================
# Token Acquisition & Lifecycle Tests
# =====================================================================

def test_token_acquisition_success(ecw_client_instance):
    """Test successful OAuth 2.0 token acquisition via client_credentials and signed assertion."""
    mock_resp = httpx.Response(
        status_code=200,
        json={
            "access_token": "mock-ecw-access-token-12345",
            "token_type": "Bearer",
            "expires_in": 300,
            "scope": "system/Patient.read",
        },
        request=httpx.Request("POST", "https://staging-oauthserver.ecwcloud.com/oauth/oauth2/token"),
    )

    async def mock_post(url, data=None, headers=None, **kwargs):
        assert data is not None
        assert data.get("grant_type") == "client_credentials"
        assert data.get("client_assertion_type") == "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
        assert "client_assertion" in data
        assert data.get("scope") == "system/Patient.read"
        return mock_resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.post = mock_post
    ecw_client_instance._custom_http_client = mock_client

    token = asyncio.run(ecw_client_instance.get_access_token())
    assert token == "mock-ecw-access-token-12345"
    assert ecw_client_instance._cached_token == "mock-ecw-access-token-12345"


def test_token_caching_avoids_redundant_calls(ecw_client_instance):
    """Cached token should be reused without making network requests if still valid."""
    ecw_client_instance._cached_token = "cached-valid-token"
    ecw_client_instance._token_expires_at = time.time() + 200

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.post = MagicMock(side_effect=AssertionError("Should not make network call for cached token"))
    ecw_client_instance._custom_http_client = mock_client

    token = asyncio.run(ecw_client_instance.get_access_token())
    assert token == "cached-valid-token"


def test_token_acquisition_unconfigured_client_id(mock_settings):
    """Unconfigured client ID must immediately raise EcwAuthError identifying the blocker."""
    mock_settings.ECW_CLIENT_ID = ""
    client = EcwClient(settings_obj=mock_settings)

    with pytest.raises(EcwAuthError) as exc_info:
        asyncio.run(client.get_access_token())

    assert exc_info.value.status_code == 401
    assert "ECW_CLIENT_ID is missing" in exc_info.value.detail
    assert "Missing ECW_CLIENT_ID" in exc_info.value.blocker


def test_token_acquisition_rejected_401(ecw_client_instance):
    """eCW token endpoint returning 401 must raise EcwAuthError."""
    mock_resp = httpx.Response(
        status_code=401,
        text='{"error": "invalid_client", "error_description": "Bad client credentials"}',
        request=httpx.Request("POST", "https://staging-oauthserver.ecwcloud.com/oauth/oauth2/token"),
    )

    async def mock_post(*args, **kwargs):
        return mock_resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.post = mock_post
    ecw_client_instance._custom_http_client = mock_client

    with pytest.raises(EcwAuthError) as exc_info:
        asyncio.run(ecw_client_instance.get_access_token(force_refresh=True))

    assert exc_info.value.status_code == 401
    assert "eClinicalWorks token request rejected (401)" in exc_info.value.detail


def test_token_acquisition_timeout(ecw_client_instance):
    """Network timeout reaching OAuth server must raise EcwServiceUnavailableError (503)."""
    async def mock_post(*args, **kwargs):
        raise httpx.TimeoutException("OAuth connect timeout")

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.post = mock_post
    ecw_client_instance._custom_http_client = mock_client

    with pytest.raises(EcwServiceUnavailableError) as exc_info:
        asyncio.run(ecw_client_instance.get_access_token(force_refresh=True))

    assert exc_info.value.status_code == 503


# =====================================================================
# Patient Retrieval (GET /Patient/{id}) Tests
# =====================================================================

def test_get_patient_by_id_success(ecw_client_instance):
    """Test retrieving patient demographics with strict field filtering (no sensitive clinical data)."""
    ecw_client_instance._cached_token = "mock-valid-token"
    ecw_client_instance._token_expires_at = time.time() + 300

    raw_fhir_patient = {
        "resourceType": "Patient",
        "id": "12345",
        "active": True,
        "name": [
            {
                "use": "official",
                "family": "Smith",
                "given": ["Jane", "Marie"],
            }
        ],
        "telecom": [
            {"system": "phone", "value": "561-555-0199", "use": "mobile"},
            {"system": "email", "value": "jane.smith@example.com"},
        ],
        "gender": "female",
        "birthDate": "1985-04-12",
        "address": [
            {
                "use": "home",
                "line": ["100 Ocean Blvd", "Suite 200"],
                "city": "Boynton Beach",
                "state": "FL",
                "postalCode": "33435",
            }
        ],
        "communication": [
            {
                "language": {"text": "English"},
                "preferred": True,
            }
        ],
        # Simulated sensitive fields that MUST NOT be exposed by receptionist model
        "condition": [{"clinicalStatus": "active", "code": {"text": "Hypertension"}}],
        "medication": [{"display": "Lisinopril 10mg"}],
    }

    mock_resp = httpx.Response(
        status_code=200,
        json=raw_fhir_patient,
        request=httpx.Request("GET", "https://staging-fhir.ecwcloud.com/fhir/r4/TEST01/Patient/12345"),
    )

    async def mock_get(url, headers=None, **kwargs):
        assert url == "https://staging-fhir.ecwcloud.com/fhir/r4/TEST01/Patient/12345"
        assert headers.get("Authorization") == "Bearer mock-valid-token"
        return mock_resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = mock_get
    ecw_client_instance._custom_http_client = mock_client

    result = asyncio.run(ecw_client_instance.get_patient_by_id("12345"))

    assert isinstance(result, PatientDemographicsResponse)
    assert result.patient_id == "12345"
    assert result.first_name == "Jane Marie"
    assert result.last_name == "Smith"
    assert result.full_name == "Jane Marie Smith"
    assert result.date_of_birth == "1985-04-12"
    assert result.gender == "female"
    assert result.phone == "561-555-0199"
    assert result.email == "jane.smith@example.com"
    assert result.address is not None
    assert result.address.city == "Boynton Beach"
    assert result.address.state == "FL"
    assert result.preferred_language == "English"
    assert result.active is True

    # Security check: Ensure patient response model does not contain medical details
    dumped = result.model_dump()
    assert "condition" not in dumped
    assert "medication" not in dumped
    assert "clinicalStatus" not in dumped


def test_get_patient_by_id_404_not_found(ecw_client_instance):
    """When eCW returns 404, EcwNotFoundError must be raised (never mock data)."""
    ecw_client_instance._cached_token = "mock-token"
    ecw_client_instance._token_expires_at = time.time() + 300

    mock_resp = httpx.Response(
        status_code=404,
        json={"resourceType": "OperationOutcome", "issue": [{"diagnostics": "Patient not found"}]},
        request=httpx.Request("GET", "https://staging-fhir.ecwcloud.com/fhir/r4/TEST01/Patient/99999"),
    )

    async def mock_get(*args, **kwargs):
        return mock_resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = mock_get
    ecw_client_instance._custom_http_client = mock_client

    with pytest.raises(EcwNotFoundError) as exc_info:
        asyncio.run(ecw_client_instance.get_patient_by_id("99999"))

    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()


def test_get_patient_by_id_403_forbidden(ecw_client_instance):
    """When eCW returns 403, EcwPermissionError must be raised identifying practice permission blocker."""
    ecw_client_instance._cached_token = "mock-token"
    ecw_client_instance._token_expires_at = time.time() + 300

    mock_resp = httpx.Response(
        status_code=403,
        text="Forbidden: Insufficient scopes",
        request=httpx.Request("GET", "https://staging-fhir.ecwcloud.com/fhir/r4/TEST01/Patient/12345"),
    )

    async def mock_get(*args, **kwargs):
        return mock_resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = mock_get
    ecw_client_instance._custom_http_client = mock_client

    with pytest.raises(EcwPermissionError) as exc_info:
        asyncio.run(ecw_client_instance.get_patient_by_id("12345"))

    assert exc_info.value.status_code == 403
    assert "403 Forbidden" in exc_info.value.detail
    assert "scopes" in exc_info.value.blocker


def test_get_patient_by_id_auto_refreshes_on_401(ecw_client_instance):
    """When FHIR returns 401, client must refresh token and retry the live request once."""
    calls = []

    async def mock_post(*args, **kwargs):
        return httpx.Response(
            status_code=200,
            json={"access_token": "fresh-token-456", "expires_in": 300},
            request=httpx.Request("POST", "https://staging-oauthserver.ecwcloud.com/oauth/oauth2/token"),
        )

    async def mock_get(url, headers=None, **kwargs):
        calls.append(headers.get("Authorization"))
        if len(calls) == 1:
            # First attempt with stale token returns 401
            return httpx.Response(
                status_code=401,
                text="Unauthorized: token expired",
                request=httpx.Request("GET", url),
            )
        # Second attempt with fresh token succeeds
        return httpx.Response(
            status_code=200,
            json={"resourceType": "Patient", "id": "12345", "name": [{"family": "Smith", "given": ["Jane"]}]},
            request=httpx.Request("GET", url),
        )

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.post = mock_post
    mock_client.get = mock_get
    ecw_client_instance._custom_http_client = mock_client

    # Set initial stale token
    ecw_client_instance._cached_token = "stale-token-123"
    ecw_client_instance._token_expires_at = time.time() + 100

    result = asyncio.run(ecw_client_instance.get_patient_by_id("12345"))

    assert result.patient_id == "12345"
    assert len(calls) == 2
    assert calls[0] == "Bearer stale-token-123"
    assert calls[1] == "Bearer fresh-token-456"


def test_get_patient_by_id_502_upstream_failure(ecw_client_instance):
    """500 or 502 from eCW FHIR server raises EcwUpstreamError."""
    ecw_client_instance._cached_token = "mock-token"
    ecw_client_instance._token_expires_at = time.time() + 300

    mock_resp = httpx.Response(
        status_code=502,
        text="Bad Gateway",
        request=httpx.Request("GET", "https://staging-fhir.ecwcloud.com/fhir/r4/TEST01/Patient/12345"),
    )

    async def mock_get(*args, **kwargs):
        return mock_resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = mock_get
    ecw_client_instance._custom_http_client = mock_client

    with pytest.raises(EcwUpstreamError) as exc_info:
        asyncio.run(ecw_client_instance.get_patient_by_id("12345"))

    assert exc_info.value.status_code == 502


def test_get_patient_by_id_503_timeout(ecw_client_instance):
    """Network timeout or connection error raises EcwServiceUnavailableError (503)."""
    ecw_client_instance._cached_token = "mock-token"
    ecw_client_instance._token_expires_at = time.time() + 300

    async def mock_get(*args, **kwargs):
        raise httpx.ConnectTimeout("Connection to eCW FHIR timed out")

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = mock_get
    ecw_client_instance._custom_http_client = mock_client

    with pytest.raises(EcwServiceUnavailableError) as exc_info:
        asyncio.run(ecw_client_instance.get_patient_by_id("12345"))

    assert exc_info.value.status_code == 503


# =====================================================================
# Targeted Name & DOB Search Unit Tests
# =====================================================================

def test_search_patient_by_name_dob_unit_single_match(ecw_client_instance):
    """EcwClient.search_patient_by_name_dob returns single_match on 1 result."""
    ecw_client_instance._cached_token = "mock-token"
    ecw_client_instance._token_expires_at = time.time() + 300

    bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": 1,
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "1001",
                    "name": [{"family": "Smith", "given": ["Alex"]}],
                    "birthDate": "1985-06-15",
                    "active": True,
                }
            }
        ],
    }

    mock_resp = httpx.Response(
        status_code=200,
        json=bundle,
        request=httpx.Request("GET", "https://staging-fhir.ecwcloud.com/fhir/r4/TEST01/Patient"),
    )

    async def mock_get(url, params=None, **kwargs):
        assert params.get("given") == "Alex"
        assert params.get("family") == "Smith"
        assert params.get("birthdate") == "1985-06-15"
        return mock_resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = mock_get
    ecw_client_instance._custom_http_client = mock_client

    res = asyncio.run(
        ecw_client_instance.search_patient_by_name_dob(
            first_name="Alex",
            last_name="Smith",
            dob="1985-06-15",
        )
    )

    assert isinstance(res, PatientSearchMatchResponse)
    assert res.match_status == "single_match"
    assert res.match_count == 1
    assert res.patients[0].full_name == "Alex Smith"
    assert res.patients[0].patient_id == "1001"


# =====================================================================
# Paginated List Patients Unit Tests
# =====================================================================

def test_list_patients_unit_with_pagination(ecw_client_instance):
    """EcwClient.list_patients parses entries and extracts next_page_token."""
    ecw_client_instance._cached_token = "mock-token"
    ecw_client_instance._token_expires_at = time.time() + 300

    bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": 2,
        "link": [
            {"relation": "self", "url": "https://staging-fhir.ecwcloud.com/fhir/r4/TEST01/Patient?_count=2"},
            {"relation": "next", "url": "https://staging-fhir.ecwcloud.com/fhir/r4/TEST01/Patient?_count=2&page=2"},
        ],
        "entry": [
            {"resource": {"resourceType": "Patient", "id": "1", "name": [{"family": "One"}]}},
            {"resource": {"resourceType": "Patient", "id": "2", "name": [{"family": "Two"}]}},
        ],
    }

    mock_resp = httpx.Response(
        status_code=200,
        json=bundle,
        request=httpx.Request("GET", "https://staging-fhir.ecwcloud.com/fhir/r4/TEST01/Patient"),
    )

    async def mock_get(url, params=None, **kwargs):
        return mock_resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = mock_get
    ecw_client_instance._custom_http_client = mock_client

    res = asyncio.run(ecw_client_instance.list_patients(page_size=2))

    assert isinstance(res, PatientListResponse)
    assert res.count == 2
    assert res.has_more is True
    assert "page=2" in res.next_page_token


def test_list_patients_unit_unsupported_population_wide_restriction(ecw_client_instance):
    """EcwClient.list_patients raises EcwClientError 400 when eCW rejects unfiltered listing."""
    ecw_client_instance._cached_token = "mock-token"
    ecw_client_instance._token_expires_at = time.time() + 300

    mock_resp = httpx.Response(
        status_code=400,
        text='{"resourceType": "OperationOutcome", "issue": [{"diagnostics": "Search without search criteria is not supported for resource type Patient"}]}',
        request=httpx.Request("GET", "https://staging-fhir.ecwcloud.com/fhir/r4/TEST01/Patient"),
    )

    async def mock_get(url, params=None, **kwargs):
        return mock_resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = mock_get
    ecw_client_instance._custom_http_client = mock_client

    with pytest.raises(EcwClientError) as exc_info:
        asyncio.run(ecw_client_instance.list_patients(page_size=20))

    assert exc_info.value.status_code == 400
    assert "restricts population-wide patient listing" in exc_info.value.detail


# =====================================================================
# Provider App Token Caching & Scheduling Access Tests
# =====================================================================

def test_get_provider_access_token_caching(ecw_client_instance):
    """get_provider_access_token reuses cached token when valid and reacquires when expired."""
    ecw_client_instance._cached_token = "cached_provider_token_123"
    ecw_client_instance._token_expires_at = time.time() + 300

    token = asyncio.run(ecw_client_instance.get_provider_access_token())
    assert token == "cached_provider_token_123"

    # Status check
    status_info = asyncio.run(ecw_client_instance.get_provider_token_cache_status())
    assert status_info["is_cached"] is True
    assert status_info["is_valid"] is True
    assert status_info["token_type"] == "Bearer"
    assert "cached_provider_token_123" not in str(status_info)


def test_test_scheduling_access_scope_restricted(ecw_client_instance):
    """test_scheduling_access analyzes system/Patient.read and detects 403 forbidden."""
    ecw_client_instance._cached_token = "mock-token-abc"
    ecw_client_instance._token_expires_at = time.time() + 300

    mock_resp = httpx.Response(
        status_code=403,
        text='{"resourceType": "OperationOutcome", "issue": [{"severity": "error", "code": "forbidden", "diagnostics": "Access denied"}]}',
        request=httpx.Request("GET", "https://staging-fhir.ecwcloud.com/fhir/r4/TEST01/Slot"),
    )

    async def mock_get(url, params=None, **kwargs):
        return mock_resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = mock_get
    ecw_client_instance._custom_http_client = mock_client

    report = asyncio.run(ecw_client_instance.test_scheduling_access(resource="Slot"))

    assert report["status"] == "scope_restricted"
    assert report["authenticated"] is True
    assert report["http_status"] == 403
    assert report["token_type"] == "Bearer"
    assert "expiry" in report
    assert report["scopes"] == "system/Patient.read"
    assert report["api_response_status"] == "forbidden_scope_or_practice_restriction"
    assert report["scope_analysis"]["approved_scope"] == "system/Patient.read"
    assert "system/Patient.read" in report["scope_analysis"]["scope_status"]
    assert "eClinicalWorks SMART Backend Services requires explicit scheduling scopes" in report["scope_analysis"]["scheduling_authorization_issue"]
    assert "not confirmed eCW-approved scopes; do not add them without official eCW confirmation" in report["scope_analysis"]["scheduling_authorization_issue"]
    assert report["scheduling_probe"]["http_status"] == 403
    assert "mock-token-abc" not in str(report)


def test_test_scheduling_access_success(ecw_client_instance):
    """test_scheduling_access parses 200 OK bundle summary without exposing tokens or PHI."""
    ecw_client_instance._cached_token = "mock-token-abc"
    ecw_client_instance._token_expires_at = time.time() + 300

    mock_resp = httpx.Response(
        status_code=200,
        json={
            "resourceType": "Bundle",
            "type": "searchset",
            "total": 3,
            "entry": [{"resource": {"resourceType": "Slot", "id": "slot-1"}}],
        },
        request=httpx.Request("GET", "https://staging-fhir.ecwcloud.com/fhir/r4/TEST01/Slot"),
    )

    async def mock_get(url, params=None, **kwargs):
        return mock_resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = mock_get
    ecw_client_instance._custom_http_client = mock_client

    report = asyncio.run(ecw_client_instance.test_scheduling_access(resource="Slot"))

    assert report["status"] == "success"
    assert report["http_status"] == 200
    assert report["token_type"] == "Bearer"
    assert report["expiry"] > 0
    assert report["scopes"] == "system/Patient.read"
    assert report["api_response_status"] == "authorized"
    assert report["scheduling_probe"]["outcome"] == "authorized"
    assert report["scheduling_probe"]["bundle_summary"]["total"] == 3
    assert report["scheduling_probe"]["bundle_summary"]["entry_count"] == 1
    assert "mock-token-abc" not in str(report)


def test_test_scheduling_access_invalid_resource(ecw_client_instance):
    """test_scheduling_access rejects unsupported resources with 400 Bad Request."""
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(ecw_client_instance.test_scheduling_access(resource="InvalidResource"))

    assert exc_info.value.status_code == 400
    assert "Allowed resources" in exc_info.value.detail


# =====================================================================
# Encounter.read & Appointment Mapping Unit Tests
# =====================================================================

def test_parse_fhir_datetime_timezone_conversion():
    """Verify ISO-8601 parsing converts UTC / offsets to Eastern Time without fabricating times for date-only."""
    from app.services.ecw_client import parse_fhir_datetime

    # 1. UTC Z timestamp (15:30 UTC is 10:30 AM EST in winter)
    d1, t1 = parse_fhir_datetime("2026-11-20T15:30:00Z")
    assert d1 == "2026-11-20"
    assert t1 == "10:30 AM"

    # 2. Offset timestamp (-05:00 EST)
    d2, t2 = parse_fhir_datetime("2026-11-20T10:30:00-05:00")
    assert d2 == "2026-11-20"
    assert t2 == "10:30 AM"

    # 3. Afternoon offset (-05:00)
    d3, t3 = parse_fhir_datetime("2026-12-05T14:00:00-05:00")
    assert d3 == "2026-12-05"
    assert t3 == "02:00 PM"

    # 4. Date-only string (no fabricated time)
    d4, t4 = parse_fhir_datetime("2026-11-20")
    assert d4 == "2026-11-20"
    assert t4 is None

    # 5. None or empty
    assert parse_fhir_datetime(None) == (None, None)
    assert parse_fhir_datetime("") == (None, None)


def test_normalize_time_str_formats():
    """Verify various 12-hour and 24-hour time formats parse to (hour, minute)."""
    from app.services.ecw_client import normalize_time_str

    assert normalize_time_str("10:30 AM") == (10, 30)
    assert normalize_time_str("10:30AM") == (10, 30)
    assert normalize_time_str("10:30") == (10, 30)
    assert normalize_time_str("14:30") == (14, 30)
    assert normalize_time_str("02:00 PM") == (14, 0)
    assert normalize_time_str("2:00 PM") == (14, 0)
    assert normalize_time_str("invalid") is None
    assert normalize_time_str("") is None


def test_get_patient_encounters_unit_success(ecw_client_instance):
    """Test retrieving encounters bundle and parsing resources."""
    ecw_client_instance._cached_token = "mock-token"
    ecw_client_instance._token_expires_at = time.time() + 300

    bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": 1,
        "entry": [
            {
                "resource": {
                    "resourceType": "Encounter",
                    "id": "enc-001",
                    "status": "planned",
                    "period": {
                        "start": "2026-11-20T10:30:00-05:00",
                        "end": "2026-11-20T11:00:00-05:00",
                    },
                    "participant": [
                        {
                            "individual": {
                                "display": "Dr. Example",
                            }
                        }
                    ],
                    "location": [
                        {
                            "location": {
                                "display": "MD Primary Care",
                            }
                        }
                    ],
                    "type": [
                        {
                            "text": "Follow-up",
                        }
                    ],
                }
            }
        ],
    }

    mock_resp = httpx.Response(
        status_code=200,
        json=bundle,
        request=httpx.Request("GET", "https://staging-fhir.ecwcloud.com/fhir/r4/TEST01/Encounter"),
    )

    async def mock_get(url, params=None, **kwargs):
        assert params.get("patient") == "12345"
        return mock_resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = mock_get
    ecw_client_instance._custom_http_client = mock_client

    encounters = asyncio.run(ecw_client_instance.get_patient_encounters(patient_id="12345"))
    assert len(encounters) == 1
    assert encounters[0]["id"] == "enc-001"

    apt = ecw_client_instance.parse_encounter_to_appointment(encounters[0])
    assert apt.encounter_id == "enc-001"
    assert apt.appointment_date == "2026-11-20"
    assert apt.appointment_time == "10:30 AM"
    assert apt.end_time == "11:00 AM"
    assert apt.status == "planned"
    assert apt.provider == "Dr. Example"
    assert apt.location == "MD Primary Care"
    assert apt.visit_type == "Follow-up"


def test_get_patient_encounters_unit_403_permission_error(ecw_client_instance):
    """Test that HTTP 403 on Encounter raises EcwPermissionError with clear diagnostics."""
    ecw_client_instance._cached_token = "mock-token"
    ecw_client_instance._token_expires_at = time.time() + 300

    mock_resp = httpx.Response(
        status_code=403,
        text="Access denied: Scope Encounter.read required.",
        request=httpx.Request("GET", "https://staging-fhir.ecwcloud.com/fhir/r4/TEST01/Encounter"),
    )

    async def mock_get(url, params=None, **kwargs):
        return mock_resp

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = mock_get
    ecw_client_instance._custom_http_client = mock_client

    with pytest.raises(EcwPermissionError) as exc_info:
        asyncio.run(ecw_client_instance.get_patient_encounters(patient_id="12345"))

    assert exc_info.value.status_code == 403
    assert "Encounter.read" in exc_info.value.detail


def test_filter_appointments_unit():
    """Verify local filtering by appointment_date and appointment_time."""
    from app.models.appointments import AppointmentDetail
    from app.services.ecw_client import ecw_client

    appointments = [
        AppointmentDetail(
            encounter_id="1",
            appointment_date="2026-11-20",
            appointment_time="10:30 AM",
            end_time="11:00 AM",
            status="planned",
        ),
        AppointmentDetail(
            encounter_id="2",
            appointment_date="2026-11-20",
            appointment_time="02:00 PM",
            end_time=None,
            status="planned",
        ),
        AppointmentDetail(
            encounter_id="3",
            appointment_date="2026-12-05",
            appointment_time="10:30 AM",
            end_time=None,
            status="planned",
        ),
    ]

    # Filter by date only
    f_date = ecw_client.filter_appointments(appointments, appointment_date="2026-11-20")
    assert len(f_date) == 2
    assert {a.encounter_id for a in f_date} == {"1", "2"}

    # Filter by time only
    f_time = ecw_client.filter_appointments(appointments, appointment_time="10:30 AM")
    assert len(f_time) == 2
    assert {a.encounter_id for a in f_time} == {"1", "3"}

    # Filter by both date and time
    f_both = ecw_client.filter_appointments(
        appointments,
        appointment_date="2026-11-20",
        appointment_time="10:30 AM",
    )
    assert len(f_both) == 1
    assert f_both[0].encounter_id == "1"



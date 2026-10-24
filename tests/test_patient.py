"""FastAPI integration tests for eClinicalWorks Patient Search and Listing APIs.

Tests all 13 required scenarios:
1. Exact first-name, last-name, and DOB search
2. No matching patient (match_status: no_match, match_count: 0)
3. One matching patient (match_status: single_match, match_count: 1)
4. Multiple matching patients (match_status: multiple_matches, match_count: 2)
5. Invalid DOB (non-ISO format or future date -> 400 Bad Request)
6. Missing required parameters (missing first_name, last_name, or dob -> 422)
7. Authentication failure (401 Unauthorized)
8. Insufficient permissions (403 Forbidden)
9. eCW upstream error (502 Bad Gateway)
10. Patient list pagination (has_more: True, next_page_token provided)
11. No next page (has_more: False, next_page_token is None)
12. Unsupported population-wide search (eCW 400 restriction)
13. Prevention of mock-data fallback (never substitutes synthetic demo patients)
"""
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.patient import (
    PatientAddress,
    PatientDemographicsResponse,
    PatientListResponse,
    PatientMatchSummary,
    PatientSearchMatchResponse,
)
from app.services.ecw_client import (
    EcwAuthError,
    EcwClientError,
    EcwNotFoundError,
    EcwPermissionError,
    EcwServiceUnavailableError,
    EcwUpstreamError,
)


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app)


# =====================================================================
# 1. API One: GET /api/patients/search (Name & DOB Search)
# =====================================================================

def test_search_patient_by_name_dob_exact_single_match(client: TestClient):
    """Scenario 1 & 3: Exact first-name, last-name, and DOB search with one matching patient."""
    mock_response = PatientSearchMatchResponse(
        match_status="single_match",
        match_count=1,
        patients=[
            PatientMatchSummary(
                patient_id="ECW-1001",
                first_name="Alex",
                last_name="Smith",
                full_name="Alex Smith",
                date_of_birth="1985-06-15",
                active=True,
            )
        ],
        identity_verification_required=True,
        notice="Single patient match confirmed. Secondary verification required before disclosing PHI.",
    )

    with patch("app.api.patients.ecw_client.search_patient_by_name_dob", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_response

        response = client.get("/api/patients/search?first_name=Alex&last_name=Smith&dob=1985-06-15")

        assert response.status_code == 200
        data = response.json()

        assert data["match_status"] == "single_match"
        assert data["match_count"] == 1
        assert len(data["patients"]) == 1
        assert data["patients"][0]["patient_id"] == "ECW-1001"
        assert data["patients"][0]["full_name"] == "Alex Smith"
        assert data["patients"][0]["date_of_birth"] == "1985-06-15"
        assert data["identity_verification_required"] is True
        assert "secondary verification required" in data["notice"].lower()

        # Security check: Ensure no sensitive clinical info leaked
        dumped = str(data)
        assert "condition" not in dumped.lower()
        assert "medication" not in dumped.lower()


def test_search_patient_no_match(client: TestClient):
    """Scenario 2: Search returns 0 matching patients."""
    mock_response = PatientSearchMatchResponse(
        match_status="no_match",
        match_count=0,
        patients=[],
        identity_verification_required=True,
        notice="No matching patient records found with the provided name and date of birth.",
    )

    with patch("app.api.patients.ecw_client.search_patient_by_name_dob", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_response

        response = client.get("/api/patients/search?first_name=Unknown&last_name=Person&dob=1990-01-01")

        assert response.status_code == 200
        data = response.json()
        assert data["match_status"] == "no_match"
        assert data["match_count"] == 0
        assert len(data["patients"]) == 0
        assert "no matching patient records" in data["notice"].lower()


def test_search_patient_multiple_matches(client: TestClient):
    """Scenario 4: Search returns multiple matching patients."""
    mock_response = PatientSearchMatchResponse(
        match_status="multiple_matches",
        match_count=2,
        patients=[
            PatientMatchSummary(
                patient_id="ECW-101",
                first_name="Alex",
                last_name="Smith",
                full_name="Alex Smith",
                date_of_birth="1985-06-15",
                active=True,
            ),
            PatientMatchSummary(
                patient_id="ECW-102",
                first_name="Alex",
                last_name="Smith",
                full_name="Alex Smith",
                date_of_birth="1985-06-15",
                active=True,
            ),
        ],
        identity_verification_required=True,
        notice="Multiple matching records found. Detailed disclosure withheld for safety.",
    )

    with patch("app.api.patients.ecw_client.search_patient_by_name_dob", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_response

        response = client.get("/api/patients/search?first_name=Alex&last_name=Smith&dob=1985-06-15")

        assert response.status_code == 200
        data = response.json()
        assert data["match_status"] == "multiple_matches"
        assert data["match_count"] == 2
        assert len(data["patients"]) == 2


def test_search_patient_invalid_dob_format(client: TestClient):
    """Scenario 5: Non-ISO date format must be rejected with 400 Bad Request."""
    response = client.get("/api/patients/search?first_name=Alex&last_name=Smith&dob=15/06/1985")
    assert response.status_code == 400
    data = response.json()
    assert "Invalid date format" in data["message"]


def test_search_patient_future_dob(client: TestClient):
    """Scenario 5: Future date of birth must be rejected with 400 Bad Request."""
    response = client.get("/api/patients/search?first_name=Alex&last_name=Smith&dob=2099-01-01")
    assert response.status_code == 400
    data = response.json()
    assert "must be in the past" in data["message"]


def test_search_patient_missing_required_parameters(client: TestClient):
    """Scenario 6: Missing required first_name, last_name, or dob returns 422."""
    # Missing dob
    res1 = client.get("/api/patients/search?first_name=Alex&last_name=Smith")
    assert res1.status_code == 422

    # Missing first_name
    res2 = client.get("/api/patients/search?last_name=Smith&dob=1985-06-15")
    assert res2.status_code == 422

    # Missing last_name
    res3 = client.get("/api/patients/search?first_name=Alex&dob=1985-06-15")
    assert res3.status_code == 422


def test_search_patient_authentication_failure(client: TestClient):
    """Scenario 7: Upstream authentication failure returns 401."""
    with patch("app.api.patients.ecw_client.search_patient_by_name_dob", new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = EcwAuthError(
            detail="eClinicalWorks authentication failed (401) during patient search.",
            blocker="Invalid or expired access token",
        )

        response = client.get("/api/patients/search?first_name=Alex&last_name=Smith&dob=1985-06-15")

        assert response.status_code == 401
        data = response.json()
        assert data["status"] == "error"
        assert "authentication failed" in data["message"].lower()


def test_search_patient_insufficient_permissions(client: TestClient):
    """Scenario 8: Insufficient permissions returns 403 Forbidden."""
    with patch("app.api.patients.ecw_client.search_patient_by_name_dob", new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = EcwPermissionError(
            detail="eClinicalWorks permission denied (403) for patient search.",
            blocker="Missing system/Patient.read scope",
        )

        response = client.get("/api/patients/search?first_name=Alex&last_name=Smith&dob=1985-06-15")

        assert response.status_code == 403
        data = response.json()
        assert "permission denied" in data["message"].lower()


def test_search_patient_upstream_error(client: TestClient):
    """Scenario 9: Upstream eCW error returns 502 Bad Gateway."""
    with patch("app.api.patients.ecw_client.search_patient_by_name_dob", new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = EcwUpstreamError(
            detail="eClinicalWorks Patient search upstream failure (HTTP 502)."
        )

        response = client.get("/api/patients/search?first_name=Alex&last_name=Smith&dob=1985-06-15")

        assert response.status_code == 502
        data = response.json()
        assert "upstream failure" in data["message"].lower()


# =====================================================================
# 2. API Two: GET /api/patients (List Patients with Pagination)
# =====================================================================

def test_list_patients_pagination_with_next_page(client: TestClient):
    """Scenario 10: Patient list pagination with continuation next_page_token."""
    mock_list_response = PatientListResponse(
        items=[
            PatientMatchSummary(patient_id="101", first_name="John", last_name="Doe", full_name="John Doe"),
            PatientMatchSummary(patient_id="102", first_name="Jane", last_name="Doe", full_name="Jane Doe"),
        ],
        count=2,
        page_size=2,
        next_page_token="https://staging-fhir.ecwcloud.com/fhir/r4/FFBJCD/Patient?_count=2&page=2",
        has_more=True,
    )

    with patch("app.api.patients.ecw_client.list_patients", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = mock_list_response

        # Call with API Key authorization header
        headers = {"X-Api-Key": "demo-clinic-secret-key-12345"}
        response = client.get("/api/patients?page_size=2", headers=headers)

        assert response.status_code == 200
        data = response.json()

        assert data["count"] == 2
        assert len(data["items"]) == 2
        assert data["has_more"] is True
        assert data["next_page_token"] is not None
        assert "page=2" in data["next_page_token"]


def test_list_patients_no_next_page(client: TestClient):
    """Scenario 11: Patient list terminal page where has_more is False and next_page_token is None."""
    mock_list_response = PatientListResponse(
        items=[
            PatientMatchSummary(patient_id="201", first_name="Alice", last_name="Wonder", full_name="Alice Wonder"),
        ],
        count=1,
        page_size=20,
        next_page_token=None,
        has_more=False,
    )

    with patch("app.api.patients.ecw_client.list_patients", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = mock_list_response

        headers = {"X-Api-Key": "demo-clinic-secret-key-12345"}
        response = client.get("/api/patients", headers=headers)

        assert response.status_code == 200
        data = response.json()

        assert data["count"] == 1
        assert data["has_more"] is False
        assert data["next_page_token"] is None


def test_list_patients_unsupported_population_wide_search(client: TestClient):
    """Scenario 12: Practice restriction against unindexed population search returns 400 with explanation."""
    with patch("app.api.patients.ecw_client.list_patients", new_callable=AsyncMock) as mock_list:
        mock_list.side_effect = EcwClientError(
            status_code=400,
            detail=(
                "eClinicalWorks EHR server restricts population-wide patient listing without search criteria. "
                "Practice security policy mandates searching by specific parameters (e.g., given, family, birthdate, identifier) "
                "rather than unrestricted population enumeration."
            ),
            blocker="eCW restricts unfiltered population queries without search parameters",
        )

        headers = {"X-Api-Key": "demo-clinic-secret-key-12345"}
        response = client.get("/api/patients", headers=headers)

        assert response.status_code == 400
        data = response.json()
        assert "restricts population-wide patient listing" in data["message"].lower()
        assert "blocker" in data


def test_list_patients_requires_authentication(client: TestClient):
    """Security verification: Listing patient population without authorization must return 401."""
    # Request without X-Api-Key or Authorization header
    response = client.get("/api/patients")
    assert response.status_code == 401
    assert "unauthorized" in response.text.lower()


# =====================================================================
# 3. Scenario 13: Prevention of Mock-Data Fallback
# =====================================================================

def test_prevention_of_mock_data_fallback_on_fhir_failure(client: TestClient):
    """Scenario 13: When live eCW request fails, service must NEVER return synthetic mock data."""
    with patch("app.api.patients.ecw_client.search_patient_by_name_dob", new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = EcwServiceUnavailableError(
            detail="Connection timed out while searching patient records in eClinicalWorks."
        )

        response = client.get("/api/patients/search?first_name=Eleanor&last_name=Vance&dob=1985-04-12")

        # Must return actual error (503) instead of fake Eleanor Vance mock record
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "error"
        assert "timed out" in data["message"].lower()
        assert "eleanor" not in str(data).lower()

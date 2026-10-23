"""FastAPI integration tests for eClinicalWorks Patient Retrieval & Search Endpoints.

Verifies:
1. GET /api/patients/{patient_id}
   - 200 OK: Minimal authorized demographic fields returned (no clinical data leaked).
   - 401 Unauthorized: When authentication fails.
   - 403 Forbidden: When practice permissions or scopes are insufficient.
   - 404 Not Found: When patient ID does not exist in eCW EHR.
   - 502 Bad Gateway: When eCW returns upstream errors or malformed payloads.
   - 503 Service Unavailable: When eCW times out or connection fails.
2. GET /api/patients
   - 200 OK: Searching by family, given, birthdate, etc.
   - 400 Bad Request: Missing query parameters.
"""
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.patient import (
    PatientAddress,
    PatientDemographicsResponse,
    PatientSearchResponse,
)
from app.services.ecw_client import (
    EcwAuthError,
    EcwPermissionError,
    EcwNotFoundError,
    EcwUpstreamError,
    EcwServiceUnavailableError,
)


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app)


# =====================================================================
# GET /api/patients/{patient_id} Tests
# =====================================================================

def test_get_patient_by_id_200_success(client: TestClient):
    """GET /api/patients/{patient_id} returns 200 with minimal necessary demographics."""
    mock_demographics = PatientDemographicsResponse(
        patient_id="12345",
        first_name="Eleanor",
        last_name="Vance",
        full_name="Eleanor Vance",
        date_of_birth="1985-04-12",
        gender="female",
        phone="561-555-0199",
        email="eleanor.vance@example.com",
        address=PatientAddress(
            line="100 Ocean Blvd",
            city="Boynton Beach",
            state="FL",
            postal_code="33435",
        ),
        active=True,
        preferred_language="English",
    )

    with patch("app.api.patients.ecw_client.get_patient_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_demographics

        response = client.get("/api/patients/12345")

        assert response.status_code == 200
        data = response.json()

        assert data["patient_id"] == "12345"
        assert data["first_name"] == "Eleanor"
        assert data["last_name"] == "Vance"
        assert data["full_name"] == "Eleanor Vance"
        assert data["date_of_birth"] == "1985-04-12"
        assert data["gender"] == "female"
        assert data["phone"] == "561-555-0199"
        assert data["email"] == "eleanor.vance@example.com"
        assert data["address"]["city"] == "Boynton Beach"
        assert data["address"]["state"] == "FL"
        assert data["preferred_language"] == "English"
        assert data["active"] is True

        # Strictly verify no clinical fields are exposed
        forbidden_fields = ["diagnoses", "conditions", "medications", "notes", "observations", "prescriptions"]
        for field in forbidden_fields:
            assert field not in data


def test_get_patient_by_id_401_unauthorized(client: TestClient):
    """GET /api/patients/{patient_id} returns 401 when eCW authentication fails."""
    with patch("app.api.patients.ecw_client.get_patient_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = EcwAuthError(
            detail="Authentication failed with eClinicalWorks OAuth server.",
            blocker="Invalid eCW client assertion or expired credentials",
        )

        response = client.get("/api/patients/12345")

        assert response.status_code == 401
        data = response.json()
        assert data["status"] == "error"
        assert "Authentication failed" in data["message"]
        assert "blocker" in data


def test_get_patient_by_id_403_forbidden(client: TestClient):
    """GET /api/patients/{patient_id} returns 403 when practice tenant denies access."""
    with patch("app.api.patients.ecw_client.get_patient_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = EcwPermissionError(
            detail="Insufficient permissions or practice tenant has not authorized this app.",
            blocker="Missing system/Patient.read scope or pending practice activation",
        )

        response = client.get("/api/patients/12345")

        assert response.status_code == 403
        data = response.json()
        assert data["status"] == "error"
        assert "Insufficient permissions" in data["message"]


def test_get_patient_by_id_404_not_found(client: TestClient):
    """GET /api/patients/{patient_id} returns 404 when patient does not exist in eCW."""
    with patch("app.api.patients.ecw_client.get_patient_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = EcwNotFoundError(detail="Patient record was not found in eClinicalWorks EHR.")

        response = client.get("/api/patients/nonexistent-id")

        assert response.status_code == 404
        data = response.json()
        assert data["status"] == "error"
        assert "not found" in data["message"].lower()


def test_get_patient_by_id_502_bad_gateway(client: TestClient):
    """GET /api/patients/{patient_id} returns 502 on upstream eCW server error."""
    with patch("app.api.patients.ecw_client.get_patient_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = EcwUpstreamError(detail="eClinicalWorks upstream FHIR server error (HTTP 502).")

        response = client.get("/api/patients/12345")

        assert response.status_code == 502
        data = response.json()
        assert data["status"] == "error"
        assert "upstream" in data["message"].lower()


def test_get_patient_by_id_503_service_unavailable(client: TestClient):
    """GET /api/patients/{patient_id} returns 503 on eCW timeout or temporary unavailability."""
    with patch("app.api.patients.ecw_client.get_patient_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = EcwServiceUnavailableError(
            detail="Connection timed out while fetching patient from eClinicalWorks."
        )

        response = client.get("/api/patients/12345")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "error"
        assert "timed out" in data["message"].lower() or "unavailable" in data["message"].lower()


# =====================================================================
# GET /api/patients (Search) Tests
# =====================================================================

def test_search_patients_200_success(client: TestClient):
    """GET /api/patients returns matching patients when valid US Core parameters are supplied."""
    mock_results = PatientSearchResponse(
        total=1,
        patients=[
            PatientDemographicsResponse(
                patient_id="12345",
                first_name="Jane",
                last_name="Smith",
                full_name="Jane Smith",
                date_of_birth="1980-05-15",
                gender="female",
                phone="561-555-0199",
                email="jane.smith@example.com",
                active=True,
            )
        ],
    )

    with patch("app.api.patients.ecw_client.search_patients", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_results

        response = client.get("/api/patients?family=Smith&given=Jane&birthdate=1980-05-15")

        assert response.status_code == 200
        data = response.json()

        assert data["total"] == 1
        assert len(data["patients"]) == 1
        assert data["patients"][0]["patient_id"] == "12345"
        assert data["patients"][0]["full_name"] == "Jane Smith"


def test_search_patients_400_no_parameters(client: TestClient):
    """GET /api/patients without query parameters must return 400 Bad Request."""
    response = client.get("/api/patients")
    assert response.status_code == 400
    data = response.json()
    assert "At least one search parameter" in data["message"]

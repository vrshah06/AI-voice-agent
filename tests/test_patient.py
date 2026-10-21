"""Tests for patient identification endpoint."""
from datetime import date, timedelta
from fastapi.testclient import TestClient


def test_identify_existing_demo_patient(client: TestClient):
    """Verify identifying a pre-seeded synthetic demo patient."""
    payload = {
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
    }
    response = client.post("/api/patient/identify", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "verified_patient"
    assert data["patient_id"] == "PAT-DEMO-001"
    assert data["patient_name"] == "Eleanor Vance"
    assert data["date_of_birth"] == "1985-04-12"
    assert data["identity_verified"] is True
    assert data["is_demo_data"] is True
    assert "DEMO PROTOTYPE ONLY" in data["disclaimer"]
    assert "verified your details" in data["message"]


def test_identify_new_demo_patient(client: TestClient):
    """Verify identifying a new caller returns verified status."""
    payload = {
        "patient_name": "Marcus Aurelius",
        "date_of_birth": "1990-08-15",
    }
    response = client.post("/api/patient/identify", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "verified_patient"
    assert data["patient_id"].startswith("PAT-DEMO-")
    assert data["identity_verified"] is True
    assert data["is_demo_data"] is True
    assert "verified your details" in data["message"]


def test_identify_patient_future_dob(client: TestClient):
    """Verify that a future date of birth is rejected with 422."""
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    payload = {
        "patient_name": "Baby Tomorrow",
        "date_of_birth": tomorrow,
    }
    response = client.post("/api/patient/identify", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["status"] == "validation_error"
    assert "must be in the past" in response.text


def test_identify_patient_empty_name(client: TestClient):
    """Verify that an empty or whitespace-only name is rejected with 422."""
    payload = {
        "patient_name": "   ",
        "date_of_birth": "1992-05-10",
    }
    response = client.post("/api/patient/identify", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["status"] == "validation_error"


def test_identify_patient_missing_fields(client: TestClient):
    """Verify missing required fields return 422."""
    response = client.post("/api/patient/identify", json={"patient_name": "Incomplete Record"})
    assert response.status_code == 422


def test_identify_patient_invalid_date_format(client: TestClient):
    """Verify non-ISO date format is rejected."""
    payload = {
        "patient_name": "John Doe",
        "date_of_birth": "12/04/1985",
    }
    response = client.post("/api/patient/identify", json=payload)
    assert response.status_code == 422

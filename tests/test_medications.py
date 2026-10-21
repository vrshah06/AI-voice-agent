"""Tests for medication refill endpoint."""
from datetime import date, timedelta
from fastapi.testclient import TestClient


def test_medication_refill_success(client: TestClient):
    """Verify successfully submitting a simulated prescription refill request."""
    payload = {
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "medication_name": "Lisinopril 10mg",
        "preferred_pharmacy_name": "Walgreens Pharmacy #5812",
        "pharmacy_location": "100 Main Street, Springfield",
    }
    response = client.post("/api/medications/refill", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "pending_prescriber_review"
    assert data["refill_reference"].startswith("REF-DEMO-")
    assert data["medication_name"] == "Lisinopril 10mg"
    assert data["preferred_pharmacy_name"] == "Walgreens Pharmacy #5812"
    assert data["pharmacy_location"] == "100 Main Street, Springfield"
    # Safety assertions
    assert data["requires_prescriber_approval"] is True
    assert data["is_demo_data"] is True
    assert "DEMO PROTOTYPE ONLY" in data["disclaimer"]
    assert "prescriber must review and approve" in data["clinic_notice"]


def test_medication_refill_missing_pharmacy(client: TestClient):
    """Verify missing preferred_pharmacy_name triggers 422 validation error."""
    payload = {
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "medication_name": "Atorvastatin 20mg",
        "pharmacy_location": "Downtown",
        # missing preferred_pharmacy_name
    }
    response = client.post("/api/medications/refill", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["status"] == "validation_error"


def test_medication_refill_empty_medication_name(client: TestClient):
    """Verify whitespace-only medication name triggers 422."""
    payload = {
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "medication_name": "   ",
        "preferred_pharmacy_name": "CVS",
        "pharmacy_location": "123 Oak St",
    }
    response = client.post("/api/medications/refill", json=payload)
    assert response.status_code == 422


def test_medication_refill_future_dob(client: TestClient):
    """Verify future date of birth is rejected for refills."""
    future_date = (date.today() + timedelta(days=5)).isoformat()
    payload = {
        "patient_name": "Eleanor Vance",
        "date_of_birth": future_date,
        "medication_name": "Metformin 500mg",
        "preferred_pharmacy_name": "CVS",
        "pharmacy_location": "123 Oak St",
    }
    response = client.post("/api/medications/refill", json=payload)
    assert response.status_code == 422

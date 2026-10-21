"""Tests for Retell AI tool adapter and webhook integration."""
from datetime import date, timedelta
from fastapi.testclient import TestClient
from app.core.config import settings


def test_retell_webhook_identify_patient(client: TestClient, auth_headers: dict):
    """Verify Retell default wrapped payload invoking identify_patient."""
    payload = {
        "name": "identify_patient",
        "call": {"call_id": "call_test_123"},
        "args": {
            "patient_name": "Eleanor Vance",
            "date_of_birth": "1985-04-12",
        },
    }
    response = client.post("/api/retell/webhook", json=payload, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "Eleanor Vance" in data["message"]
    assert data["data"]["patient_id"] == "PAT-DEMO-001"
    assert data["data"]["identity_verified"] is True


def test_retell_webhook_check_availability(client: TestClient, auth_headers: dict):
    """Verify Retell checking appointment availability."""
    target_date = (date.today() + timedelta(days=3)).isoformat()
    payload = {
        "name": "check_appointment_availability",
        "args": {
            "patient_name": "Eleanor Vance",
            "date_of_birth": "1985-04-12",
            "doctor_name": "Dr. Chintan Shah",
            "requested_date": target_date,
        },
    }
    response = client.post("/api/retell/webhook", json=payload, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "09:00" in data["data"]["available_slots"]


def test_retell_webhook_book_and_conflict(client: TestClient, auth_headers: dict):
    """Verify Retell booking an appointment and gracefully handling conflict without HTTP crash."""
    target_date = (date.today() + timedelta(days=3)).isoformat()
    payload = {
        "name": "book_appointment",
        "args": {
            "patient_name": "Eleanor Vance",
            "date_of_birth": "1985-04-12",
            "doctor_name": "Dr. Chintan Shah",
            "appointment_date": target_date,
            "appointment_time": "09:00",
        },
    }
    # 1. First booking succeeds
    res1 = client.post("/api/retell/webhook", json=payload, headers=auth_headers)
    assert res1.status_code == 200
    assert res1.json()["status"] == "success"
    assert "BK-DEMO-" in res1.json()["data"]["booking_reference"]

    # 2. Second booking handles conflict gracefully as an error message for the LLM
    res2 = client.post("/api/retell/webhook", json=payload, headers=auth_headers)
    assert res2.status_code == 200  # Return 200 to prevent voice call termination
    data2 = res2.json()
    assert data2["status"] == "error"
    assert "already booked" in data2["message"]


def test_retell_webhook_reschedule(client: TestClient, auth_headers: dict):
    """Verify Retell rescheduling an existing appointment."""
    day1 = (date.today() + timedelta(days=2)).isoformat()
    day2 = (date.today() + timedelta(days=5)).isoformat()

    # Book first
    client.post("/api/retell/webhook", json={
        "name": "book_appointment",
        "args": {
            "patient_name": "Eleanor Vance",
            "date_of_birth": "1985-04-12",
            "doctor_name": "Dr. Chintan Shah",
            "appointment_date": day1,
            "appointment_time": "11:00",
        }
    }, headers=auth_headers)

    # Reschedule
    res = client.post("/api/retell/webhook", json={
        "name": "reschedule_appointment",
        "args": {
            "patient_name": "Eleanor Vance",
            "date_of_birth": "1985-04-12",
            "new_date": day2,
            "new_time": "14:30",
        }
    }, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert res.json()["data"]["new_time"] == "14:30"


def test_retell_webhook_cancel(client: TestClient, auth_headers: dict):
    """Verify Retell cancelling an appointment."""
    day1 = (date.today() + timedelta(days=3)).isoformat()
    client.post("/api/retell/webhook", json={
        "name": "book_appointment",
        "args": {
            "patient_name": "Eleanor Vance",
            "date_of_birth": "1985-04-12",
            "doctor_name": "Dr. Chintan Shah",
            "appointment_date": day1,
            "appointment_time": "09:00",
        }
    }, headers=auth_headers)

    res = client.post("/api/retell/webhook", json={
        "name": "cancel_appointment",
        "args": {
            "patient_name": "Eleanor Vance",
            "date_of_birth": "1985-04-12",
        }
    }, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert res.json()["data"]["status"] == "cancelled"


def test_retell_webhook_knowledge_answer(client: TestClient, auth_headers: dict):
    """Verify Retell querying clinic knowledge."""
    res = client.post("/api/retell/webhook", json={
        "name": "answer_clinic_question",
        "args": {"question": "What are your hours on weekdays?"}
    }, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert "Monday to Friday" in res.json()["message"]


def test_retell_webhook_take_message(client: TestClient, auth_headers: dict):
    """Verify Retell recording a caller message."""
    res = client.post("/api/retell/webhook", json={
        "name": "take_message",
        "args": {
            "caller_name": "Eleanor Vance",
            "callback_number": "555-019-2834",
            "recipient": "Dr. Chintan Shah",
            "message": "Calling for lab test follow up.",
        }
    }, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert "MSG-DEMO-" in res.json()["data"]["message_id"]


def test_retell_named_tool_endpoint_flat_args(client: TestClient, auth_headers: dict):
    """Verify Retell named tool endpoint accepting flat 'args-only' payload."""
    payload = {
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "medication_name": "Amoxicillin 500mg",
        "preferred_pharmacy_name": "CVS Pharmacy",
        "pharmacy_location": "Oak St",
    }
    response = client.post(
        "/api/retell/tools/request_medication_refill",
        json=payload,
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "REF-DEMO-" in data["data"]["refill_reference"]


def test_retell_auth_failure(client: TestClient):
    """Verify unauthorized request without valid API key is rejected with 401."""
    payload = {
        "name": "identify_patient",
        "args": {"patient_name": "Test", "date_of_birth": "1990-01-01"},
    }
    response = client.post(
        "/api/retell/webhook",
        json=payload,
        headers={"X-Api-Key": "invalid-wrong-key"},
    )
    assert response.status_code == 401
    assert "Unauthorized" in response.text

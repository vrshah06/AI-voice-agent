"""Tests for appointment availability, booking, rescheduling, and cancellation endpoints."""
from datetime import date, timedelta
from fastapi.testclient import TestClient


def test_appointment_availability_success(client: TestClient):
    """Verify querying availability for a future date returns sample slots."""
    future_date = (date.today() + timedelta(days=3)).isoformat()
    payload = {
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "doctor_name": "Dr. Chintan Shah",
        "requested_date": future_date,
    }
    response = client.post("/api/appointments/availability", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "available"
    assert data["requested_date"] == future_date
    assert data["doctor_name"] == "Dr. Chintan Shah"
    assert "09:00" in data["available_slots"]
    assert "11:00" in data["available_slots"]
    assert "14:30" in data["available_slots"]
    assert data["is_demo_data"] is True
    assert "DEMO PROTOTYPE ONLY" in data["disclaimer"]


def test_appointment_availability_past_date_rejected(client: TestClient):
    """Verify querying an appointment date in the past returns 422 validation error."""
    past_date = (date.today() - timedelta(days=1)).isoformat()
    payload = {
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "requested_date": past_date,
    }
    response = client.post("/api/appointments/availability", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["status"] == "validation_error"
    assert "cannot be in the past" in response.text


def test_appointment_booking_success(client: TestClient):
    """Verify successfully booking a valid demo slot."""
    target_date = (date.today() + timedelta(days=2)).isoformat()
    payload = {
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "doctor_name": "Dr. Chintan Shah",
        "appointment_date": target_date,
        "appointment_time": "09:00",
    }
    response = client.post("/api/appointments/book", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "confirmed"
    assert data["booking_reference"].startswith("BK-DEMO-")
    assert data["appointment_time"] == "09:00"
    assert data["appointment_date"] == target_date
    assert data["is_demo_data"] is True
    assert "simulated" in data["message"].lower() or "demo" in data["message"].lower()


def test_appointment_booking_unavailable_slot_rejected(client: TestClient):
    """Verify that attempting to book a time slot not in clinic schedule returns 400."""
    target_date = (date.today() + timedelta(days=2)).isoformat()
    payload = {
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "doctor_name": "Dr. Chintan Shah",
        "appointment_date": target_date,
        "appointment_time": "10:15",  # Not in STANDARD_SLOTS (09:00, 11:00, 14:30)
    }
    response = client.post("/api/appointments/book", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data["status"] == "error"
    assert "not a valid clinic scheduling slot" in data["message"]


def test_appointment_duplicate_booking_prevention(client: TestClient):
    """Verify that booking the same slot twice triggers 409 Conflict."""
    target_date = (date.today() + timedelta(days=4)).isoformat()
    booking_payload = {
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "doctor_name": "Dr. Chintan Shah",
        "appointment_date": target_date,
        "appointment_time": "11:00",
    }

    # First booking succeeds
    res1 = client.post("/api/appointments/book", json=booking_payload)
    assert res1.status_code == 200

    # Second booking for the same doctor, date, and time fails with 409 Conflict
    res2 = client.post("/api/appointments/book", json=booking_payload)
    assert res2.status_code == 409
    data = res2.json()
    assert data["status"] == "error"
    assert "already booked" in data["message"]


def test_availability_reflects_booked_slots(client: TestClient):
    """Verify that booking a slot removes it from subsequent availability responses."""
    target_date = (date.today() + timedelta(days=5)).isoformat()

    # Query initial availability
    res_init = client.post("/api/appointments/availability", json={
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "doctor_name": "Dr. Chintan Shah",
        "requested_date": target_date,
    })
    assert "14:30" in res_init.json()["available_slots"]

    # Book 14:30
    client.post("/api/appointments/book", json={
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "doctor_name": "Dr. Chintan Shah",
        "appointment_date": target_date,
        "appointment_time": "14:30",
    })

    # Query again
    res_after = client.post("/api/appointments/availability", json={
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "doctor_name": "Dr. Chintan Shah",
        "requested_date": target_date,
    })
    assert "14:30" not in res_after.json()["available_slots"]
    assert "09:00" in res_after.json()["available_slots"]
    assert "11:00" in res_after.json()["available_slots"]


def test_appointment_reschedule_success(client: TestClient):
    """Verify rescheduling an existing confirmed appointment."""
    initial_date = (date.today() + timedelta(days=2)).isoformat()
    new_date = (date.today() + timedelta(days=6)).isoformat()

    # 1. First book
    book_res = client.post("/api/appointments/book", json={
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "doctor_name": "Dr. Chintan Shah",
        "appointment_date": initial_date,
        "appointment_time": "09:00",
    })
    assert book_res.status_code == 200
    booking_ref = book_res.json()["booking_reference"]

    # 2. Reschedule to new_date at 11:00
    resched_res = client.post("/api/appointments/reschedule", json={
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "appointment_reference": booking_ref,
        "new_date": new_date,
        "new_time": "11:00",
    })
    assert resched_res.status_code == 200
    resched_data = resched_res.json()
    assert resched_data["status"] == "rescheduled"
    assert resched_data["new_date"] == new_date
    assert resched_data["new_time"] == "11:00"
    assert resched_data["old_time"] == "09:00"

    # 3. Old slot on initial_date (09:00) is now freed up!
    avail_res = client.post("/api/appointments/availability", json={
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "doctor_name": "Dr. Chintan Shah",
        "requested_date": initial_date,
    })
    assert "09:00" in avail_res.json()["available_slots"]


def test_appointment_reschedule_not_found(client: TestClient):
    """Verify rescheduling returns 404 when appointment does not exist."""
    new_date = (date.today() + timedelta(days=6)).isoformat()
    res = client.post("/api/appointments/reschedule", json={
        "patient_name": "Nonexistent Patient",
        "date_of_birth": "1985-04-12",
        "appointment_reference": "BK-NONEXISTENT",
        "new_date": new_date,
        "new_time": "11:00",
    })
    assert res.status_code == 404
    assert "No active appointment found" in res.json()["message"]


def test_appointment_cancel_success(client: TestClient):
    """Verify cancelling an existing appointment releases the slot."""
    target_date = (date.today() + timedelta(days=3)).isoformat()

    # 1. Book slot 14:30
    book_res = client.post("/api/appointments/book", json={
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "doctor_name": "Dr. Chintan Shah",
        "appointment_date": target_date,
        "appointment_time": "14:30",
    })
    assert book_res.status_code == 200
    booking_ref = book_res.json()["booking_reference"]

    # 2. Cancel
    cancel_res = client.post("/api/appointments/cancel", json={
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "appointment_reference": booking_ref,
    })
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "cancelled"

    # 3. Slot 14:30 is available again
    avail_res = client.post("/api/appointments/availability", json={
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "doctor_name": "Dr. Chintan Shah",
        "requested_date": target_date,
    })
    assert "14:30" in avail_res.json()["available_slots"]


def test_appointment_cancel_not_found(client: TestClient):
    """Verify cancelling returns 404 if booking does not exist."""
    cancel_res = client.post("/api/appointments/cancel", json={
        "patient_name": "Ghost Caller",
        "date_of_birth": "1990-01-01",
        "appointment_reference": "BK-DEMO-00000000",
    })
    assert cancel_res.status_code == 404
    assert "No active appointment found" in cancel_res.json()["message"]


def test_appointment_booking_past_date_rejected(client: TestClient):
    """Verify booking with a past date returns 422."""
    past_date = (date.today() - timedelta(days=2)).isoformat()
    payload = {
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "doctor_name": "Dr. Chintan Shah",
        "appointment_date": past_date,
        "appointment_time": "09:00",
    }
    response = client.post("/api/appointments/book", json=payload)
    assert response.status_code == 422


def test_appointment_booking_invalid_time_format(client: TestClient):
    """Verify invalid time format string is rejected with 422."""
    future_date = (date.today() + timedelta(days=1)).isoformat()
    payload = {
        "patient_name": "Eleanor Vance",
        "date_of_birth": "1985-04-12",
        "doctor_name": "Dr. Chintan Shah",
        "appointment_date": future_date,
        "appointment_time": "9:00 AM",  # Invalid; must be HH:MM
    }
    response = client.post("/api/appointments/book", json=payload)
    assert response.status_code == 422
    assert "Invalid time format" in response.text

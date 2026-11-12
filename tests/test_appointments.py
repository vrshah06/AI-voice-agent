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


def test_test_ecw_scheduling_endpoint_routes(client: TestClient):
    """Verify both /api/appointments/ecw/test-scheduling and alias /api/ecw/scheduling/test are accessible."""
    from unittest.mock import AsyncMock, patch

    mock_report = {
        "status": "scope_restricted",
        "authenticated": True,
        "provider_app": {
            "client_id_preview": "test-c...xyz",
            "key_id": "ecw-key-1",
            "configured_scopes": "system/Patient.read",
            "has_patient_scope": True,
        },
        "scheduling_probe": {
            "resource": "Slot",
            "http_status": 403,
            "outcome": "forbidden_scope_or_practice_restriction",
        },
        "scope_analysis": {
            "configured_scopes": "system/Patient.read",
            "approved_scope": "system/Patient.read",
        },
    }

    with patch("app.services.ecw_client.ecw_client.test_scheduling_access", new_callable=AsyncMock) as mock_probe:
        mock_probe.return_value = mock_report

        # Test primary route
        resp1 = client.get("/api/appointments/ecw/test-scheduling?resource=Slot")
        assert resp1.status_code == 200
        assert resp1.json()["status"] == "scope_restricted"
        assert resp1.json()["scheduling_probe"]["resource"] == "Slot"

        # Test alias route
        resp2 = client.get("/api/ecw/scheduling/test?resource=Slot")
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "scope_restricted"


def test_get_provider_token_status_endpoint(client: TestClient):
    """Verify GET /api/ecw/provider/token-status returns safe token cache metadata."""
    from unittest.mock import AsyncMock, patch

    mock_status = {
        "is_cached": True,
        "is_valid": True,
        "expires_in_seconds": 250,
        "token_type": "Bearer",
        "configured_scopes": "system/Patient.read",
        "client_id_preview": "b_Zpwo...5xVs",
        "key_id": "ecw-key-1",
        "token_url": "https://oauthserver.eclinicalworks.com/oauth/oauth2/token",
    }

    with patch("app.services.ecw_client.ecw_client.get_provider_token_cache_status", new_callable=AsyncMock) as mock_stat:
        mock_stat.return_value = mock_status
        resp = client.get("/api/ecw/provider/token-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_cached"] is True
        assert data["token_type"] == "Bearer"
        assert "access_token" not in data


# =====================================================================
# eCW Appointment Retrieval (Encounter.read) Tests
# =====================================================================

def test_search_appointments_by_name_success(client: TestClient):
    """Scenario 1: Search using first name and last name."""
    from unittest.mock import AsyncMock, patch
    from app.models.patient import PatientSearchMatchResponse, PatientMatchSummary
    from app.models.appointments import AppointmentDetail

    mock_patient_res = PatientSearchMatchResponse(
        match_status="single_match",
        match_count=1,
        patients=[
            PatientMatchSummary(
                patient_id="12345",
                first_name="John",
                last_name="Smith",
                full_name="John Smith",
                date_of_birth="1985-05-12",
                active=True,
            )
        ],
        identity_verification_required=True,
        notice="Single patient match confirmed.",
    )

    mock_appointments = [
        AppointmentDetail(
            encounter_id="enc-001",
            appointment_date="2026-11-20",
            appointment_time="10:30 AM",
            end_time="11:00 AM",
            status="planned",
            provider="Dr. Example",
            location="MD Primary Care",
            visit_type="Follow-up",
        ),
        AppointmentDetail(
            encounter_id="enc-002",
            appointment_date="2026-12-05",
            appointment_time="02:00 PM",
            end_time=None,
            status="planned",
            provider="Dr. Example",
            location="MD Primary Care",
            visit_type="Consultation",
        ),
    ]

    with patch("app.services.ecw_client.ecw_client.search_patient_by_name_dob", new_callable=AsyncMock) as mock_search, \
         patch("app.services.ecw_client.ecw_client.search_patient_encounters", new_callable=AsyncMock) as mock_encounters:
        mock_search.return_value = mock_patient_res
        mock_encounters.return_value = mock_appointments

        resp = client.get("/api/appointments/search?first_name=John&last_name=Smith")
        assert resp.status_code == 200
        data = resp.json()

        assert data["success"] is True
        assert data["patient"]["patient_id"] == "12345"
        assert data["patient"]["first_name"] == "John"
        assert data["patient"]["last_name"] == "Smith"
        assert data["total_appointments"] == 2
        assert len(data["appointments"]) == 2
        assert data["appointments"][0]["encounter_id"] == "enc-001"
        assert data["appointments"][0]["appointment_date"] == "2026-11-20"
        assert data["appointments"][0]["appointment_time"] == "10:30 AM"
        assert data["appointments"][0]["end_time"] == "11:00 AM"
        assert data["appointments"][0]["status"] == "planned"
        assert data["appointments"][0]["provider"] == "Dr. Example"
        assert data["appointments"][0]["location"] == "MD Primary Care"
        assert data["appointments"][0]["visit_type"] == "Follow-up"


def test_search_appointments_by_name_and_dob_success(client: TestClient):
    """Scenario 2: Search using first name, last name, and DOB."""
    from unittest.mock import AsyncMock, patch
    from app.models.patient import PatientSearchMatchResponse, PatientMatchSummary
    from app.models.appointments import AppointmentDetail

    mock_patient_res = PatientSearchMatchResponse(
        match_status="single_match",
        match_count=1,
        patients=[
            PatientMatchSummary(
                patient_id="12345",
                first_name="John",
                last_name="Smith",
                full_name="John Smith",
                date_of_birth="1985-05-12",
                active=True,
            )
        ],
        identity_verification_required=True,
        notice="Single patient match confirmed.",
    )

    mock_appointments = [
        AppointmentDetail(
            encounter_id="enc-001",
            appointment_date="2026-11-20",
            appointment_time="10:30 AM",
            end_time="11:00 AM",
            status="planned",
            provider="Dr. Example",
            location="MD Primary Care",
            visit_type="Follow-up",
        )
    ]

    with patch("app.services.ecw_client.ecw_client.search_patient_by_name_dob", new_callable=AsyncMock) as mock_search, \
         patch("app.services.ecw_client.ecw_client.search_patient_encounters", new_callable=AsyncMock) as mock_encounters:
        mock_search.return_value = mock_patient_res
        mock_encounters.return_value = mock_appointments

        resp = client.get("/api/appointments/search?first_name=John&last_name=Smith&dob=1985-05-12")
        assert resp.status_code == 200
        data = resp.json()

        assert data["success"] is True
        assert data["patient"]["patient_id"] == "12345"
        assert data["total_appointments"] == 1
        mock_search.assert_awaited_once_with(first_name="John", last_name="Smith", dob="1985-05-12")


def test_search_appointments_by_name_and_appointment_date(client: TestClient):
    """Scenario 3: Search using patient name and appointment date."""
    from unittest.mock import AsyncMock, patch
    from app.models.patient import PatientSearchMatchResponse, PatientMatchSummary
    from app.models.appointments import AppointmentDetail

    mock_patient_res = PatientSearchMatchResponse(
        match_status="single_match",
        match_count=1,
        patients=[
            PatientMatchSummary(
                patient_id="12345",
                first_name="John",
                last_name="Smith",
                full_name="John Smith",
                date_of_birth="1985-05-12",
                active=True,
            )
        ],
        identity_verification_required=True,
        notice="Single patient match confirmed.",
    )

    mock_appointments = [
        AppointmentDetail(
            encounter_id="enc-001",
            appointment_date="2026-11-20",
            appointment_time="10:30 AM",
            end_time="11:00 AM",
            status="planned",
            provider="Dr. Example",
            location="MD Primary Care",
            visit_type="Follow-up",
        )
    ]

    with patch("app.services.ecw_client.ecw_client.search_patient_by_name_dob", new_callable=AsyncMock) as mock_search, \
         patch("app.services.ecw_client.ecw_client.search_patient_encounters", new_callable=AsyncMock) as mock_encounters:
        mock_search.return_value = mock_patient_res
        mock_encounters.return_value = mock_appointments

        resp = client.get("/api/appointments/search?first_name=John&last_name=Smith&appointment_date=2026-11-20")
        assert resp.status_code == 200
        data = resp.json()

        assert data["success"] is True
        assert data["total_appointments"] == 1
        mock_encounters.assert_awaited_once_with(
            patient_id="12345",
            appointment_date="2026-11-20",
            appointment_time=None,
        )


def test_search_appointments_by_name_and_appointment_time(client: TestClient):
    """Scenario 4: Search using patient name and appointment time."""
    from unittest.mock import AsyncMock, patch
    from app.models.patient import PatientSearchMatchResponse, PatientMatchSummary
    from app.models.appointments import AppointmentDetail

    mock_patient_res = PatientSearchMatchResponse(
        match_status="single_match",
        match_count=1,
        patients=[
            PatientMatchSummary(
                patient_id="12345",
                first_name="John",
                last_name="Smith",
                full_name="John Smith",
                date_of_birth="1985-05-12",
                active=True,
            )
        ],
        identity_verification_required=True,
        notice="Single patient match confirmed.",
    )

    mock_appointments = [
        AppointmentDetail(
            encounter_id="enc-001",
            appointment_date="2026-11-20",
            appointment_time="10:30 AM",
            end_time="11:00 AM",
            status="planned",
            provider="Dr. Example",
            location="MD Primary Care",
            visit_type="Follow-up",
        )
    ]

    with patch("app.services.ecw_client.ecw_client.search_patient_by_name_dob", new_callable=AsyncMock) as mock_search, \
         patch("app.services.ecw_client.ecw_client.search_patient_encounters", new_callable=AsyncMock) as mock_encounters:
        mock_search.return_value = mock_patient_res
        mock_encounters.return_value = mock_appointments

        resp = client.get("/api/appointments/search?first_name=John&last_name=Smith&appointment_time=10:30%20AM")
        assert resp.status_code == 200
        data = resp.json()

        assert data["success"] is True
        assert data["total_appointments"] == 1
        mock_encounters.assert_awaited_once_with(
            patient_id="12345",
            appointment_date=None,
            appointment_time="10:30 AM",
        )


def test_search_appointments_all_parameters(client: TestClient):
    """Scenario 5: Search using all parameters (name, dob, appointment_date, appointment_time)."""
    from unittest.mock import AsyncMock, patch
    from app.models.patient import PatientSearchMatchResponse, PatientMatchSummary
    from app.models.appointments import AppointmentDetail

    mock_patient_res = PatientSearchMatchResponse(
        match_status="single_match",
        match_count=1,
        patients=[
            PatientMatchSummary(
                patient_id="12345",
                first_name="John",
                last_name="Smith",
                full_name="John Smith",
                date_of_birth="1985-05-12",
                active=True,
            )
        ],
        identity_verification_required=True,
        notice="Single patient match confirmed.",
    )

    mock_appointments = [
        AppointmentDetail(
            encounter_id="enc-001",
            appointment_date="2026-11-20",
            appointment_time="10:30 AM",
            end_time="11:00 AM",
            status="planned",
            provider="Dr. Example",
            location="MD Primary Care",
            visit_type="Follow-up",
        )
    ]

    with patch("app.services.ecw_client.ecw_client.search_patient_by_name_dob", new_callable=AsyncMock) as mock_search, \
         patch("app.services.ecw_client.ecw_client.search_patient_encounters", new_callable=AsyncMock) as mock_encounters:
        mock_search.return_value = mock_patient_res
        mock_encounters.return_value = mock_appointments

        resp = client.get(
            "/api/appointments/search?first_name=John&last_name=Smith&dob=1985-05-12&appointment_date=2026-11-20&appointment_time=10:30%20AM"
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["success"] is True
        assert data["total_appointments"] == 1
        mock_search.assert_awaited_once_with(first_name="John", last_name="Smith", dob="1985-05-12")
        mock_encounters.assert_awaited_once_with(
            patient_id="12345",
            appointment_date="2026-11-20",
            appointment_time="10:30 AM",
        )


def test_search_appointments_patient_not_found(client: TestClient):
    """Scenario 6: Patient not found."""
    from unittest.mock import AsyncMock, patch
    from app.models.patient import PatientSearchMatchResponse

    mock_not_found = PatientSearchMatchResponse(
        match_status="no_match",
        match_count=0,
        patients=[],
        identity_verification_required=True,
        notice="No matching patient records found.",
    )

    with patch("app.services.ecw_client.ecw_client.search_patient_by_name_dob", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_not_found

        resp = client.get("/api/appointments/search?first_name=Unknown&last_name=Person")
        assert resp.status_code == 200
        data = resp.json()

        assert data["success"] is False
        assert "not found" in data["message"].lower()
        assert data["patient"] is None
        assert data["total_appointments"] == 0
        assert data["appointments"] == []


def test_search_appointments_multiple_patients_ambiguity(client: TestClient):
    """Scenario 7: Multiple patients with the same name (ambiguity response)."""
    from unittest.mock import AsyncMock, patch
    from app.models.patient import PatientSearchMatchResponse, PatientMatchSummary

    mock_multiple = PatientSearchMatchResponse(
        match_status="multiple_matches",
        match_count=2,
        patients=[
            PatientMatchSummary(
                patient_id="1001",
                first_name="John",
                last_name="Smith",
                full_name="John Smith",
                date_of_birth="1980-01-15",
                active=True,
            ),
            PatientMatchSummary(
                patient_id="1002",
                first_name="John",
                last_name="Smith",
                full_name="John Smith",
                date_of_birth="1992-09-20",
                active=True,
            ),
        ],
        identity_verification_required=True,
        notice="Multiple matching patient records found.",
    )

    with patch("app.services.ecw_client.ecw_client.search_patient_by_name_dob", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_multiple

        resp = client.get("/api/appointments/search?first_name=John&last_name=Smith")
        assert resp.status_code == 200
        data = resp.json()

        assert data["success"] is False
        assert "multiple patients" in data["message"].lower()
        assert data["patient"] is None
        assert data["total_appointments"] == 0
        assert data["appointments"] == []
        assert "candidates" in data
        assert len(data["candidates"]) == 2
        assert data["candidates"][0]["patient_id"] == "1001"
        assert data["candidates"][1]["patient_id"] == "1002"


def test_search_appointments_patient_found_no_appointments(client: TestClient):
    """Scenario 8: Patient found but no appointments."""
    from unittest.mock import AsyncMock, patch
    from app.models.patient import PatientSearchMatchResponse, PatientMatchSummary

    mock_patient_res = PatientSearchMatchResponse(
        match_status="single_match",
        match_count=1,
        patients=[
            PatientMatchSummary(
                patient_id="12345",
                first_name="John",
                last_name="Smith",
                full_name="John Smith",
                date_of_birth="1985-05-12",
                active=True,
            )
        ],
        identity_verification_required=True,
        notice="Single patient match confirmed.",
    )

    with patch("app.services.ecw_client.ecw_client.search_patient_by_name_dob", new_callable=AsyncMock) as mock_search, \
         patch("app.services.ecw_client.ecw_client.search_patient_encounters", new_callable=AsyncMock) as mock_encounters:
        mock_search.return_value = mock_patient_res
        mock_encounters.return_value = []

        resp = client.get("/api/appointments/search?first_name=John&last_name=Smith")
        assert resp.status_code == 200
        data = resp.json()

        assert data["success"] is True
        assert data["patient"]["patient_id"] == "12345"
        assert data["total_appointments"] == 0
        assert data["appointments"] == []
        assert "no appointments found" in data["message"].lower()


def test_search_appointments_permission_error_403(client: TestClient):
    """Scenario 9: Encounter.read permission not approved (403 response)."""
    from unittest.mock import AsyncMock, patch
    from app.models.patient import PatientSearchMatchResponse, PatientMatchSummary
    from app.services.ecw_client import EcwPermissionError

    mock_patient_res = PatientSearchMatchResponse(
        match_status="single_match",
        match_count=1,
        patients=[
            PatientMatchSummary(
                patient_id="12345",
                first_name="John",
                last_name="Smith",
                full_name="John Smith",
                date_of_birth="1985-05-12",
                active=True,
            )
        ],
        identity_verification_required=True,
        notice="Single patient match confirmed.",
    )

    with patch("app.services.ecw_client.ecw_client.search_patient_by_name_dob", new_callable=AsyncMock) as mock_search, \
         patch("app.services.ecw_client.ecw_client.search_patient_encounters", new_callable=AsyncMock) as mock_encounters:
        mock_search.return_value = mock_patient_res
        mock_encounters.side_effect = EcwPermissionError(
            detail=(
                "eClinicalWorks denied access (403 Forbidden) to Encounter resource. "
                "Ensure your Provider App has been granted 'Encounter.read' or 'system/Encounter.read' scope."
            ),
            blocker="Missing Encounter.read scope or practice authorization",
        )

        resp = client.get("/api/appointments/search?first_name=John&last_name=Smith")
        assert resp.status_code == 403
        data = resp.json()
        assert data["status"] == "error"
        assert "Encounter.read" in data["message"]
        # Verify it does NOT contain synthetic demo disclaimer
        assert "is_demo_data" not in data or data.get("is_demo_data") is False or "disclaimer" not in data


def test_search_appointments_invalid_dob_format(client: TestClient):
    """Verify malformed DOB format returns 400 Bad Request."""
    resp = client.get("/api/appointments/search?first_name=John&last_name=Smith&dob=05-12-1985")
    assert resp.status_code == 400
    assert "Invalid date format for 'dob'" in resp.json()["message"]


def test_search_appointments_invalid_appointment_date_format(client: TestClient):
    """Verify malformed appointment_date format returns 400 Bad Request."""
    resp = client.get("/api/appointments/search?first_name=John&last_name=Smith&appointment_date=2026/11/20")
    assert resp.status_code == 400
    assert "Invalid date format for 'appointment_date'" in resp.json()["message"]


def test_search_appointments_invalid_appointment_time_format(client: TestClient):
    """Verify malformed appointment_time format returns 400 Bad Request."""
    resp = client.get("/api/appointments/search?first_name=John&last_name=Smith&appointment_time=25:99")
    assert resp.status_code == 400
    assert "Invalid time format for 'appointment_time'" in resp.json()["message"]



"""Appointment API routes for availability querying, booking, rescheduling, cancellation, and retrieval."""
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from app.models.appointments import (
    AppointmentAvailabilityRequest,
    AppointmentAvailabilityResponse,
    AppointmentBookRequest,
    AppointmentBookResponse,
    AppointmentCancelRequest,
    AppointmentCancelResponse,
    AppointmentDetail,
    AppointmentRescheduleRequest,
    AppointmentRescheduleResponse,
    AppointmentSearchResponse,
    PatientBasicInfo,
    PatientCandidate,
)
from app.services.appointment_service import appointment_service
from app.services.ecw_client import ecw_client, normalize_time_str

router = APIRouter(prefix="/api/appointments", tags=["Appointments"])


@router.post(
    "/availability",
    response_model=AppointmentAvailabilityResponse,
    status_code=status.HTTP_200_OK,
    summary="Check Appointment Availability",
    description=(
        "Query demo appointment slots for a requested doctor and date. "
        "Rejects past dates and filters out any already booked slots."
    ),
)
async def check_availability(payload: AppointmentAvailabilityRequest) -> AppointmentAvailabilityResponse:
    """Retrieve sample available appointment slots."""
    return appointment_service.get_availability(payload)


@router.post(
    "/book",
    response_model=AppointmentBookResponse,
    status_code=status.HTTP_200_OK,
    summary="Book Simulated Appointment",
    description=(
        "Reserve a slot in the in-memory schedule. Validates that the requested slot exists "
        "and prevents duplicate bookings. Returns a simulated confirmation code."
    ),
)
async def book_appointment(payload: AppointmentBookRequest) -> AppointmentBookResponse:
    """Book an appointment slot in the demo system."""
    return appointment_service.book_appointment(payload)


@router.post(
    "/reschedule",
    response_model=AppointmentRescheduleResponse,
    status_code=status.HTTP_200_OK,
    summary="Reschedule Appointment",
    description=(
        "Move an existing confirmed appointment to a new date and time. "
        "Releases the previous slot and reserves the new slot."
    ),
)
async def reschedule_appointment(payload: AppointmentRescheduleRequest) -> AppointmentRescheduleResponse:
    """Reschedule an existing appointment."""
    return appointment_service.reschedule_appointment(payload)


@router.post(
    "/cancel",
    response_model=AppointmentCancelResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel Appointment",
    description="Cancel a scheduled appointment and release the time slot back into clinic availability.",
)
async def cancel_appointment(payload: AppointmentCancelRequest) -> AppointmentCancelResponse:
    """Cancel an existing appointment."""
    return appointment_service.cancel_appointment(payload)


# =====================================================================
# Real eCW Encounter / Appointment Retrieval API
# =====================================================================

async def execute_appointment_search(
    first_name: str,
    last_name: str,
    dob: Optional[str] = None,
    appointment_date: Optional[str] = None,
    appointment_time: Optional[str] = None,
) -> AppointmentSearchResponse:
    """Core logic to validate inputs, find the patient in eCW, and retrieve filtered Encounter records."""
    clean_first = first_name.strip() if first_name else ""
    clean_last = last_name.strip() if last_name else ""
    clean_dob = dob.strip() if dob else None
    clean_date = appointment_date.strip() if appointment_date else None
    clean_time = appointment_time.strip() if appointment_time else None

    if not clean_first:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query parameter 'first_name' is required and cannot be blank.",
        )
    if not clean_last:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query parameter 'last_name' is required and cannot be blank.",
        )

    # 1. Validate DOB format if provided
    if clean_dob:
        try:
            parsed_dob = datetime.strptime(clean_dob, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid date format for 'dob': '{clean_dob}'. Expected format is YYYY-MM-DD.",
            )
        today = date.today()
        if parsed_dob >= today:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Date of birth ({clean_dob}) must be in the past.",
            )

    # 2. Validate appointment_date format if provided
    if clean_date:
        try:
            datetime.strptime(clean_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid date format for 'appointment_date': '{clean_date}'. Expected format is YYYY-MM-DD.",
            )

    # 3. Validate appointment_time format if provided
    if clean_time:
        norm = normalize_time_str(clean_time)
        if norm is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid time format for 'appointment_time': '{clean_time}'. "
                    "Expected 12-hour (e.g. '10:30 AM') or 24-hour (e.g. '14:30') format."
                ),
            )

    # Step 1: Find the patient using existing patient search integration
    patient_res = await ecw_client.search_patient_by_name_dob(
        first_name=clean_first,
        last_name=clean_last,
        dob=clean_dob,
    )

    # Step 2: Handle patient matching outcomes
    if patient_res.match_status == "no_match" or patient_res.match_count == 0:
        return AppointmentSearchResponse(
            success=False,
            message=(
                f"Patient '{clean_first} {clean_last}'"
                + (f" with DOB '{clean_dob}'" if clean_dob else "")
                + " was not found in the clinic records."
            ),
            patient=None,
            total_appointments=0,
            appointments=[],
        )

    # If multiple candidates remain (patient ambiguity response with minimal identifying info)
    if patient_res.match_status == "multiple_matches" or patient_res.match_count > 1:
        candidates = [
            PatientCandidate(
                patient_id=p.patient_id,
                first_name=p.first_name,
                last_name=p.last_name,
                date_of_birth=p.date_of_birth,
            )
            for p in patient_res.patients
        ]
        return AppointmentSearchResponse(
            success=False,
            message=(
                f"Multiple patients ({patient_res.match_count}) found matching '{clean_first} {clean_last}'. "
                "Please provide date of birth ('dob' formatted as YYYY-MM-DD) to distinguish patients with similar names."
            ),
            patient=None,
            total_appointments=0,
            appointments=[],
            candidates=candidates,
        )

    # Single unique patient matched
    matched_patient = patient_res.patients[0]
    matched_id = matched_patient.patient_id
    patient_info = PatientBasicInfo(
        patient_id=matched_id,
        first_name=matched_patient.first_name or clean_first,
        last_name=matched_patient.last_name or clean_last,
    )

    # Step 3 & Step 4: Retrieve and filter Encounter records from eCW FHIR
    appointments = await ecw_client.search_patient_encounters(
        patient_id=matched_id,
        appointment_date=clean_date,
        appointment_time=clean_time,
    )

    message = None
    if not appointments:
        filter_parts = []
        if clean_date:
            filter_parts.append(f"date {clean_date}")
        if clean_time:
            filter_parts.append(f"time {clean_time}")
        filter_str = f" for {' and '.join(filter_parts)}" if filter_parts else ""
        message = f"No appointments found for patient '{clean_first} {clean_last}'{filter_str}."

    return AppointmentSearchResponse(
        success=True,
        patient=patient_info,
        total_appointments=len(appointments),
        appointments=appointments,
        message=message,
    )


@router.get(
    "/search",
    response_model=AppointmentSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search Patient Appointments via eCW Encounter",
    description=(
        "Search a patient's existing appointment and encounter details from eClinicalWorks EHR using "
        "the existing `Patient.read` and `Encounter.read` FHIR scopes.\n\n"
        "### Workflow:\n"
        "1. **Patient Identification**: Searches for the patient in eCW using First Name, Last Name, "
        "and optional Date of Birth (`dob`).\n"
        "2. **Disambiguation & Matching**:\n"
        "   - If no patient matches: Returns a clean not-found response (`success: false`).\n"
        "   - If multiple patients match: Returns patient ambiguity response (`success: false`) with minimal candidate summaries.\n"
        "   - If uniquely matched: Uses the patient's actual eCW Patient ID to query the Encounter API.\n"
        "3. **Encounter Retrieval**: Queries eCW FHIR `GET /Encounter?patient={patient_id}` using the authorized Provider App token.\n"
        "4. **Filtering**: Optionally filters appointments by `appointment_date` (YYYY-MM-DD) and/or `appointment_time` (e.g. 10:30 AM).\n\n"
        "**Clinical Safety Notice**: A name-only match confirms record existence only for initial development testing. "
        "Do not consider a name-only match sufficient identity verification for production disclosure of protected health information (PHI)."
    ),
    responses={
        200: {
            "description": "Appointment search completed successfully, or returned patient resolution guidance.",
            "model": AppointmentSearchResponse,
        },
        400: {"description": "Invalid query parameters (e.g. malformed date or time format)."},
        401: {"description": "eClinicalWorks authentication failed or access token rejected."},
        403: {"description": "Insufficient permissions: Encounter.read scope or practice authorization missing."},
        404: {"description": "Requested resource not found."},
        429: {"description": "eClinicalWorks FHIR API rate limit reached."},
        502: {"description": "eClinicalWorks upstream FHIR server failure or malformed payload."},
        503: {"description": "eClinicalWorks service temporarily unavailable."},
    },
)
async def search_patient_appointments(
    first_name: str = Query(
        ...,
        min_length=1,
        description="Patient's legal first / given name",
        examples=["John"],
    ),
    last_name: str = Query(
        ...,
        min_length=1,
        description="Patient's legal last / family name",
        examples=["Smith"],
    ),
    dob: Optional[str] = Query(
        default=None,
        description="Patient date of birth (YYYY-MM-DD) to distinguish patients with similar names",
        examples=["1985-05-12"],
    ),
    appointment_date: Optional[str] = Query(
        default=None,
        description="Filter appointments by date (YYYY-MM-DD)",
        examples=["2026-11-20"],
    ),
    appointment_time: Optional[str] = Query(
        default=None,
        description="Filter appointments by time (e.g. '10:30 AM' or '14:30')",
        examples=["10:30 AM"],
    ),
) -> AppointmentSearchResponse:
    """Retrieve existing appointment/encounter details for a patient from eCW EHR."""
    return await execute_appointment_search(
        first_name=first_name,
        last_name=last_name,
        dob=dob,
        appointment_date=appointment_date,
        appointment_time=appointment_time,
    )



@router.get(
    "/ecw/test-scheduling",
    status_code=status.HTTP_200_OK,
    summary="Test eCW Provider App Scheduling API Access",
    description=(
        "Reuses existing Provider App Backend Services authentication (RFC 7523 private-key JWT) "
        "to acquire/verify access token and test connectivity to eCW FHIR Scheduling resources (Slot, Appointment, Schedule).\n\n"
        "Performs scope diagnosis and tests official eCW FHIR scheduling endpoint without exposing tokens or credentials."
    ),
    tags=["Appointments", "eCW Provider Scheduling"],
)
async def test_ecw_scheduling(
    resource: str = Query("Slot", description="FHIR Scheduling resource: Slot, Appointment, or Schedule"),
    count: int = Query(5, ge=1, le=50, description="Max records to probe in FHIR bundle"),
) -> Dict[str, Any]:
    """Test eCW FHIR Scheduling resource access using the Provider App access token."""
    return await ecw_client.test_scheduling_access(resource=resource, query_params={"_count": str(count)})


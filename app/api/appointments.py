"""Appointment API routes for availability querying, booking, rescheduling, and cancellation."""
from typing import Any, Dict, Optional
from fastapi import APIRouter, Query, status
from app.models.appointments import (
    AppointmentAvailabilityRequest,
    AppointmentAvailabilityResponse,
    AppointmentBookRequest,
    AppointmentBookResponse,
    AppointmentCancelRequest,
    AppointmentCancelResponse,
    AppointmentRescheduleRequest,
    AppointmentRescheduleResponse,
)
from app.services.appointment_service import appointment_service
from app.services.ecw_client import ecw_client

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


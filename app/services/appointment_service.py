"""In-memory service managing demo appointment availability, bookings, rescheduling, and cancellation."""
import random
import string
from datetime import date
from typing import Dict, List, Optional, Set
from fastapi import HTTPException, status
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


class AppointmentService:
    """Manages appointment scheduling operations with in-memory persistence and conflict prevention."""

    # Standard clinic demo slot templates
    STANDARD_SLOTS: List[str] = ["09:00", "11:00", "14:30"]

    def __init__(self) -> None:
        # Key: (doctor_name_lower, date_iso) -> Set of booked times (e.g. {"09:00"})
        self._booked_slots: Dict[str, Set[str]] = {}
        # List of confirmed simulated booking records: Dict[str, Any]
        self._bookings: List[Dict[str, str]] = []

    def _get_schedule_key(self, doctor_name: str, apt_date: date) -> str:
        return f"{doctor_name.strip().lower()}_{apt_date.isoformat()}"

    def get_availability(self, request: AppointmentAvailabilityRequest) -> AppointmentAvailabilityResponse:
        """Fetch available slots for a given doctor and future date."""
        doctor = request.doctor_name or "Dr. Chintan Shah"
        sched_key = self._get_schedule_key(doctor, request.requested_date)
        already_booked = self._booked_slots.get(sched_key, set())

        # Filter out booked slots
        available = [slot for slot in self.STANDARD_SLOTS if slot not in already_booked]

        date_formatted = request.requested_date.strftime("%A, %B %d, %Y")
        if available:
            slot_str = ", ".join(available)
            message = (
                f"For {doctor} on {date_formatted}, available demo times are {slot_str}. "
                f"Which of these times works best for you?"
            )
        else:
            message = (
                f"All demo appointment slots for {doctor} on {date_formatted} are currently booked. "
                f"Would you like to check an alternative date?"
            )

        return AppointmentAvailabilityResponse(
            status="available" if available else "fully_booked",
            patient_name=request.patient_name,
            doctor_name=doctor,
            requested_date=request.requested_date.isoformat(),
            available_slots=available,
            message=message,
        )

    def book_appointment(self, request: AppointmentBookRequest) -> AppointmentBookResponse:
        """Book a simulated appointment slot, validating existence and preventing duplicate bookings."""
        doctor = request.doctor_name or "Dr. Chintan Shah"
        req_date = request.appointment_date
        req_time = request.appointment_time
        sched_key = self._get_schedule_key(doctor, req_date)

        # 1. Verify that the requested slot is in clinic's standard schedule
        if req_time not in self.STANDARD_SLOTS:
            valid_slots = ", ".join(self.STANDARD_SLOTS)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Requested slot '{req_time}' is not a valid clinic scheduling slot. "
                    f"Available clinic slot times are: {valid_slots}."
                ),
            )

        # 2. Check if the slot is already booked (prevent duplicate bookings)
        booked_times = self._booked_slots.setdefault(sched_key, set())
        if req_time in booked_times:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Conflict: Slot {req_time} on {req_date.isoformat()} with {doctor} is already booked. "
                    f"Please select another available slot."
                ),
            )

        # 3. Reserve slot in-memory
        booked_times.add(req_time)

        # 4. Generate unique simulated booking reference
        random_suffix = "".join(random.choices(string.digits, k=4))
        date_code = req_date.strftime("%Y%m%d")
        time_code = req_time.replace(":", "")
        booking_ref = f"BK-DEMO-{date_code}-{time_code}-{random_suffix}"

        booking_record = {
            "booking_reference": booking_ref,
            "patient_name": request.patient_name,
            "date_of_birth": request.date_of_birth.isoformat(),
            "doctor_name": doctor,
            "appointment_date": req_date.isoformat(),
            "appointment_time": req_time,
            "status": "confirmed",
        }
        self._bookings.append(booking_record)

        date_human = req_date.strftime("%A, %B %d, %Y")
        message = (
            f"Your simulated appointment with {doctor} is booked for {date_human} at {req_time}. "
            f"Your demo booking reference is {booking_ref}. Please note this is a simulation and "
            f"no real appointment has been placed on the clinic calendar."
        )

        return AppointmentBookResponse(
            status="confirmed",
            booking_reference=booking_ref,
            patient_name=request.patient_name,
            doctor_name=doctor,
            appointment_date=req_date.isoformat(),
            appointment_time=req_time,
            message=message,
        )

    def _find_booking(
        self,
        patient_name: str,
        booking_ref: Optional[str] = None,
        target_date: Optional[date] = None,
    ) -> Optional[Dict[str, str]]:
        """Helper to locate an active booking record."""
        p_name_norm = patient_name.strip().lower()
        for b in self._bookings:
            if b.get("status") != "confirmed":
                continue
            if b.get("patient_name", "").strip().lower() != p_name_norm:
                continue

            # Match by reference if provided
            if booking_ref and b.get("booking_reference") == booking_ref.strip():
                return b

            # Match by date if provided
            if target_date and b.get("appointment_date") == target_date.isoformat():
                return b

        # If only patient name is provided and exactly one booking exists, use it
        patient_bookings = [
            b for b in self._bookings
            if b.get("status") == "confirmed" and b.get("patient_name", "").strip().lower() == p_name_norm
        ]
        if len(patient_bookings) == 1:
            return patient_bookings[0]

        return None

    def reschedule_appointment(self, request: AppointmentRescheduleRequest) -> AppointmentRescheduleResponse:
        """Reschedule an existing confirmed appointment to a new date and time."""
        doctor = request.doctor_name or "Dr. Chintan Shah"
        target_booking = self._find_booking(
            request.patient_name,
            request.appointment_reference,
            request.current_date,
        )

        if not target_booking:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"No active appointment found for patient '{request.patient_name}' to reschedule. "
                    "Please provide your booking reference or verify your appointment date."
                ),
            )

        # Validate new time
        if request.new_time not in self.STANDARD_SLOTS:
            valid_slots = ", ".join(self.STANDARD_SLOTS)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Requested slot '{request.new_time}' is not a valid clinic slot ({valid_slots}).",
            )

        # Check conflict on new date/time
        new_sched_key = self._get_schedule_key(doctor, request.new_date)
        new_booked = self._booked_slots.setdefault(new_sched_key, set())
        if request.new_time in new_booked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"The new slot {request.new_time} on {request.new_date.isoformat()} is already booked.",
            )

        # Release old slot
        old_date_str = target_booking["appointment_date"]
        old_time = target_booking["appointment_time"]
        old_sched_key = f"{doctor.strip().lower()}_{old_date_str}"
        if old_sched_key in self._booked_slots and old_time in self._booked_slots[old_sched_key]:
            self._booked_slots[old_sched_key].remove(old_time)

        # Reserve new slot
        new_booked.add(request.new_time)

        # Update booking record
        target_booking["appointment_date"] = request.new_date.isoformat()
        target_booking["appointment_time"] = request.new_time
        target_booking["doctor_name"] = doctor

        new_date_human = request.new_date.strftime("%A, %B %d, %Y")
        booking_ref = target_booking["booking_reference"]
        message = (
            f"Your appointment has been successfully rescheduled to {new_date_human} at {request.new_time} "
            f"with {doctor}. Your booking reference remains {booking_ref}. Note: This is a simulation."
        )

        return AppointmentRescheduleResponse(
            status="rescheduled",
            booking_reference=booking_ref,
            patient_name=request.patient_name,
            doctor_name=doctor,
            old_date=old_date_str,
            old_time=old_time,
            new_date=request.new_date.isoformat(),
            new_time=request.new_time,
            message=message,
        )

    def cancel_appointment(self, request: AppointmentCancelRequest) -> AppointmentCancelResponse:
        """Cancel an existing confirmed appointment and release the slot."""
        target_booking = self._find_booking(
            request.patient_name,
            request.appointment_reference,
            request.appointment_date,
        )

        if not target_booking:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"No active appointment found for patient '{request.patient_name}' to cancel. "
                    "Please verify your details or provide your booking reference."
                ),
            )

        # Release slot
        doctor = target_booking.get("doctor_name", "Dr. Chintan Shah")
        apt_date_str = target_booking["appointment_date"]
        apt_time = target_booking["appointment_time"]
        sched_key = f"{doctor.strip().lower()}_{apt_date_str}"
        if sched_key in self._booked_slots and apt_time in self._booked_slots[sched_key]:
            self._booked_slots[sched_key].remove(apt_time)

        # Mark cancelled
        target_booking["status"] = "cancelled"
        booking_ref = target_booking["booking_reference"]

        message = (
            f"Your appointment on {apt_date_str} at {apt_time} has been cancelled. "
            f"Confirmation reference: {booking_ref}. Note: This is a simulated cancellation."
        )

        return AppointmentCancelResponse(
            status="cancelled",
            booking_reference=booking_ref,
            patient_name=request.patient_name,
            cancelled_date=apt_date_str,
            cancelled_time=apt_time,
            message=message,
        )

    def reset(self) -> None:
        """Reset state for clean automated testing."""
        self._booked_slots.clear()
        self._bookings.clear()


appointment_service = AppointmentService()

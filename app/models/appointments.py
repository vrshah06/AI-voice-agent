"""Appointment data models for checking availability, booking, rescheduling, and cancellation."""
from datetime import date
import re
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
from app.models.common import BaseDemoResponse, validate_date_not_in_past, validate_dob_not_future


TIME_FORMAT_REGEX = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class AppointmentAvailabilityRequest(BaseModel):
    """Payload to query demo appointment slots."""
    patient_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Full name of patient.",
        examples=["Eleanor Vance"]
    )
    date_of_birth: date = Field(
        ...,
        description="Patient date of birth (YYYY-MM-DD).",
        examples=["1985-04-12"]
    )
    doctor_name: Optional[str] = Field(
        default="Dr. Chintan Shah",
        description="Requested physician or provider name.",
        examples=["Dr. Chintan Shah"]
    )
    requested_date: date = Field(
        ...,
        description="Target appointment date in YYYY-MM-DD format (must not be in the past).",
        examples=["2026-10-25"]
    )

    @field_validator("patient_name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Patient name cannot be empty.")
        return cleaned

    @field_validator("date_of_birth")
    @classmethod
    def check_dob(cls, v: date) -> date:
        return validate_dob_not_future(v)

    @field_validator("requested_date")
    @classmethod
    def check_requested_date(cls, v: date) -> date:
        return validate_date_not_in_past(v)


class AppointmentAvailabilityResponse(BaseDemoResponse):
    """Available sample slots returned for the requested date."""
    status: str = Field(default="available", description="Query status.")
    patient_name: str = Field(..., description="Echoed patient name.")
    doctor_name: str = Field(..., description="Physician name.")
    requested_date: str = Field(..., description="Target date formatted as YYYY-MM-DD.")
    available_slots: List[str] = Field(
        ...,
        description="List of available times (e.g. ['09:00', '11:00', '14:30']).",
        examples=[["09:00", "11:00", "14:30"]]
    )
    message: str = Field(
        ...,
        description="Conversational string for the virtual receptionist to read aloud."
    )


class AppointmentBookRequest(BaseModel):
    """Payload to book an appointment slot."""
    patient_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Full name of patient.",
        examples=["Eleanor Vance"]
    )
    date_of_birth: date = Field(
        ...,
        description="Patient date of birth (YYYY-MM-DD).",
        examples=["1985-04-12"]
    )
    doctor_name: str = Field(
        default="Dr. Chintan Shah",
        min_length=2,
        max_length=100,
        description="Requested physician name.",
        examples=["Dr. Chintan Shah"]
    )
    appointment_date: date = Field(
        ...,
        description="Appointment date in YYYY-MM-DD format (must not be in the past).",
        examples=["2026-10-25"]
    )
    appointment_time: str = Field(
        ...,
        description="Appointment time in 24-hour HH:MM format.",
        examples=["09:00"]
    )

    @field_validator("patient_name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Patient name cannot be empty.")
        return cleaned

    @field_validator("date_of_birth")
    @classmethod
    def check_dob(cls, v: date) -> date:
        return validate_dob_not_future(v)

    @field_validator("appointment_date")
    @classmethod
    def check_appointment_date(cls, v: date) -> date:
        return validate_date_not_in_past(v)

    @field_validator("appointment_time")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        cleaned = v.strip()
        if not TIME_FORMAT_REGEX.match(cleaned):
            raise ValueError(f"Invalid time format '{v}'. Expected 24-hour HH:MM (e.g., '09:00', '14:30').")
        return cleaned


class AppointmentBookResponse(BaseDemoResponse):
    """Response returned upon simulated appointment confirmation."""
    status: str = Field(default="confirmed", description="Booking outcome status.")
    booking_reference: str = Field(
        ...,
        description="Unique simulated appointment booking reference code.",
        examples=["BK-DEMO-20261025-0900-581"]
    )
    patient_name: str = Field(..., description="Patient name.")
    doctor_name: str = Field(..., description="Doctor name.")
    appointment_date: str = Field(..., description="Date of appointment (YYYY-MM-DD).")
    appointment_time: str = Field(..., description="Time of appointment (HH:MM).")
    message: str = Field(
        ...,
        description="Natural language summary for voice assistant confirmation."
    )


class AppointmentRescheduleRequest(BaseModel):
    """Payload to reschedule an existing appointment to a new date and time."""
    patient_name: str = Field(..., min_length=2, max_length=100, description="Patient full name.")
    date_of_birth: date = Field(..., description="Patient date of birth (YYYY-MM-DD).")
    appointment_reference: Optional[str] = Field(
        default=None,
        description="Existing booking reference code if known (e.g. BK-DEMO-...).",
    )
    current_date: Optional[date] = Field(
        default=None,
        description="Date of current appointment if reference code is not remembered.",
    )
    doctor_name: Optional[str] = Field(
        default="Dr. Chintan Shah",
        description="Doctor name.",
    )
    new_date: date = Field(
        ...,
        description="New requested appointment date in YYYY-MM-DD format (must not be in the past).",
    )
    new_time: str = Field(
        ...,
        description="New requested time in 24-hour HH:MM format.",
        examples=["11:00"]
    )

    @field_validator("new_date")
    @classmethod
    def check_new_date(cls, v: date) -> date:
        return validate_date_not_in_past(v)

    @field_validator("new_time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        cleaned = v.strip()
        if not TIME_FORMAT_REGEX.match(cleaned):
            raise ValueError(f"Invalid time format '{v}'. Expected 24-hour HH:MM (e.g. '09:00', '11:00').")
        return cleaned


class AppointmentRescheduleResponse(BaseDemoResponse):
    """Structured response for appointment rescheduling."""
    status: str = Field(default="rescheduled", description="Rescheduling outcome.")
    booking_reference: str = Field(..., description="Active booking reference.")
    patient_name: str = Field(..., description="Patient name.")
    doctor_name: str = Field(..., description="Doctor name.")
    old_date: str = Field(..., description="Previous appointment date.")
    old_time: str = Field(..., description="Previous appointment time.")
    new_date: str = Field(..., description="Updated appointment date.")
    new_time: str = Field(..., description="Updated appointment time.")
    message: str = Field(..., description="Spoken message for voice agent.")


class AppointmentCancelRequest(BaseModel):
    """Payload to cancel an existing appointment."""
    patient_name: str = Field(..., min_length=2, max_length=100, description="Patient full name.")
    date_of_birth: date = Field(..., description="Patient date of birth (YYYY-MM-DD).")
    appointment_reference: Optional[str] = Field(
        default=None,
        description="Booking reference code if provided by caller.",
    )
    appointment_date: Optional[date] = Field(
        default=None,
        description="Approximate date of the appointment to cancel if reference code is unknown.",
    )
    reason: Optional[str] = Field(
        default="Patient request",
        description="Optional reason for cancellation.",
    )


class AppointmentCancelResponse(BaseDemoResponse):
    """Structured response for appointment cancellation."""
    status: str = Field(default="cancelled", description="Cancellation outcome.")
    booking_reference: str = Field(..., description="Cancelled appointment reference.")
    patient_name: str = Field(..., description="Patient name.")
    cancelled_date: str = Field(..., description="Date of cancelled appointment.")
    cancelled_time: str = Field(..., description="Time of cancelled appointment.")
    message: str = Field(..., description="Spoken message for voice agent.")

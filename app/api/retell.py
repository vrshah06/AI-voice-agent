"""Retell AI tool webhook adapter.

Provides seamless compatibility with Retell AI custom functions and subagent nodes,
supporting both wrapped payloads ({name, call, args}) and flat payloads, header-based
API key auth, and conversational error handling so voice agents do not crash during live calls.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

from app.api.appointments import execute_appointment_search
from app.core.security import verify_retell_or_api_key
from app.models.appointments import (
    AppointmentAvailabilityRequest,
    AppointmentBookRequest,
    AppointmentCancelRequest,
    AppointmentDetail,
    AppointmentRescheduleRequest,
)
from app.models.knowledge import ClinicKnowledgeRequest
from app.models.medications import MedicationRefillRequest
from app.models.messages import TakeMessageRequest
from app.models.patient import PatientIdentifyRequest, PatientInfoRequest
from app.models.retell import RetellToolResponse, RetellWebhookRequest
from app.services.appointment_service import appointment_service
from app.services.knowledge_service import knowledge_service
from app.services.message_service import message_service
from app.services.patient_service import patient_service
from app.services.refill_service import refill_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/retell",
    tags=["Retell AI Adapter"],
    dependencies=[Depends(verify_retell_or_api_key)],
)


def _normalize_optional_date(raw: Any) -> Optional[str]:
    """Normalize optional date input (YYYY-MM-DD or MM/DD/YYYY) into YYYY-MM-DD."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s


def _format_spoken_date(iso_date: Optional[str]) -> str:
    """Format YYYY-MM-DD into a natural spoken date (e.g. 'November 20, 2026')."""
    if not iso_date:
        return "an unspecified date"
    try:
        dt = datetime.strptime(iso_date, "%Y-%m-%d").date()
        return dt.strftime("%B %d, %Y").replace(" 0", " ")
    except ValueError:
        return iso_date


def _format_appointments_for_voice(
    patient_name: str,
    appointments: List[AppointmentDetail],
) -> str:
    """Build a concise, natural spoken summary of retrieved eCW appointments."""
    total = len(appointments)
    noun = "appointment" if total == 1 else "appointments"
    parts = [f"I found {total} {noun} for {patient_name}."]

    max_spoken = 5
    for idx, apt in enumerate(appointments[:max_spoken]):
        date_str = _format_spoken_date(apt.appointment_date)
        time_str = f" at {apt.appointment_time}" if apt.appointment_time else ""
        provider_str = f" with {apt.provider}" if apt.provider else ""
        location_str = f" at {apt.location}" if apt.location else ""
        type_str = f" ({apt.visit_type})" if apt.visit_type else ""
        status_str = f", status {apt.status}" if apt.status else ""

        prefix = "First," if total > 1 and idx == 0 else ("Next," if total > 1 else "It is")
        parts.append(f"{prefix} on {date_str}{time_str}{provider_str}{location_str}{type_str}{status_str}.")

    if total > max_spoken:
        parts.append(f"There are {total - max_spoken} additional appointments on file.")

    return " ".join(parts)


async def _dispatch_tool(tool_name: str, args: Dict[str, Any]) -> RetellToolResponse:
    """Internal dispatcher for all Retell AI tools."""
    normalized_name = tool_name.strip().lower()

    try:
        # 1. Identify / Verify Patient (Live eCW FHIR lookup)
        if normalized_name in ["identify_patient", "patient_identify", "verify_patient"]:
            req = PatientIdentifyRequest(**args)
            result = await patient_service.identify_patient(req)
            return RetellToolResponse(
                status="success" if result.identity_verified else (result.status or "success"),
                message=result.message,
                data=result.model_dump(),
            )

        # 1b. Get Patient Information (Post-Verification)
        elif normalized_name in ["get_patient_information", "get_patient_info", "patient_info", "lookup_patient"]:
            req = PatientInfoRequest(**args)
            info_result = await patient_service.get_patient_information(req)
            return RetellToolResponse(
                status=info_result.get("status", "success"),
                message=info_result["message"],
                data=info_result,
            )

        # 2. Check Availability
        elif normalized_name in ["check_appointment_availability", "check_availability", "appointment_availability"]:
            req = AppointmentAvailabilityRequest(**args)
            result = appointment_service.get_availability(req)
            return RetellToolResponse(
                status="success",
                message=result.message,
                data=result.model_dump(),
            )

        # 3. Book Appointment
        elif normalized_name in ["book_appointment", "appointment_book"]:
            req = AppointmentBookRequest(**args)
            result = appointment_service.book_appointment(req)
            return RetellToolResponse(
                status="success",
                message=result.message,
                data=result.model_dump(),
            )

        # 4. Reschedule Appointment
        elif normalized_name in ["reschedule_appointment", "appointment_reschedule"]:
            req = AppointmentRescheduleRequest(**args)
            result = appointment_service.reschedule_appointment(req)
            return RetellToolResponse(
                status="success",
                message=result.message,
                data=result.model_dump(),
            )

        # 5. Cancel Appointment
        elif normalized_name in ["cancel_appointment", "appointment_cancel"]:
            req = AppointmentCancelRequest(**args)
            result = appointment_service.cancel_appointment(req)
            return RetellToolResponse(
                status="success",
                message=result.message,
                data=result.model_dump(),
            )

        # 6. Prescription Refill
        elif normalized_name in [
            "request_medication_refill",
            "medication_refill",
            "refill_medication",
            "submit_refill_request",
        ]:
            req = MedicationRefillRequest(**args)
            result = refill_service.request_refill(req)
            return RetellToolResponse(
                status="success",
                message=result.message,
                data=result.model_dump(),
            )


        # 7. Clinic Knowledge / FAQ
        elif normalized_name in ["answer_clinic_question", "clinic_question", "faq", "knowledge_answer", "answer_question"]:
            req = ClinicKnowledgeRequest(**args)
            result = knowledge_service.answer_question(req)
            return RetellToolResponse(
                status="success",
                message=result.message,
                data=result.model_dump(),
            )

        # 8. Take Message
        elif normalized_name in ["take_message", "leave_message", "record_message"]:
            req = TakeMessageRequest(**args)
            result = message_service.take_message(req)
            return RetellToolResponse(
                status="success",
                message=result.message,
                data=result.model_dump(),
            )

        # 9. Search Patient Appointments (Live eCW Patient.read + Encounter.read)
        elif normalized_name in [
            "search_appointments",
            "get_appointments",
            "get_patient_appointments",
            "lookup_appointments",
            "check_appointments",
            "find_appointments",
            "appointment_search",
        ]:
            first_name = str(args.get("first_name") or "").strip()
            last_name = str(args.get("last_name") or "").strip()
            if (not first_name or not last_name) and args.get("patient_name"):
                name_parts = str(args["patient_name"]).strip().split(None, 1)
                if not first_name and name_parts:
                    first_name = name_parts[0]
                if not last_name and len(name_parts) > 1:
                    last_name = name_parts[1]

            if not first_name or not last_name:
                return RetellToolResponse(
                    status="error",
                    message="I need both the patient's first and last name to look up their appointments. Could you please provide their full name?",
                    error="Missing required parameters: first_name and last_name.",
                )

            raw_dob = args.get("dob") or args.get("date_of_birth")
            raw_apt_date = args.get("appointment_date") or args.get("date")
            raw_apt_time = args.get("appointment_time") or args.get("time")

            clean_dob = _normalize_optional_date(raw_dob)
            clean_apt_date = _normalize_optional_date(raw_apt_date)
            clean_apt_time = str(raw_apt_time).strip() if raw_apt_time else None

            result = await execute_appointment_search(
                first_name=first_name,
                last_name=last_name,
                dob=clean_dob,
                appointment_date=clean_apt_date,
                appointment_time=clean_apt_time,
            )

            if not result.success:
                if result.candidates:
                    return RetellToolResponse(
                        status="multiple_matches",
                        message=(
                            f"I found multiple patient records matching {first_name} {last_name}. "
                            "Could you please provide the patient's date of birth so I can confirm the right chart?"
                        ),
                        data=result.model_dump(),
                    )
                return RetellToolResponse(
                    status="not_found",
                    message=result.message or f"I could not find a patient record for {first_name} {last_name}.",
                    data=result.model_dump(),
                )

            patient_display = (
                f"{result.patient.first_name or first_name} {result.patient.last_name or last_name}".strip()
                if result.patient
                else f"{first_name} {last_name}"
            )
            if result.total_appointments == 0:
                spoken_msg = result.message or f"I found {patient_display}'s chart, but there are no appointments on file."
            else:
                spoken_msg = _format_appointments_for_voice(patient_display, result.appointments)

            return RetellToolResponse(
                status="success",
                message=spoken_msg,
                data=result.model_dump(),
            )

        else:
            return RetellToolResponse(
                status="error",
                message=(
                    f"Unknown tool function '{tool_name}'. Available tools: identify_patient, "
                    "search_appointments, check_appointment_availability, book_appointment, reschedule_appointment, "
                    "cancel_appointment, request_medication_refill, answer_clinic_question, take_message."
                ),
                error=f"Unrecognized tool: {tool_name}",
            )

    except ValidationError as ve:
        # Extract first human-readable validation error for voice agent to speak
        errors = ve.errors()
        first_msg = errors[0]["msg"] if errors else "Invalid parameters provided."
        field_loc = " -> ".join(str(loc) for loc in errors[0].get("loc", []))
        friendly_error = f"Validation error on {field_loc}: {first_msg}"
        logger.warning("Retell tool validation error: %s", friendly_error)
        return RetellToolResponse(
            status="error",
            message=f"I couldn't process that: {first_msg}. Could you please verify the details?",
            error=friendly_error,
        )
    except HTTPException as he:
        logger.warning("Retell tool HTTP exception: %s", he.detail)
        return RetellToolResponse(
            status="error",
            message=str(he.detail),
            error=str(he.detail),
        )
    except Exception as exc:
        logger.exception("Unexpected error executing Retell tool %s: %s", tool_name, exc)
        return RetellToolResponse(
            status="error",
            message="An unexpected error occurred while processing your request. Please try again or ask for assistance.",
            error=str(exc),
        )


@router.post(
    "/webhook",
    response_model=RetellToolResponse,
    summary="Retell AI General Webhook Handler",
    description="Unified webhook endpoint for Retell AI custom functions (both wrapped {name, call, args} and direct formats).",
)
async def handle_retell_webhook(raw_request: Request) -> RetellToolResponse:
    """Dispatches incoming Retell custom tool requests based on payload function name."""
    try:
        body = await raw_request.json()
    except Exception:
        return RetellToolResponse(
            status="error",
            message="Invalid JSON request body received.",
            error="Malformed JSON payload",
        )

    # Check if payload is wrapped: {name: "...", call: {...}, args: {...}}
    if "name" in body:
        tool_name = body.get("name", "")
        args = body.get("args") or {}
    else:
        # Fallback if tool name is passed via query param or not specified
        tool_name = raw_request.query_params.get("tool_name", "")
        args = body

    if not tool_name:
        return RetellToolResponse(
            status="error",
            message="No tool name specified in Retell webhook request.",
            error="Missing 'name' field in payload or 'tool_name' query param.",
        )

    return await _dispatch_tool(tool_name, args)


@router.post(
    "/tools/{tool_name}",
    response_model=RetellToolResponse,
    summary="Retell AI Named Tool Handler",
    description="Dedicated URL endpoint for a specific Retell tool (supports both wrapped and flat 'args-only' modes).",
)
async def handle_named_retell_tool(tool_name: str, raw_request: Request) -> RetellToolResponse:
    """Dispatches a named tool endpoint call."""
    try:
        body = await raw_request.json()
    except Exception:
        body = {}

    # Extract args whether wrapped or flat
    if isinstance(body, dict) and "args" in body:
        args = body.get("args") or {}
    else:
        args = body if isinstance(body, dict) else {}

    return await _dispatch_tool(tool_name, args)

"""Retell AI tool webhook adapter.

Provides seamless compatibility with Retell AI custom functions and subagent nodes,
supporting both wrapped payloads ({name, call, args}) and flat payloads, header-based
API key auth, and conversational error handling so voice agents do not crash during live calls.
"""
import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

from app.core.security import verify_retell_or_api_key
from app.models.appointments import (
    AppointmentAvailabilityRequest,
    AppointmentBookRequest,
    AppointmentCancelRequest,
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


def _dispatch_tool(tool_name: str, args: Dict[str, Any]) -> RetellToolResponse:
    """Internal dispatcher for all Retell AI tools."""
    normalized_name = tool_name.strip().lower()

    try:
        # 1. Identify / Verify Patient
        if normalized_name in ["identify_patient", "patient_identify", "verify_patient"]:
            req = PatientIdentifyRequest(**args)
            result = patient_service.identify_patient(req)
            return RetellToolResponse(
                status="success",
                message=result.message,
                data=result.model_dump(),
            )

        # 1b. Get Patient Information (Post-Verification)
        elif normalized_name in ["get_patient_information", "get_patient_info", "patient_info", "lookup_patient"]:
            req = PatientInfoRequest(**args)
            info_result = patient_service.get_patient_information(req)
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

        else:
            return RetellToolResponse(
                status="error",
                message=(
                    f"Unknown tool function '{tool_name}'. Available tools: identify_patient, "
                    "check_appointment_availability, book_appointment, reschedule_appointment, "
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

    return _dispatch_tool(tool_name, args)


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

    return _dispatch_tool(tool_name, args)

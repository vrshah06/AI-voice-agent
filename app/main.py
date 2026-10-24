"""Main FastAPI application entrypoint for AI Receptionist Medical Clinic MVP."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.appointments import router as appointments_router
from app.api.health import router as health_router
from app.api.knowledge import router as knowledge_router
from app.api.medications import router as medications_router
from app.api.messages import router as messages_router
from app.api.patients import router as patients_router
from app.api.retell import router as retell_router
from app.api.auth import router as auth_router
from app.core.config import settings

# Configure basic logging
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ai_receptionist")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    logger.info("Starting up %s (Env: %s)", settings.APP_NAME, settings.APP_ENV)
    logger.info("Clinic: %s | Hours: %s", settings.CLINIC_NAME, settings.CLINIC_HOURS)
    yield
    logger.info("Shutting down %s", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version="0.3.0",
    description=(
        f"### {settings.CLINIC_NAME} AI Receptionist Backend\n\n"
        "**Core Capabilities:**\n"
        f"- 🩺 **Greeting & Triage**: Identify caller intent for {settings.CLINIC_NAME}.\n"
        "- 👤 **Real eCW Patient Demographics**: Live EHR retrieval (`GET /api/patients/{patient_id}`) and search via SMART on FHIR.\n"
        "- 📅 **Appointment Availability & Booking**: In-memory scheduling with conflict prevention.\n"
        "- 🔄 **Reschedule & Cancellation**: Modify or cancel appointments with state release.\n"
        "- 💊 **Medication Refills**: Log refill requests for mandatory physician authorization.\n"
        "- ℹ️ **Clinic Knowledge Base**: Strictly approved answers on hours, location, insurance, etc.\n"
        "- 📝 **Take a Message**: Record caller messages for clinic physicians and staff.\n"
        "- 🎙️ **Retell AI Adapter**: Dedicated endpoints with webhook authentication and safe error handling.\n"
        "- 🔐 **eCW SMART JWKS & Auth Status**: Standards-compliant JWKS and configuration diagnostics."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global Exception Handlers for clean, consistent error responses
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic validation failures with structured details."""
    errors = []
    for err in exc.errors():
        field_loc = " -> ".join(str(loc) for loc in err.get("loc", []))
        errors.append({
            "field": field_loc,
            "message": err.get("msg", "Invalid value"),
            "type": err.get("type", "value_error"),
        })

    primary_msg = errors[0]["message"] if errors else "Validation failed for one or more fields."
    return JSONResponse(
        status_code=422,
        content={
            "status": "validation_error",
            "message": f"Validation failed: {primary_msg}",
            "errors": errors,
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle standard HTTP exceptions with consistent JSON formatting."""
    content = {
        "status": "error",
        "message": exc.detail,
        "status_code": exc.status_code,
    }
    if hasattr(exc, "blocker") and getattr(exc, "blocker"):
        content["blocker"] = getattr(exc, "blocker")
    if request.url.path.startswith("/api/retell") or request.url.path.startswith("/api/appointments"):
        content["is_demo_data"] = True
        content["disclaimer"] = settings.DISCLAIMER
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Handle unexpected server errors."""
    logger.exception("Unhandled server exception: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": "internal_server_error",
            "message": "An unexpected server error occurred. Please try again later.",
        },
    )


# Root Welcome Endpoint
@app.get("/", tags=["General"])
async def root_greeting():
    """Welcome greeting for callers and developers."""
    return {
        "greeting": (
            f"Thank you for calling {settings.CLINIC_NAME}. I am the AI voice receptionist. "
            "How may I help you today?"
        ),
        "clinic": settings.CLINIC_NAME,
        "phone": settings.CLINIC_PHONE,
        "hours": settings.CLINIC_HOURS,
        "intents_supported": [
            "Retrieve patient demographics from eCW EHR",
            "Search patients in eCW EHR",
            "Book an appointment",
            "Reschedule an appointment",
            "Cancel an appointment",
            "Request a medication refill",
            "Ask a general question about clinic hours, location, insurance, etc.",
            "Leave a message for clinic staff",
            "Speak with clinic staff",
        ],
        "documentation": "/docs",
        "health": "/health",
    }


# Register Application Routers
app.include_router(health_router)
app.include_router(patients_router)
app.include_router(appointments_router)
app.include_router(medications_router)
app.include_router(knowledge_router)
app.include_router(messages_router)
app.include_router(retell_router)
app.include_router(auth_router)

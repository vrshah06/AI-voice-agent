"""Health check and system status endpoint."""
from datetime import datetime, timezone
from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    summary="Health Check",
    description="Check server operational status, environment, and demo configuration."
)
async def health_check():
    """Returns application health status, timestamp, and demo mode flags."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "app_name": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "clinic_name": settings.CLINIC_NAME,
        "is_demo": True,
        "disclaimer": settings.DISCLAIMER,
    }

"""API routes package."""
from app.api.health import router as health_router
from app.api.patients import router as patients_router
from app.api.appointments import router as appointments_router
from app.api.medications import router as medications_router
from app.api.knowledge import router as knowledge_router
from app.api.messages import router as messages_router
from app.api.retell import router as retell_router
from app.api.auth import router as auth_router

__all__ = [
    "health_router",
    "patients_router",
    "appointments_router",
    "medications_router",
    "knowledge_router",
    "messages_router",
    "retell_router",
    "auth_router",
]

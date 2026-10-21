"""Pytest fixtures and configuration."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.appointment_service import appointment_service
from app.services.patient_service import patient_service
from app.services.refill_service import refill_service
from app.services.message_service import message_service
from app.core.config import settings


@pytest.fixture(autouse=True)
def reset_in_memory_state():
    """Reset state of all in-memory services before every test run."""
    appointment_service.reset()
    patient_service.reset()
    refill_service.reset()
    message_service.reset()
    yield
    appointment_service.reset()
    patient_service.reset()
    refill_service.reset()
    message_service.reset()


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers():
    """Valid auth headers for protected/webhook endpoints."""
    return {"X-Api-Key": settings.WEBHOOK_SECRET_KEY}

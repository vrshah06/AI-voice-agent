"""Tests for health check and root endpoints."""
from fastapi.testclient import TestClient
from app.core.config import settings


def test_health_check(client: TestClient):
    """Verify health check endpoint returns 200, healthy status, and demo flags."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert data["is_demo"] is True
    assert settings.CLINIC_NAME in data["clinic_name"]
    assert "DEMO PROTOTYPE ONLY" in data["disclaimer"]


def test_root_greeting(client: TestClient):
    """Verify root endpoint provides clinic greeting and supported intents."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "Thank you for calling" in data["greeting"]
    assert settings.CLINIC_NAME in data["greeting"]
    assert "AI voice receptionist" in data["greeting"]
    assert "intents_supported" in data
    assert len(data["intents_supported"]) >= 4

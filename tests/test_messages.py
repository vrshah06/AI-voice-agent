"""Tests for take message endpoint."""
from fastapi.testclient import TestClient


def test_take_message_success(client: TestClient):
    """Verify recording a message for clinic staff returns tracking reference."""
    payload = {
        "caller_name": "Eleanor Vance",
        "callback_number": "555-019-2834",
        "recipient": "Dr. Chintan Shah",
        "message": "Please have the doctor call me regarding my recent lab test results.",
    }
    response = client.post("/api/messages", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "recorded"
    assert data["message_id"].startswith("MSG-DEMO-")
    assert "Eleanor Vance" in data["message"]
    assert "Dr. Chintan Shah" in data["message"]
    assert data["is_demo_data"] is True


def test_take_message_missing_fields(client: TestClient):
    """Verify missing required fields triggers 422 validation error."""
    response = client.post("/api/messages", json={"caller_name": "Eleanor Vance"})
    assert response.status_code == 422

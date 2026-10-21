"""Tests for clinic knowledge base query endpoint."""
from fastapi.testclient import TestClient


def test_knowledge_clinic_hours(client: TestClient):
    """Verify querying clinic hours returns approved clinic facts."""
    response = client.post("/api/knowledge/answer", json={"question": "What are your clinic hours?"})
    assert response.status_code == 200
    data = response.json()
    assert data["answer_found"] is True
    assert data["topic"] == "hours"
    assert "Monday to Friday" in data["answer"]
    assert data["escalate_to_staff"] is False


def test_knowledge_clinic_insurance(client: TestClient):
    """Verify querying insurance returns approved accepted plans."""
    response = client.post("/api/knowledge/answer", json={"question": "Do you accept Medicare and Blue Cross?"})
    assert response.status_code == 200
    data = response.json()
    assert data["answer_found"] is True
    assert "Medicare" in data["answer"]


def test_knowledge_clinic_location(client: TestClient):
    """Verify querying location returns approved clinic address."""
    response = client.post("/api/knowledge/answer", json={"question": "Where is the clinic located?"})
    assert response.status_code == 200
    data = response.json()
    assert data["answer_found"] is True
    assert "100 Medical Center Way" in data["answer"]


def test_knowledge_unanswered_fallback(client: TestClient):
    """Verify unapproved or unknown questions return answer_found=False without hallucinating."""
    response = client.post(
        "/api/knowledge/answer",
        json={"question": "Can I bring my pet iguana into the examination room?"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["answer_found"] is False
    assert data["escalate_to_staff"] is True
    assert "don't have approved information" in data["answer"].lower()

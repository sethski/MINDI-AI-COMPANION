from fastapi.testclient import TestClient

from mindi_agent.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_safe_prompt_allowed() -> None:
    response = client.post("/assistant/respond", json={"text": "summarize my notes"})
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["allowed"] is True
    assert body["status"] == "ready"


def test_risky_prompt_blocked() -> None:
    response = client.post("/assistant/respond", json={"text": "delete all files"})
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["allowed"] is False
    assert body["decision"]["requiresUnlock"] is True

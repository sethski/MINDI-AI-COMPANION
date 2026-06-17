"""Phase 3 proactive layer tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from mindi_agent.main import app

client = TestClient(app)


def test_proactive_briefing_endpoint():
    response = client.post("/ops/proactive/briefing")
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "briefing"
    assert body["message"]


def test_proactive_nudges_consume_when_idle():
    client.post("/ops/proactive/orb-activity", json={"idle": True})
    client.post("/ops/proactive/briefing")
    nudges = client.get("/ops/proactive/nudges?limit=2")
    assert nudges.status_code == 200
    items = nudges.json()
    assert isinstance(items, list)
    assert len(items) >= 1


def test_screen_help_action_route():
    response = client.post(
        "/assistant/respond",
        json={"text": "look at my screen and help me", "mode": "chat"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "Ctrl+Shift+S" in body["reply"]

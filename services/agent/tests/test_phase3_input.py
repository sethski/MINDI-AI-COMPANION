"""Phase 3 input surface tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from mindi_agent.main import app

client = TestClient(app)


def test_chat_history_persists_after_assistant_reply():
    client.delete("/chat/history")
    response = client.post(
        "/assistant/respond",
        json={"text": "hello from phase3 test", "mode": "chat", "tab": "home"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reply"]

    history = client.get("/chat/history?limit=20")
    assert history.status_code == 200
    messages = history.json()["messages"]
    assert any(
        message["role"] == "user" and "phase3 test" in message["content"] for message in messages
    )
    assert any(message["role"] == "assistant" for message in messages)


def test_chat_history_clear():
    client.post(
        "/assistant/respond",
        json={"text": "temporary chat line", "mode": "chat"},
    )
    cleared = client.delete("/chat/history")
    assert cleared.status_code == 200
    assert cleared.json()["deleted"] >= 0
    history = client.get("/chat/history")
    assert history.json()["messages"] == []

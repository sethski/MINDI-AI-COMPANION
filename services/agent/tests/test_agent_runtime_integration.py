import os

import httpx
import pytest

RUNTIME_URL = os.getenv("MINDI_AI_RUNTIME_URL", "http://127.0.0.1:8877").rstrip("/")
AGENT_URL = os.getenv("MINDI_AGENT_URL", "http://127.0.0.1:8765").rstrip("/")

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def require_services() -> None:
    for url in (RUNTIME_URL, AGENT_URL):
        try:
            response = httpx.get(f"{url}/health", timeout=3.0)
            response.raise_for_status()
        except Exception as exc:
            pytest.skip(f"Service not reachable: {url} ({exc})")


def test_agent_ai_status_reflects_runtime(require_services: None) -> None:
    response = httpx.get(f"{AGENT_URL}/ops/ai/status", timeout=8.0)
    body = response.json()
    assert body["accepted"] is True
    assert body["runtime"]["url"].startswith("http")
    assert "llm" in body["features"]


def test_config_roundtrip(require_services: None) -> None:
    original = httpx.get(f"{AGENT_URL}/ops/ai/status", timeout=8.0).json()
    original_tokens = original["config"]["llmMaxTokens"]

    try:
        update = httpx.post(
            f"{AGENT_URL}/ops/ai/config",
            json={"llmMaxTokens": 192, "offlineMode": True},
            timeout=15.0,
        )
        assert update.json()["accepted"] is True
        status = httpx.get(f"{AGENT_URL}/ops/ai/status", timeout=8.0).json()
        assert status["config"]["llmMaxTokens"] == 192
        assert status["runtime"]["reachable"] is True
    finally:
        httpx.post(
            f"{AGENT_URL}/ops/ai/config",
            json={"llmMaxTokens": original_tokens, "offlineMode": True},
            timeout=15.0,
        )


def test_assistant_respond_with_live_runtime(require_services: None) -> None:
    response = httpx.post(
        f"{AGENT_URL}/assistant/respond",
        json={"text": "Say hello in one short sentence."},
        timeout=180.0,
    )
    body = response.json()
    assert body["decision"]["allowed"] is True
    if body.get("degraded"):
        pytest.skip(f"Runtime degraded: {body.get('fallbackReason')}")
    assert body["reply"].strip()

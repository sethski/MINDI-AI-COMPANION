import pytest
from fastapi.testclient import TestClient

from mindi_ai_runtime.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_runtime_status_shape() -> None:
    response = client.get("/runtime/status")
    assert response.status_code == 200
    body = response.json()
    assert "features" in body
    for feature in ("llm", "asr", "ocr"):
        assert feature in body["features"]
        assert "ready" in body["features"][feature]
        assert "pathConfigured" in body["features"][feature]


def test_llm_generate_rejects_empty_prompt() -> None:
    response = client.post("/llm/generate", json={"prompt": "   "})
    body = response.json()
    assert body["accepted"] is False
    assert body["reason"] == "empty_prompt"


def test_asr_transcribe_rejects_invalid_source_type() -> None:
    response = client.post(
        "/asr/transcribe",
        json={"sourceType": "stream", "sourceValue": "noop"},
    )
    body = response.json()
    assert body["accepted"] is False
    assert body["reason"] == "invalid_source_type"


def test_ocr_extract_rejects_missing_path() -> None:
    response = client.post("/ocr/extract", json={"path": ""})
    body = response.json()
    assert body["accepted"] is False


@pytest.mark.integration
def test_llm_generate_live_when_configured() -> None:
    import os

    model_path = os.getenv("MINDI_TEST_GGUF_PATH", "").strip()
    if not model_path:
        pytest.skip("MINDI_TEST_GGUF_PATH not set")

    config = client.post("/runtime/config", json={"llmModelPath": model_path})
    assert config.status_code == 200

    response = client.post("/llm/generate", json={"prompt": "Reply with exactly: OK"})
    body = response.json()
    if not body.get("accepted"):
        pytest.skip(f"LLM probe unavailable: {body.get('reason')}")
    assert body["reply"].strip()

import pytest
from fastapi.testclient import TestClient

from mindi_ai_runtime import main
from mindi_ai_runtime.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_clean_llama_output_strips_cli_banner() -> None:
    noisy = """Loading model...
build      : b9354
model      : qwen2.5-7b-instruct
available commands:
  /exit or Ctrl+C     stop or exit
> <|system|>
Respond in clear concise English.
<|user|>
Answer using the local source context when it is relevant.
Source 1: export.json
Path: C:\\data\\export.json
Excerpt: {"score": 1.0}
User request: hi
Hi there!"""
    assert main._clean_llama_output(noisy) == "Hi there!"


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


def test_runtime_status_reports_ollama_readiness(monkeypatch) -> None:
    original_provider = main.runtime_config.llmProvider
    original_model = main.runtime_config.llmModel
    original_path = main.runtime_config.llmModelPath

    monkeypatch.setattr(main.runtime_config, "llmProvider", "ollama")
    monkeypatch.setattr(main.runtime_config, "llmModel", "qwen2.5:0.5b")
    monkeypatch.setattr(main.runtime_config, "llmModelPath", "")
    monkeypatch.setattr(main, "_ollama_model_available", lambda model: (True, {"reason": "ok"}))

    try:
        response = client.get("/runtime/status")
    finally:
        main.runtime_config.llmProvider = original_provider
        main.runtime_config.llmModel = original_model
        main.runtime_config.llmModelPath = original_path

    body = response.json()
    assert body["features"]["llm"]["ready"] is True
    assert body["features"]["llm"]["provider"] == "ollama"
    assert body["features"]["llm"]["pathConfigured"] is True


def test_llm_generate_routes_to_ollama(monkeypatch) -> None:
    original_provider = main.runtime_config.llmProvider
    original_model = main.runtime_config.llmModel
    original_path = main.runtime_config.llmModelPath

    monkeypatch.setattr(main.runtime_config, "llmProvider", "ollama")
    monkeypatch.setattr(main.runtime_config, "llmModel", "qwen2.5:0.5b")
    monkeypatch.setattr(main.runtime_config, "llmModelPath", "")
    monkeypatch.setattr(main, "_ollama_model_available", lambda model: (True, {"reason": "ok"}))

    def fake_run_ollama(prompt: str) -> tuple[bool, dict]:
        assert "hello from test" in prompt
        return True, {"reply": "ollama says hi"}

    monkeypatch.setattr(main, "_run_ollama", fake_run_ollama)

    try:
        response = client.post("/llm/generate", json={"prompt": "hello from test"})
    finally:
        main.runtime_config.llmProvider = original_provider
        main.runtime_config.llmModel = original_model
        main.runtime_config.llmModelPath = original_path

    body = response.json()
    assert body["accepted"] is True
    assert body["provider"] == "ollama"
    assert body["model"] == "qwen2.5:0.5b"
    assert body["reply"] == "ollama says hi"


def test_asr_transcribe_rejects_invalid_source_type() -> None:
    response = client.post(
        "/asr/transcribe",
        json={"sourceType": "stream", "sourceValue": "noop"},
    )
    body = response.json()
    assert body["accepted"] is False
    assert body["reason"] == "invalid_source_type"


def test_asr_transcribe_retries_after_stale_load_failure(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"RIFFtest")
    model_dir = tmp_path / "asr-model"
    model_dir.mkdir()

    original_path = main.runtime_config.asrModelPath
    original_language_hint = main.runtime_config.asrLanguageHint
    original_return_timestamps = main.runtime_config.asrReturnTimestamps
    original_error = main.asr_runtime_error
    original_model = main.asr_model
    original_model_ref = main.asr_model_ref

    class FakeResult:
        text = "hello world"
        time_stamps = None

    class FakeModel:
        def transcribe(self, *, audio, language, return_time_stamps):
            assert audio == str(audio_path.resolve())
            assert language is None
            assert return_time_stamps is False
            return [FakeResult()]

    def fake_load():
        main.asr_model = FakeModel()
        main.asr_runtime_error = None
        main.asr_model_ref = str(model_dir)
        return True, {"reason": "ok"}

    monkeypatch.setattr(main.runtime_config, "asrModelPath", str(model_dir))
    monkeypatch.setattr(main.runtime_config, "asrLanguageHint", None)
    monkeypatch.setattr(main.runtime_config, "asrReturnTimestamps", False)
    monkeypatch.setattr(main, "asr_runtime_error", "asr_model_load_failed")
    monkeypatch.setattr(main, "asr_model", None)
    monkeypatch.setattr(main, "asr_model_ref", None)
    monkeypatch.setattr(main, "_load_qwen_asr_model", fake_load)

    try:
        response = client.post(
            "/asr/transcribe",
            json={"sourceType": "file", "sourceValue": str(audio_path)},
        )
    finally:
        main.runtime_config.asrModelPath = original_path
        main.runtime_config.asrLanguageHint = original_language_hint
        main.runtime_config.asrReturnTimestamps = original_return_timestamps
        main.asr_runtime_error = original_error
        main.asr_model = original_model
        main.asr_model_ref = original_model_ref

    body = response.json()
    assert body["accepted"] is True
    assert body["reason"] == "ok"
    assert body["text"] == "hello world"


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

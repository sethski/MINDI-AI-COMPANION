from __future__ import annotations

import json
from pathlib import Path

import pytest

from mindi_agent.main import store
from mindi_agent.memory_db import MemoryDB

_DEFAULT_TEST_CONFIG = {
    "llmModelPath": "",
    "llmLanguagePackPath": "",
    "asrModelPath": "",
    "ocrModelPath": "",
    "ocrPythonExecutable": "",
    "llmCommand": "llama-cli",
    "llmContextSize": 4096,
    "llmMaxTokens": 256,
    "llmTemperature": 0.2,
    "llmThreads": 0,
    "llmProvider": "llama.cpp",
    "asrProvider": "huggingface_local",
    "ocrProvider": "huggingface_local",
    "llmModel": "Qwen/Qwen2.5-7B-Instruct",
    "asrModel": "Qwen/Qwen3-ASR-1.7B",
    "ocrModel": "zai-org/GLM-OCR",
    "asrLanguageHint": None,
    "asrReturnTimestamps": False,
    "asrMaxTokens": 256,
    "offlineMode": True,
    "experimentalAsr": True,
    "experimentalOcr": True,
}


@pytest.fixture(autouse=True)
def isolated_memory_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid cross-test pollution in the shared data/runtime/memory.db."""
    monkeypatch.setattr(store, "memory_db", MemoryDB(tmp_path / "memory.db"))


@pytest.fixture(autouse=True)
def isolated_ai_runtime_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep pytest from overwriting the user's data/runtime/ai_runtime_config.json."""
    config_path = tmp_path / "ai_runtime_config.json"
    config_path.write_text(json.dumps(_DEFAULT_TEST_CONFIG, ensure_ascii=True, indent=2), encoding="utf-8")
    monkeypatch.setattr(store.ai_runtime, "config_path", config_path)
    store.ai_runtime._config = store.ai_runtime._load_config()

    original_request = store.ai_runtime._request

    def _request_stub(
        method: str,
        path: str,
        payload: dict | None = None,
        timeout: float = 4.5,
    ) -> tuple[bool, dict]:
        # Never push isolated test config to a live ai_runtime on :8877.
        if method == "POST" and path == "/runtime/config":
            return True, {
                "accepted": True,
                "runtime": {
                    "service": "mindi-ai-runtime",
                    "reachable": False,
                    "offlineMode": True,
                    "lastError": None,
                },
            }
        return original_request(method, path, payload, timeout)

    monkeypatch.setattr(store.ai_runtime, "_request", _request_stub)


@pytest.fixture(autouse=True)
def prefer_local_ocr_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Perception tests mock extract_text_for_ocr; avoid live ai_runtime OCR bypassing mocks."""

    def _runtime_ocr_unavailable(*, path: Path) -> dict:
        return {"accepted": False, "reason": "runtime_unavailable_for_tests"}

    monkeypatch.setattr(store.ai_runtime, "extract_ocr", _runtime_ocr_unavailable)

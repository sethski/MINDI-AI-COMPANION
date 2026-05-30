import json
import os
from pathlib import Path
from time import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_RUNTIME_URL = "http://127.0.0.1:8877"


class LocalAiRuntimeClient:
    def __init__(self, *, base_url: str | None = None, config_path: Path | None = None) -> None:
        self.base_url = (base_url or os.getenv("MINDI_AI_RUNTIME_URL") or DEFAULT_RUNTIME_URL).rstrip("/")
        self.config_path = config_path or Path("data/runtime/ai_runtime_config.json")
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config = self._load_config()

    def _load_config(self) -> dict:
        defaults = {
            "llmModelPath": "",
            "asrModelPath": "",
            "ocrModelPath": "",
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
            "offlineMode": True,
            "experimentalAsr": True,
            "experimentalOcr": True,
        }
        if not self.config_path.exists():
            return defaults
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                merged = dict(defaults)
                merged.update(payload)
                return merged
        except Exception:
            pass
        return defaults

    def _save_config(self, config: dict) -> None:
        self.config_path.write_text(json.dumps(config, ensure_ascii=True, indent=2), encoding="utf-8")
        self._config = config

    def _request(self, method: str, path: str, payload: dict | None = None, timeout: float = 4.5) -> tuple[bool, dict]:
        url = f"{self.base_url}{path}"
        raw = b""
        if payload is not None:
            raw = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        req = Request(
            url=url,
            method=method,
            data=raw if payload is not None else None,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
            data = json.loads(body) if body else {}
            if isinstance(data, dict):
                return True, data
        except HTTPError as exc:
            try:
                err = exc.read().decode("utf-8")
                parsed = json.loads(err)
                if isinstance(parsed, dict):
                    return False, parsed
            except Exception:
                pass
            return False, {"reason": f"http_error:{exc.code}"}
        except (URLError, TimeoutError):
            return False, {"reason": "runtime_unreachable"}
        except Exception:
            return False, {"reason": "runtime_request_failed"}
        return False, {"reason": "runtime_invalid_response"}

    def _feature_defaults(self) -> dict:
        cfg = self._config
        return {
            "llm": {
                "enabled": True,
                "ready": False,
                "experimental": False,
                "pathConfigured": bool(str(cfg.get("llmModelPath", "")).strip()),
                "provider": str(cfg.get("llmProvider", "llama.cpp")),
                "model": str(cfg.get("llmModel", "Qwen/Qwen2.5-7B-Instruct")),
                "lastError": "runtime_unreachable",
            },
            "asr": {
                "enabled": True,
                "ready": False,
                "experimental": bool(cfg.get("experimentalAsr", True)),
                "pathConfigured": bool(str(cfg.get("asrModelPath", "")).strip()),
                "provider": str(cfg.get("asrProvider", "huggingface_local")),
                "model": str(cfg.get("asrModel", "Qwen/Qwen3-ASR-1.7B")),
                "lastError": "runtime_unreachable",
            },
            "ocr": {
                "enabled": True,
                "ready": False,
                "experimental": bool(cfg.get("experimentalOcr", True)),
                "pathConfigured": bool(str(cfg.get("ocrModelPath", "")).strip()),
                "provider": str(cfg.get("ocrProvider", "huggingface_local")),
                "model": str(cfg.get("ocrModel", "zai-org/GLM-OCR")),
                "lastError": "runtime_unreachable",
            },
        }

    def get_status(self) -> dict:
        defaults = self._feature_defaults()
        ok, payload = self._request("GET", "/runtime/status")
        if not ok:
            return {
                "accepted": True,
                "runtime": {
                    "service": "mindi-ai-runtime",
                    "reachable": False,
                    "url": self.base_url,
                    "offlineMode": bool(self._config.get("offlineMode", True)),
                    "lastError": payload.get("reason", "runtime_unreachable"),
                },
                "features": defaults,
                "config": self._config,
            }
        feature_payload = payload.get("features", {})
        for key in ("llm", "asr", "ocr"):
            if isinstance(feature_payload, dict) and isinstance(feature_payload.get(key), dict):
                defaults[key].update(feature_payload[key])
                defaults[key]["pathConfigured"] = defaults[key]["pathConfigured"] or bool(
                    str(defaults[key].get("modelPath", "")).strip()
                )
        runtime_payload = payload.get("runtime", {})
        return {
            "accepted": True,
            "runtime": {
                "service": str(runtime_payload.get("service", "mindi-ai-runtime")),
                "reachable": bool(runtime_payload.get("reachable", True)),
                "url": self.base_url,
                "offlineMode": bool(runtime_payload.get("offlineMode", True)),
                "lastError": runtime_payload.get("lastError"),
            },
            "features": defaults,
            "config": self._config,
        }

    def update_config(self, update: dict) -> dict:
        merged = dict(self._config)
        for key in (
            "llmModelPath",
            "asrModelPath",
            "ocrModelPath",
            "llmCommand",
            "llmContextSize",
            "llmMaxTokens",
            "llmTemperature",
            "llmThreads",
            "llmProvider",
            "asrProvider",
            "ocrProvider",
            "llmModel",
            "asrModel",
            "ocrModel",
            "offlineMode",
            "experimentalAsr",
            "experimentalOcr",
        ):
            if key in update:
                merged[key] = update[key]
        self._save_config(merged)
        self._request("POST", "/runtime/config", payload=merged)
        return self.get_status()

    def generate_reply(self, *, prompt: str, language_mode: str) -> dict:
        started = time()
        ok, payload = self._request(
            "POST",
            "/llm/generate",
            payload={"prompt": prompt, "languageMode": language_mode},
            timeout=12.0,
        )
        latency_ms = int((time() - started) * 1000)
        if not ok or not payload.get("accepted"):
            reason = payload.get("reason", "runtime_unavailable")
            return {
                "accepted": False,
                "reason": reason,
                "provider": str(self._config.get("llmProvider", "llama.cpp")),
                "model": str(self._config.get("llmModel", "Qwen/Qwen2.5-7B-Instruct")),
                "latencyMs": latency_ms,
            }
        return {
            "accepted": True,
            "reason": "ok",
            "reply": str(payload.get("reply", "")),
            "provider": str(payload.get("provider", self._config.get("llmProvider", "llama.cpp"))),
            "model": str(payload.get("model", self._config.get("llmModel", "Qwen/Qwen2.5-7B-Instruct"))),
            "latencyMs": int(payload.get("latencyMs", latency_ms)),
        }

    def transcribe(self, *, source_type: str, source_value: str) -> dict:
        ok, payload = self._request(
            "POST",
            "/asr/transcribe",
            payload={"sourceType": source_type, "sourceValue": source_value},
            timeout=20.0,
        )
        if not ok:
            return {
                "accepted": False,
                "reason": payload.get("reason", "runtime_unavailable"),
                "text": None,
                "segments": [],
                "provider": str(self._config.get("asrProvider", "huggingface_local")),
                "model": str(self._config.get("asrModel", "Qwen/Qwen3-ASR-1.7B")),
                "degraded": True,
            }
        return payload

    def extract_ocr(self, *, path: Path) -> dict:
        ok, payload = self._request(
            "POST",
            "/ocr/extract",
            payload={"path": str(path)},
            timeout=12.0,
        )
        if not ok:
            return {
                "accepted": False,
                "reason": payload.get("reason", "runtime_unavailable"),
                "text": None,
                "ocrMode": None,
                "provider": str(self._config.get("ocrProvider", "huggingface_local")),
                "model": str(self._config.get("ocrModel", "zai-org/GLM-OCR")),
                "degraded": True,
            }
        return payload

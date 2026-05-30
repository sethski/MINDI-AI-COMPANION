from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from time import time
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel


class RuntimeConfig(BaseModel):
    llmModelPath: str = ""
    llmLanguagePackPath: str = ""
    asrModelPath: str = ""
    ocrModelPath: str = ""
    llmCommand: str = "llama-cli"
    llmContextSize: int = 4096
    llmMaxTokens: int = 256
    llmTemperature: float = 0.2
    llmThreads: int = 0
    llmProvider: str = "llama.cpp"
    asrProvider: str = "huggingface_local"
    ocrProvider: str = "huggingface_local"
    llmModel: str = "Qwen/Qwen2.5-7B-Instruct"
    asrModel: str = "Qwen/Qwen3-ASR-1.7B"
    ocrModel: str = "zai-org/GLM-OCR"
    ocrPythonExecutable: str = ""
    asrLanguageHint: str | None = None
    asrReturnTimestamps: bool = False
    asrMaxTokens: int = 256
    offlineMode: bool = True
    experimentalAsr: bool = True
    experimentalOcr: bool = True


class LlmGenerateRequest(BaseModel):
    prompt: str
    languageMode: str = "english"


class AsrTranscribeRequest(BaseModel):
    sourceType: str
    sourceValue: str
    languageHint: str | None = None
    returnTimestamps: bool | None = None


class OcrExtractRequest(BaseModel):
    path: str


RUNTIME_CONFIG_PATH = Path(__file__).resolve().parents[4] / "data" / "runtime" / "ai_runtime_config.json"


def _load_persisted_runtime_config() -> RuntimeConfig:
    try:
        if RUNTIME_CONFIG_PATH.exists():
            raw = json.loads(RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))
            return RuntimeConfig.model_validate(raw)
    except Exception:
        pass
    return RuntimeConfig()


def _persist_runtime_config(config: RuntimeConfig) -> None:
    RUNTIME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_CONFIG_PATH.write_text(
        json.dumps(config.model_dump(), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


app = FastAPI(title="MINDI AI Runtime", version="0.1.0")
runtime_config = _load_persisted_runtime_config()
asr_runtime_error: str | None = None
asr_model_ref: str | None = None
asr_model: Any | None = None
ocr_runtime_error: str | None = None
ocr_model_ref: str | None = None
ocr_pipe: Any | None = None
language_pack_runtime_error: str | None = None
language_pack_ref: str | None = None
language_pack_payload: dict[str, Any] | None = None
feature_telemetry: dict[str, dict[str, Any]] = {
    "llm": {"lastLatencyMs": None, "lastFailureReason": None},
    "asr": {"lastLatencyMs": None, "lastFailureReason": None},
    "ocr": {"lastLatencyMs": None, "lastFailureReason": None},
}


def _resolve_model_path(raw_path: str) -> Path | None:
    if not raw_path.strip():
        return None
    return Path(raw_path).expanduser()


def _resolve_llm_model_path(raw_path: str) -> Path | None:
    """Resolve a GGUF file path, including split-model shards in the same folder."""
    if not raw_path.strip():
        return None
    path = Path(raw_path).expanduser()
    if path.is_file():
        return path
    search_dirs: list[Path] = []
    if path.is_dir():
        search_dirs.append(path)
    elif path.parent.is_dir():
        search_dirs.append(path.parent)
    for directory in search_dirs:
        shards = sorted(directory.glob("*-of-*.gguf"))
        if shards:
            return shards[0]
        any_gguf = sorted(directory.glob("*.gguf"))
        if any_gguf:
            return any_gguf[0]
    return path


def _resolve_asr_model_ref() -> str:
    model_path = runtime_config.asrModelPath.strip()
    if model_path:
        return str(Path(model_path).expanduser())
    return runtime_config.asrModel


def _resolve_language_pack_path() -> Path | None:
    raw_path = runtime_config.llmLanguagePackPath.strip()
    if not raw_path:
        return None
    return Path(raw_path).expanduser()


def _resolve_ocr_model_ref() -> str:
    model_path = runtime_config.ocrModelPath.strip()
    if model_path:
        return str(Path(model_path).expanduser())
    return runtime_config.ocrModel


def _resolve_ocr_python_executable() -> Path | None:
    raw = runtime_config.ocrPythonExecutable.strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _llm_runtime_error(model_path: Path | None) -> str | None:
    if model_path is None:
        return "model_path_missing"
    if not model_path.exists() or not model_path.is_file():
        return "model_path_missing"
    if not runtime_config.llmCommand.strip():
        return "llama_cpp_command_missing"
    if shutil.which(runtime_config.llmCommand.strip()) is None:
        return "llama_cpp_binary_missing"
    return None


def _asr_runtime_error(asr_path: Path | None) -> str | None:
    global asr_runtime_error
    # No local path configured: fall back to the HuggingFace model ref
    # (e.g. Qwen/Qwen3-ASR-1.7B). Readiness then tracks the real load path:
    # the qwen_asr dependency must be importable, otherwise the load fails.
    if asr_path is None:
        if asr_runtime_error is not None:
            return asr_runtime_error
        if importlib.util.find_spec("qwen_asr") is None:
            return "qwen_asr_dependency_missing"
        return None
    if not asr_path.exists():
        return "model_path_missing"
    if not asr_path.is_dir() and not asr_path.is_file():
        return "model_path_missing"
    if asr_runtime_error is not None:
        return asr_runtime_error
    return None


def _ocr_runtime_error(ocr_path: Path | None) -> str | None:
    global ocr_runtime_error
    ocr_python_executable = _resolve_ocr_python_executable()
    if ocr_path is None:
        return "model_path_missing"
    if not ocr_path.exists():
        return "model_path_missing"
    if not ocr_path.is_dir() and not ocr_path.is_file():
        return "model_path_missing"
    if ocr_python_executable is not None and (not ocr_python_executable.exists() or not ocr_python_executable.is_file()):
        return "ocr_helper_python_missing"
    if ocr_runtime_error is not None:
        return ocr_runtime_error
    return None


def _build_llm_prompt(*, prompt: str, language_mode: str) -> str:
    if language_mode == "tagalog":
        system_instruction = "Tumugon sa malinaw at maikling Tagalog."
    elif language_mode == "taglish":
        system_instruction = "Respond in practical Taglish, concise and clear."
    else:
        system_instruction = "Respond in clear concise English."
    return (
        "<|system|>\n"
        f"{system_instruction}\n"
        f"{_language_pack_prompt_hint()}"
        "<|user|>\n"
        f"{prompt.strip()}\n"
        "<|assistant|>\n"
    )


def _load_language_pack() -> tuple[bool, dict]:
    global language_pack_runtime_error, language_pack_ref, language_pack_payload

    language_pack_path = _resolve_language_pack_path()
    if language_pack_path is None:
        language_pack_runtime_error = None
        language_pack_ref = None
        language_pack_payload = None
        return True, {"reason": "none"}

    path_str = str(language_pack_path.resolve())
    if language_pack_payload is not None and language_pack_ref == path_str and language_pack_runtime_error is None:
        return True, {"reason": "ok"}

    if not language_pack_path.exists() or not language_pack_path.is_file():
        language_pack_runtime_error = "language_pack_not_found"
        language_pack_ref = None
        language_pack_payload = None
        return False, {"reason": language_pack_runtime_error}
    try:
        payload = json.loads(language_pack_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        language_pack_runtime_error = "language_pack_invalid_json"
        language_pack_ref = None
        language_pack_payload = None
        return False, {"reason": language_pack_runtime_error}
    if not isinstance(payload, dict):
        language_pack_runtime_error = "language_pack_schema_invalid"
        language_pack_ref = None
        language_pack_payload = None
        return False, {"reason": language_pack_runtime_error}
    top_terms = payload.get("topTerms")
    if not isinstance(top_terms, list):
        language_pack_runtime_error = "language_pack_schema_invalid"
        language_pack_ref = None
        language_pack_payload = None
        return False, {"reason": language_pack_runtime_error}

    language_pack_runtime_error = None
    language_pack_ref = path_str
    language_pack_payload = payload
    return True, {"reason": "ok"}


def _language_pack_prompt_hint() -> str:
    ok, _ = _load_language_pack()
    if not ok or not isinstance(language_pack_payload, dict):
        return ""
    top_terms = language_pack_payload.get("topTerms")
    if not isinstance(top_terms, list):
        return ""
    terms: list[str] = []
    for item in top_terms:
        token = str(item).strip()
        if token and token not in terms:
            terms.append(token)
        if len(terms) >= 20:
            break
    if not terms:
        return ""
    return f"Use practical Filipino/Taglish phrasing when relevant. Preferred terms: {', '.join(terms)}.\n"


def _clean_llama_output(text: str) -> str:
    if not text:
        return ""
    cleaned = text.replace("\r", "").strip()
    for marker in ("<|assistant|>", "assistant\n"):
        if marker in cleaned:
            cleaned = cleaned.split(marker, maxsplit=1)[-1].strip()
    for split_marker in ("\n\n[ Prompt:", "\n[ Prompt:", "\nExiting..."):
        if split_marker in cleaned:
            cleaned = cleaned.split(split_marker, maxsplit=1)[0].strip()
    lines = [line for line in cleaned.split("\n") if line.strip() not in {">", ""}]
    return "\n".join(lines).strip()


def _run_llama_cpp(prompt: str) -> tuple[bool, dict]:
    model_path = _resolve_llm_model_path(runtime_config.llmModelPath)
    runtime_error = _llm_runtime_error(model_path)
    if runtime_error is not None or model_path is None:
        return False, {"reason": runtime_error or "llm_model_not_ready"}

    command = [
        runtime_config.llmCommand.strip(),
        "-m",
        str(model_path),
        "-p",
        prompt,
        "-c",
        str(max(256, int(runtime_config.llmContextSize))),
        "-n",
        str(max(1, int(runtime_config.llmMaxTokens))),
        "--temp",
        str(float(runtime_config.llmTemperature)),
        "--no-display-prompt",
    ]
    if int(runtime_config.llmThreads) > 0:
        command.extend(["-t", str(int(runtime_config.llmThreads))])
    # Default to CPU inference; Vulkan offload often fails on limited VRAM Windows devices.
    command.extend(["-ngl", "0"])
    # Non-interactive one-shot generation; without this llama-cli waits for stdin and hangs.
    command.append("--single-turn")

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=420,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, {"reason": "llama_cpp_timeout"}
    except OSError:
        return False, {"reason": "llama_cpp_exec_failed"}

    output_text = _clean_llama_output(completed.stdout)
    if completed.returncode != 0:
        return False, {
            "reason": "llama_cpp_inference_failed",
            "detail": (completed.stderr or "").strip()[:240],
        }
    if not output_text:
        return False, {"reason": "llama_cpp_empty_output"}
    return True, {"reply": output_text}


def _load_qwen_asr_model() -> tuple[bool, dict]:
    global asr_runtime_error, asr_model_ref, asr_model

    model_ref = _resolve_asr_model_ref()
    if asr_model is not None and asr_model_ref == model_ref and asr_runtime_error is None:
        return True, {"reason": "ok"}

    try:
        from qwen_asr import Qwen3ASRModel
    except Exception:
        asr_runtime_error = "qwen_asr_dependency_missing"
        asr_model = None
        asr_model_ref = None
        return False, {"reason": asr_runtime_error}

    kwargs: dict[str, Any] = {
        "max_new_tokens": max(1, int(runtime_config.asrMaxTokens)),
    }
    try:
        asr_model = Qwen3ASRModel.from_pretrained(model_ref, **kwargs)
    except Exception:
        asr_runtime_error = "asr_model_load_failed"
        asr_model = None
        asr_model_ref = None
        return False, {"reason": asr_runtime_error}

    asr_model_ref = model_ref
    asr_runtime_error = None
    return True, {"reason": "ok"}


def _asr_segments_from_result(text: str, stamp_payload: Any) -> list[dict]:
    segments: list[dict] = []
    if isinstance(stamp_payload, list):
        for item in stamp_payload:
            start_raw = getattr(item, "start_time", None)
            end_raw = getattr(item, "end_time", None)
            label = getattr(item, "text", None)
            if start_raw is None or end_raw is None:
                continue
            try:
                start_ms = max(0, int(float(start_raw) * 1000))
                end_ms = max(start_ms, int(float(end_raw) * 1000))
            except (TypeError, ValueError):
                continue
            segments.append(
                {
                    "startMs": start_ms,
                    "endMs": end_ms,
                    "text": str(label or text),
                }
            )
    if segments:
        return segments
    return [{"startMs": 0, "endMs": max(1200, len(text) * 30), "text": text}]


def _extract_generated_text(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        role = str(payload.get("role", "")).strip().lower()
        if role == "assistant":
            return _extract_generated_text(payload.get("content"))
        if "generated_text" in payload:
            return _extract_generated_text(payload.get("generated_text"))
        if "content" in payload:
            return _extract_generated_text(payload.get("content"))
        if "text" in payload:
            return _extract_generated_text(payload.get("text"))
        return ""
    if isinstance(payload, list):
        assistant_items = [
            item
            for item in payload
            if isinstance(item, dict) and str(item.get("role", "")).strip().lower() == "assistant"
        ]
        if assistant_items:
            return _extract_generated_text(assistant_items[-1])
        chunks = [_extract_generated_text(item) for item in payload]
        filtered = [chunk for chunk in chunks if chunk]
        return "\n".join(filtered).strip()
    return str(payload).strip()


def _normalize_ocr_text(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 2:
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
    return cleaned


def _load_glm_ocr_pipeline() -> tuple[bool, dict]:
    global ocr_runtime_error, ocr_model_ref, ocr_pipe

    model_ref = _resolve_ocr_model_ref()
    if ocr_pipe is not None and ocr_model_ref == model_ref and ocr_runtime_error is None:
        return True, {"reason": "ok"}

    try:
        from transformers import pipeline
    except Exception:
        ocr_runtime_error = "glm_ocr_dependencies_missing"
        ocr_pipe = None
        ocr_model_ref = None
        return False, {"reason": ocr_runtime_error}

    try:
        ocr_pipe = pipeline(
            "image-text-to-text",
            model=model_ref,
            trust_remote_code=True,
        )
    except Exception as exc:
        ocr_runtime_error = "ocr_model_load_failed"
        ocr_pipe = None
        ocr_model_ref = None
        return False, {"reason": ocr_runtime_error, "detail": f"{type(exc).__name__}: {str(exc)[:500]}"}

    ocr_model_ref = model_ref
    ocr_runtime_error = None
    return True, {"reason": "ok"}


def _run_glm_ocr_helper(*, source: Path) -> tuple[bool, dict]:
    ocr_python_executable = _resolve_ocr_python_executable()
    if ocr_python_executable is None:
        return False, {"reason": "ocr_helper_python_missing"}
    helper_script = Path(__file__).with_name("ocr_helper.py")
    if not helper_script.exists():
        return False, {"reason": "ocr_helper_script_missing"}
    command = [
        str(ocr_python_executable),
        str(helper_script),
        "--model-ref",
        _resolve_ocr_model_ref(),
        "--image-path",
        str(source),
        "--max-new-tokens",
        "1024",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=420,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, {"reason": "ocr_helper_timeout"}
    except OSError as exc:
        return False, {"reason": "ocr_helper_exec_failed", "detail": f"{type(exc).__name__}: {str(exc)[:500]}"}

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0:
        return False, {"reason": "ocr_helper_failed", "detail": (stderr or stdout)[:500]}
    if not stdout:
        return False, {"reason": "ocr_helper_empty_output"}
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return False, {"reason": "ocr_helper_invalid_json", "detail": stdout[:500]}
    if not isinstance(payload, dict):
        return False, {"reason": "ocr_helper_invalid_payload"}
    return bool(payload.get("accepted", False)), payload


def _record_feature_failure(feature: str, reason: str, latency_ms: int | None = None) -> None:
    telemetry = feature_telemetry.get(feature)
    if telemetry is None:
        return
    telemetry["lastFailureReason"] = reason
    if latency_ms is not None:
        telemetry["lastLatencyMs"] = max(0, int(latency_ms))


def _record_feature_success(feature: str, latency_ms: int) -> None:
    telemetry = feature_telemetry.get(feature)
    if telemetry is None:
        return
    telemetry["lastFailureReason"] = None
    telemetry["lastLatencyMs"] = max(0, int(latency_ms))


def _feature_status() -> dict:
    llm_path = _resolve_llm_model_path(runtime_config.llmModelPath)
    asr_path = _resolve_model_path(runtime_config.asrModelPath)
    ocr_path = _resolve_model_path(runtime_config.ocrModelPath)
    llm_runtime_error = _llm_runtime_error(llm_path)
    asr_ready_error = _asr_runtime_error(asr_path)
    ocr_ready_error = _ocr_runtime_error(ocr_path)
    return {
        "llm": {
            "enabled": True,
            "ready": llm_runtime_error is None,
            "experimental": False,
            "pathConfigured": bool(runtime_config.llmModelPath.strip()),
            "provider": runtime_config.llmProvider,
            "model": runtime_config.llmModel,
            "modelPath": runtime_config.llmModelPath,
            "lastError": llm_runtime_error,
            "lastLatencyMs": feature_telemetry["llm"].get("lastLatencyMs"),
            "lastFailureReason": feature_telemetry["llm"].get("lastFailureReason")
            or llm_runtime_error,
        },
        "asr": {
            "enabled": True,
            "ready": asr_ready_error is None,
            "experimental": runtime_config.experimentalAsr,
            "pathConfigured": bool(runtime_config.asrModelPath.strip()),
            "provider": runtime_config.asrProvider,
            "model": runtime_config.asrModel,
            "modelPath": runtime_config.asrModelPath,
            "lastError": asr_ready_error,
            "lastLatencyMs": feature_telemetry["asr"].get("lastLatencyMs"),
            "lastFailureReason": feature_telemetry["asr"].get("lastFailureReason")
            or asr_ready_error,
        },
        "ocr": {
            "enabled": True,
            "ready": ocr_ready_error is None,
            "experimental": runtime_config.experimentalOcr,
            "pathConfigured": bool(runtime_config.ocrModelPath.strip()),
            "provider": runtime_config.ocrProvider,
            "model": runtime_config.ocrModel,
            "modelPath": runtime_config.ocrModelPath,
            "lastError": ocr_ready_error,
            "lastLatencyMs": feature_telemetry["ocr"].get("lastLatencyMs"),
            "lastFailureReason": feature_telemetry["ocr"].get("lastFailureReason")
            or ocr_ready_error,
        },
    }


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "mindi-ai-runtime", "version": app.version}


@app.get("/runtime/status")
def runtime_status() -> dict:
    return {
        "accepted": True,
        "runtime": {
            "service": "mindi-ai-runtime",
            "reachable": True,
            "offlineMode": runtime_config.offlineMode,
            "lastError": None,
        },
        "features": _feature_status(),
        "config": runtime_config.model_dump(),
    }


@app.post("/runtime/config")
def runtime_update_config(payload: RuntimeConfig) -> dict:
    global runtime_config, asr_runtime_error, asr_model_ref, asr_model, ocr_runtime_error, ocr_model_ref, ocr_pipe
    global language_pack_runtime_error, language_pack_ref, language_pack_payload
    runtime_config = payload
    _persist_runtime_config(runtime_config)
    # Reset ASR cache to force reload after config changes.
    asr_runtime_error = None
    asr_model_ref = None
    asr_model = None
    ocr_runtime_error = None
    ocr_model_ref = None
    ocr_pipe = None
    language_pack_runtime_error = None
    language_pack_ref = None
    language_pack_payload = None
    for telemetry in feature_telemetry.values():
        telemetry["lastLatencyMs"] = None
        telemetry["lastFailureReason"] = None
    return runtime_status()


@app.post("/llm/generate")
def llm_generate(payload: LlmGenerateRequest) -> dict:
    started = time()
    features = _feature_status()
    if not features["llm"]["ready"]:
        _record_feature_failure("llm", features["llm"]["lastError"] or "llm_model_not_ready")
        return {
            "accepted": False,
            "reason": features["llm"]["lastError"] or "llm_model_not_ready",
            "provider": runtime_config.llmProvider,
            "model": runtime_config.llmModel,
        }
    text = payload.prompt.strip()
    if not text:
        _record_feature_failure("llm", "empty_prompt")
        return {
            "accepted": False,
            "reason": "empty_prompt",
            "provider": runtime_config.llmProvider,
            "model": runtime_config.llmModel,
        }
    prompt = _build_llm_prompt(prompt=text, language_mode=payload.languageMode)
    ok, result = _run_llama_cpp(prompt)
    if not ok:
        latency_ms = int((time() - started) * 1000)
        _record_feature_failure("llm", str(result.get("reason", "llm_runtime_error")), latency_ms)
        return {
            "accepted": False,
            "reason": result.get("reason", "llm_runtime_error"),
            "detail": result.get("detail"),
            "provider": runtime_config.llmProvider,
            "model": runtime_config.llmModel,
            "degraded": True,
        }
    latency_ms = int((time() - started) * 1000)
    _record_feature_success("llm", latency_ms)
    return {
        "accepted": True,
        "reason": "ok",
        "reply": str(result["reply"]).strip(),
        "provider": runtime_config.llmProvider,
        "model": runtime_config.llmModel,
        "latencyMs": latency_ms,
    }


@app.post("/asr/transcribe")
def asr_transcribe(payload: AsrTranscribeRequest) -> dict:
    started = time()
    features = _feature_status()
    if payload.sourceType not in {"file", "mic"}:
        _record_feature_failure("asr", "invalid_source_type")
        return {"accepted": False, "reason": "invalid_source_type"}
    if not features["asr"]["ready"]:
        _record_feature_failure("asr", "asr_model_not_ready")
        return {
            "accepted": False,
            "reason": "asr_model_not_ready",
            "provider": runtime_config.asrProvider,
            "model": runtime_config.asrModel,
            "degraded": True,
        }
    value = payload.sourceValue.strip()
    if not value:
        _record_feature_failure("asr", "source_value_required")
        return {"accepted": False, "reason": "source_value_required"}

    if payload.sourceType == "file":
        audio_input = str(Path(value).resolve())
        file_path = Path(audio_input)
        if not file_path.exists() or not file_path.is_file():
            _record_feature_failure("asr", "audio_not_found")
            return {"accepted": False, "reason": "audio_not_found"}
    else:
        candidate = Path(value)
        if candidate.exists() and candidate.is_file():
            audio_input = str(candidate.resolve())
        else:
            audio_input = value

    ok, load_result = _load_qwen_asr_model()
    if not ok:
        _record_feature_failure("asr", str(load_result.get("reason", "asr_backend_unavailable")))
        return {
            "accepted": False,
            "reason": load_result.get("reason", "asr_backend_unavailable"),
            "provider": runtime_config.asrProvider,
            "model": runtime_config.asrModel,
            "degraded": True,
        }

    assert asr_model is not None
    language_hint = payload.languageHint if payload.languageHint is not None else runtime_config.asrLanguageHint
    return_timestamps = (
        payload.returnTimestamps if payload.returnTimestamps is not None else runtime_config.asrReturnTimestamps
    )
    try:
        results = asr_model.transcribe(
            audio=audio_input,
            language=language_hint,
            return_time_stamps=bool(return_timestamps),
        )
    except ValueError:
        # Retry without forced-align timestamps when aligner is not configured.
        try:
            results = asr_model.transcribe(
                audio=audio_input,
                language=language_hint,
                return_time_stamps=False,
            )
        except Exception:
            _record_feature_failure("asr", "asr_inference_failed", int((time() - started) * 1000))
            return {
                "accepted": False,
                "reason": "asr_inference_failed",
                "provider": runtime_config.asrProvider,
                "model": runtime_config.asrModel,
                "degraded": True,
            }
    except Exception:
        _record_feature_failure("asr", "asr_inference_failed", int((time() - started) * 1000))
        return {
            "accepted": False,
            "reason": "asr_inference_failed",
            "provider": runtime_config.asrProvider,
            "model": runtime_config.asrModel,
            "degraded": True,
        }

    if not results:
        _record_feature_failure("asr", "asr_empty_result", int((time() - started) * 1000))
        return {
            "accepted": False,
            "reason": "asr_empty_result",
            "provider": runtime_config.asrProvider,
            "model": runtime_config.asrModel,
            "degraded": True,
        }

    first = results[0]
    text = str(getattr(first, "text", "") or "").strip()
    if not text:
        _record_feature_failure("asr", "asr_no_text_detected", int((time() - started) * 1000))
        return {
            "accepted": False,
            "reason": "asr_no_text_detected",
            "provider": runtime_config.asrProvider,
            "model": runtime_config.asrModel,
            "degraded": True,
        }
    time_stamps = getattr(first, "time_stamps", None)
    segments = _asr_segments_from_result(text, time_stamps)
    latency_ms = int((time() - started) * 1000)
    _record_feature_success("asr", latency_ms)
    return {
        "accepted": True,
        "reason": "ok",
        "text": text,
        "segments": segments,
        "provider": runtime_config.asrProvider,
        "model": runtime_config.asrModel,
        "degraded": False,
        "latencyMs": latency_ms,
    }


@app.post("/ocr/extract")
def ocr_extract(payload: OcrExtractRequest) -> dict:
    started = time()
    features = _feature_status()
    if not features["ocr"]["ready"]:
        _record_feature_failure("ocr", features["ocr"]["lastError"] or "ocr_model_not_ready")
        return {
            "accepted": False,
            "reason": features["ocr"]["lastError"] or "ocr_model_not_ready",
            "provider": runtime_config.ocrProvider,
            "model": runtime_config.ocrModel,
            "degraded": True,
        }
    source = Path(payload.path).resolve()
    if not source.exists() or not source.is_file():
        _record_feature_failure("ocr", "image_not_found")
        return {"accepted": False, "reason": "image_not_found"}

    ocr_python_executable = _resolve_ocr_python_executable()
    if ocr_python_executable is not None:
        ok, payload_result = _run_glm_ocr_helper(source=source)
        if not ok:
            reason = str(payload_result.get("reason", "ocr_backend_unavailable"))
            _record_feature_failure("ocr", reason, int((time() - started) * 1000))
            return {
                "accepted": False,
                "reason": reason,
                "detail": payload_result.get("detail"),
                "provider": runtime_config.ocrProvider,
                "model": runtime_config.ocrModel,
                "degraded": True,
            }
        text = _normalize_ocr_text(_extract_generated_text(payload_result.get("text", "")))
    else:
        ok, load_result = _load_glm_ocr_pipeline()
        if not ok:
            _record_feature_failure("ocr", str(load_result.get("reason", "ocr_backend_unavailable")))
            return {
                "accepted": False,
                "reason": load_result.get("reason", "ocr_backend_unavailable"),
                "detail": load_result.get("detail"),
                "provider": runtime_config.ocrProvider,
                "model": runtime_config.ocrModel,
                "degraded": True,
            }
        assert ocr_pipe is not None
        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "url": str(source)},
                        {"type": "text", "text": "Text Recognition:"},
                    ],
                }
            ]
            result = ocr_pipe(text=messages, return_full_text=False, max_new_tokens=1024)
        except Exception as exc:
            _record_feature_failure("ocr", "ocr_inference_failed", int((time() - started) * 1000))
            return {
                "accepted": False,
                "reason": "ocr_inference_failed",
                "detail": f"{type(exc).__name__}: {str(exc)[:500]}",
                "provider": runtime_config.ocrProvider,
                "model": runtime_config.ocrModel,
                "degraded": True,
            }
        text = _normalize_ocr_text(_extract_generated_text(result))
    if not text:
        _record_feature_failure("ocr", "ocr_no_text_detected", int((time() - started) * 1000))
        return {
            "accepted": False,
            "reason": "ocr_no_text_detected",
            "provider": runtime_config.ocrProvider,
            "model": runtime_config.ocrModel,
            "degraded": True,
        }
    latency_ms = int((time() - started) * 1000)
    _record_feature_success("ocr", latency_ms)
    return {
        "accepted": True,
        "reason": "ok",
        "text": text,
        "ocrMode": "glm_ocr_markdown",
        "provider": runtime_config.ocrProvider,
        "model": runtime_config.ocrModel,
        "degraded": False,
        "latencyMs": latency_ms,
    }

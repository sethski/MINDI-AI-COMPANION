from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from time import time
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel


class RuntimeConfig(BaseModel):
    llmModelPath: str = ""
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


app = FastAPI(title="MINDI AI Runtime", version="0.1.0")
runtime_config = RuntimeConfig()
asr_runtime_error: str | None = None
asr_model_ref: str | None = None
asr_model: Any | None = None


def _resolve_model_path(raw_path: str) -> Path | None:
    if not raw_path.strip():
        return None
    return Path(raw_path).expanduser()


def _resolve_asr_model_ref() -> str:
    model_path = runtime_config.asrModelPath.strip()
    if model_path:
        return str(Path(model_path).expanduser())
    return runtime_config.asrModel


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
    if asr_path is None:
        return "model_path_missing"
    if not asr_path.exists():
        return "model_path_missing"
    if not asr_path.is_dir() and not asr_path.is_file():
        return "model_path_missing"
    if asr_runtime_error is not None:
        return asr_runtime_error
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
        "<|user|>\n"
        f"{prompt.strip()}\n"
        "<|assistant|>\n"
    )


def _clean_llama_output(text: str) -> str:
    if not text:
        return ""
    cleaned = text.replace("\r", "").strip()
    for marker in ("<|assistant|>", "assistant\n"):
        if marker in cleaned:
            cleaned = cleaned.split(marker, maxsplit=1)[-1].strip()
    return cleaned


def _run_llama_cpp(prompt: str) -> tuple[bool, dict]:
    model_path = _resolve_model_path(runtime_config.llmModelPath)
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

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
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


def _feature_status() -> dict:
    llm_path = _resolve_model_path(runtime_config.llmModelPath)
    asr_path = _resolve_model_path(runtime_config.asrModelPath)
    ocr_path = _resolve_model_path(runtime_config.ocrModelPath)
    llm_runtime_error = _llm_runtime_error(llm_path)
    asr_ready_error = _asr_runtime_error(asr_path)
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
        },
        "ocr": {
            "enabled": True,
            "ready": bool(ocr_path and ocr_path.exists()),
            "experimental": runtime_config.experimentalOcr,
            "pathConfigured": bool(runtime_config.ocrModelPath.strip()),
            "provider": runtime_config.ocrProvider,
            "model": runtime_config.ocrModel,
            "modelPath": runtime_config.ocrModelPath,
            "lastError": None if (ocr_path and ocr_path.exists()) else "model_path_missing",
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
    global runtime_config, asr_runtime_error, asr_model_ref, asr_model
    runtime_config = payload
    # Reset ASR cache to force reload after config changes.
    asr_runtime_error = None
    asr_model_ref = None
    asr_model = None
    return runtime_status()


@app.post("/llm/generate")
def llm_generate(payload: LlmGenerateRequest) -> dict:
    features = _feature_status()
    if not features["llm"]["ready"]:
        return {
            "accepted": False,
            "reason": features["llm"]["lastError"] or "llm_model_not_ready",
            "provider": runtime_config.llmProvider,
            "model": runtime_config.llmModel,
        }
    started = time()
    text = payload.prompt.strip()
    if not text:
        return {
            "accepted": False,
            "reason": "empty_prompt",
            "provider": runtime_config.llmProvider,
            "model": runtime_config.llmModel,
        }
    prompt = _build_llm_prompt(prompt=text, language_mode=payload.languageMode)
    ok, result = _run_llama_cpp(prompt)
    if not ok:
        return {
            "accepted": False,
            "reason": result.get("reason", "llm_runtime_error"),
            "detail": result.get("detail"),
            "provider": runtime_config.llmProvider,
            "model": runtime_config.llmModel,
            "degraded": True,
        }
    return {
        "accepted": True,
        "reason": "ok",
        "reply": str(result["reply"]).strip(),
        "provider": runtime_config.llmProvider,
        "model": runtime_config.llmModel,
        "latencyMs": int((time() - started) * 1000),
    }


@app.post("/asr/transcribe")
def asr_transcribe(payload: AsrTranscribeRequest) -> dict:
    features = _feature_status()
    if payload.sourceType not in {"file", "mic"}:
        return {"accepted": False, "reason": "invalid_source_type"}
    if not features["asr"]["ready"]:
        return {
            "accepted": False,
            "reason": "asr_model_not_ready",
            "provider": runtime_config.asrProvider,
            "model": runtime_config.asrModel,
            "degraded": True,
        }
    value = payload.sourceValue.strip()
    if not value:
        return {"accepted": False, "reason": "source_value_required"}

    if payload.sourceType == "file":
        audio_input = str(Path(value).resolve())
        file_path = Path(audio_input)
        if not file_path.exists() or not file_path.is_file():
            return {"accepted": False, "reason": "audio_not_found"}
    else:
        # Mic capture is expected to pass a local audio path or a supported audio URI payload.
        audio_input = value

    ok, load_result = _load_qwen_asr_model()
    if not ok:
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
            return {
                "accepted": False,
                "reason": "asr_inference_failed",
                "provider": runtime_config.asrProvider,
                "model": runtime_config.asrModel,
                "degraded": True,
            }
    except Exception:
        return {
            "accepted": False,
            "reason": "asr_inference_failed",
            "provider": runtime_config.asrProvider,
            "model": runtime_config.asrModel,
            "degraded": True,
        }

    if not results:
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
        return {
            "accepted": False,
            "reason": "asr_no_text_detected",
            "provider": runtime_config.asrProvider,
            "model": runtime_config.asrModel,
            "degraded": True,
        }
    time_stamps = getattr(first, "time_stamps", None)
    segments = _asr_segments_from_result(text, time_stamps)
    return {
        "accepted": True,
        "reason": "ok",
        "text": text,
        "segments": segments,
        "provider": runtime_config.asrProvider,
        "model": runtime_config.asrModel,
        "degraded": False,
    }


@app.post("/ocr/extract")
def ocr_extract(payload: OcrExtractRequest) -> dict:
    features = _feature_status()
    if not features["ocr"]["ready"]:
        return {
            "accepted": False,
            "reason": "ocr_model_not_ready",
            "provider": runtime_config.ocrProvider,
            "model": runtime_config.ocrModel,
            "degraded": True,
        }
    source = Path(payload.path).resolve()
    if not source.exists() or not source.is_file():
        return {"accepted": False, "reason": "image_not_found"}

    try:
        import pytesseract
        from PIL import Image
    except Exception:
        return {"accepted": False, "reason": "ocr_dependencies_missing"}
    try:
        text = pytesseract.image_to_string(Image.open(source)).strip()
    except pytesseract.TesseractNotFoundError:
        return {"accepted": False, "reason": "tesseract_not_installed"}
    except Exception:
        return {"accepted": False, "reason": "ocr_failed"}
    if not text:
        return {"accepted": False, "reason": "ocr_no_text_detected"}
    return {
        "accepted": True,
        "reason": "ok",
        "text": text,
        "ocrMode": "image_ocr",
        "provider": runtime_config.ocrProvider,
        "model": runtime_config.ocrModel,
        "degraded": False,
    }

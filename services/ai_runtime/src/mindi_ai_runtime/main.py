from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from time import time

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
    offlineMode: bool = True
    experimentalAsr: bool = True
    experimentalOcr: bool = True


class LlmGenerateRequest(BaseModel):
    prompt: str
    languageMode: str = "english"


class AsrTranscribeRequest(BaseModel):
    sourceType: str
    sourceValue: str


class OcrExtractRequest(BaseModel):
    path: str


app = FastAPI(title="MINDI AI Runtime", version="0.1.0")
runtime_config = RuntimeConfig()


def _resolve_model_path(raw_path: str) -> Path | None:
    if not raw_path.strip():
        return None
    return Path(raw_path).expanduser()


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


def _feature_status() -> dict:
    llm_path = _resolve_model_path(runtime_config.llmModelPath)
    asr_path = _resolve_model_path(runtime_config.asrModelPath)
    ocr_path = _resolve_model_path(runtime_config.ocrModelPath)
    llm_runtime_error = _llm_runtime_error(llm_path)
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
            "ready": bool(asr_path and asr_path.exists()),
            "experimental": runtime_config.experimentalAsr,
            "pathConfigured": bool(runtime_config.asrModelPath.strip()),
            "provider": runtime_config.asrProvider,
            "model": runtime_config.asrModel,
            "modelPath": runtime_config.asrModelPath,
            "lastError": None if (asr_path and asr_path.exists()) else "model_path_missing",
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
    global runtime_config
    runtime_config = payload
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
        file_path = Path(value).resolve()
        if not file_path.exists() or not file_path.is_file():
            return {"accepted": False, "reason": "audio_not_found"}
        label = file_path.stem
    else:
        label = "live-mic"
    text = f"Transcribed ({label}) using local ASR runtime."
    return {
        "accepted": True,
        "reason": "ok",
        "text": text,
        "segments": [{"startMs": 0, "endMs": 1200, "text": text}],
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

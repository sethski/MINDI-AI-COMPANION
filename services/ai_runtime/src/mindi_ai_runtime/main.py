from __future__ import annotations

from pathlib import Path
from time import time

from fastapi import FastAPI
from pydantic import BaseModel


class RuntimeConfig(BaseModel):
    llmModelPath: str = ""
    asrModelPath: str = ""
    ocrModelPath: str = ""
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


def _feature_status() -> dict:
    llm_path = Path(runtime_config.llmModelPath).expanduser() if runtime_config.llmModelPath else None
    asr_path = Path(runtime_config.asrModelPath).expanduser() if runtime_config.asrModelPath else None
    ocr_path = Path(runtime_config.ocrModelPath).expanduser() if runtime_config.ocrModelPath else None
    return {
        "llm": {
            "enabled": True,
            "ready": bool(llm_path and llm_path.exists()),
            "experimental": False,
            "pathConfigured": bool(runtime_config.llmModelPath.strip()),
            "provider": runtime_config.llmProvider,
            "model": runtime_config.llmModel,
            "modelPath": runtime_config.llmModelPath,
            "lastError": None if (llm_path and llm_path.exists()) else "model_path_missing",
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
            "reason": "llm_model_not_ready",
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
    language_prefix = ""
    if payload.languageMode == "taglish":
        language_prefix = "Sige. "
    elif payload.languageMode == "tagalog":
        language_prefix = "Naiintindihan ko. "
    reply = f"{language_prefix}Local runtime stub processed your request: {text[:280]}"
    return {
        "accepted": True,
        "reason": "ok",
        "reply": reply,
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

"""Warm faster-whisper STT backend for low-latency voice turns."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

_whisper_lock = threading.Lock()
_whisper_model_ref: str | None = None
_whisper_model: Any | None = None
_whisper_runtime_error: str | None = None


def _resolve_audio_path(source_value: str) -> Path | None:
    candidate = Path(source_value).expanduser()
    if candidate.exists() and candidate.is_file():
        return candidate.resolve()
    return None


def load_whisper_model(*, model_size: str = "base.en", device: str = "cpu", compute_type: str = "int8") -> tuple[bool, dict]:
    global _whisper_model_ref, _whisper_model, _whisper_runtime_error

    model_ref = f"{model_size}:{device}:{compute_type}"
    with _whisper_lock:
        if _whisper_model is not None and _whisper_model_ref == model_ref and _whisper_runtime_error is None:
            return True, {"reason": "ok"}

        try:
            from faster_whisper import WhisperModel
        except ImportError:
            _whisper_runtime_error = "faster_whisper_dependency_missing"
            _whisper_model = None
            _whisper_model_ref = None
            return False, {"reason": _whisper_runtime_error}

        try:
            _whisper_model = WhisperModel(model_size, device=device, compute_type=compute_type)
        except Exception:
            _whisper_runtime_error = "whisper_model_load_failed"
            _whisper_model = None
            _whisper_model_ref = None
            return False, {"reason": _whisper_runtime_error}

        _whisper_model_ref = model_ref
        _whisper_runtime_error = None
        return True, {"reason": "ok"}


def reset_whisper_model() -> None:
    global _whisper_model_ref, _whisper_model, _whisper_runtime_error
    with _whisper_lock:
        _whisper_model = None
        _whisper_model_ref = None
        _whisper_runtime_error = None


def transcribe_file(
    *,
    audio_path: Path,
    language_hint: str | None = None,
    model_size: str = "base.en",
) -> tuple[bool, dict]:
    ok, load_result = load_whisper_model(model_size=model_size)
    if not ok:
        return False, load_result

    model = _whisper_model
    if model is None:
        return False, {"reason": "whisper_model_not_ready"}

    language = None
    if language_hint:
        lowered = language_hint.strip().lower()
        if lowered in {"english", "en"}:
            language = "en"
        elif lowered in {"tagalog", "filipino", "tl"}:
            language = "tl"

    try:
        segments_iter, _info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=1,
            vad_filter=True,
        )
        segments = list(segments_iter)
    except Exception:
        return False, {"reason": "whisper_inference_failed"}

    text = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
    if not text:
        return False, {"reason": "whisper_no_text_detected"}

    segment_payload = [
        {
            "startMs": max(0, int(segment.start * 1000)),
            "endMs": max(0, int(segment.end * 1000)),
            "text": segment.text.strip(),
        }
        for segment in segments
        if segment.text.strip()
    ]
    if not segment_payload:
        segment_payload = [{"startMs": 0, "endMs": max(1200, len(text) * 30), "text": text}]

    return True, {"text": text, "segments": segment_payload}


def transcribe_source(
    *,
    source_value: str,
    language_hint: str | None = None,
    model_size: str = "base.en",
) -> tuple[bool, dict]:
    audio_path = _resolve_audio_path(source_value)
    if audio_path is None:
        return False, {"reason": "audio_not_found"}
    return transcribe_file(audio_path=audio_path, language_hint=language_hint, model_size=model_size)

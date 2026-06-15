"""ASR transcription, TTS synthesis, and microphone payload handling."""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from .store import RuntimeStore

from .schemas import (
    AsrSegment,
    AsrTranscribeRequest,
    AsrTranscribeResponse,
    TtsSynthesizeRequest,
    TtsSynthesizeResponse,
)

_TTS_MAX_CHARS = 800


class VoiceService:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    def _persist_mic_payload(self, payload: str) -> str | None:
        encoded = payload
        if payload.startswith("data:"):
            _, _, encoded = payload.partition(",")
        elif payload.startswith("base64:"):
            encoded = payload.removeprefix("base64:")
        try:
            raw = base64.b64decode(encoded.strip(), validate=False)
        except (binascii.Error, ValueError):
            return None
        temp_dir = Path("data") / "inbox" / "orb-captures"
        temp_dir.mkdir(parents=True, exist_ok=True)
        file_path = temp_dir / f"capture-{uuid4()}.webm"
        file_path.write_bytes(raw)
        return str(file_path.resolve())

    def transcribe_audio(self, request: AsrTranscribeRequest) -> AsrTranscribeResponse:
        source_value = (request.sourceValue or "").strip()
        if not source_value:
            return AsrTranscribeResponse(accepted=False, reason="source_value_required")
        if request.sourceType == "file":
            source = Path(source_value).resolve()
            if not source.exists() or not source.is_file():
                return AsrTranscribeResponse(accepted=False, reason="audio_not_found")
            if not self._store._is_path_allowed(source):
                return AsrTranscribeResponse(accepted=False, reason="audio_file_not_allowed")
            source_value = str(source)
        elif request.sourceType == "mic":
            if source_value.startswith("data:") or source_value.startswith("base64:"):
                persisted = self._persist_mic_payload(source_value)
                if persisted is None:
                    return AsrTranscribeResponse(accepted=False, reason="mic_payload_invalid")
                source_value = persisted
            else:
                source = Path(source_value).resolve()
                if source.exists() and source.is_file():
                    source_value = str(source)

        payload = self._store.ai_runtime.transcribe(
            source_type=request.sourceType,
            source_value=source_value,
            language_hint=request.languageHint,
            return_timestamps=request.returnTimestamps,
        )
        segments_payload = payload.get("segments") or []
        segments: list[AsrSegment] = []
        for item in segments_payload:
            if not isinstance(item, dict):
                continue
            segments.append(
                AsrSegment(
                    startMs=max(0, int(item.get("startMs", 0))),
                    endMs=max(0, int(item.get("endMs", 0))),
                    text=str(item.get("text", "")),
                )
            )
        return AsrTranscribeResponse(
            accepted=bool(payload.get("accepted", False)),
            reason=str(payload.get("reason", "runtime_unavailable")),
            text=payload.get("text"),
            segments=segments,
            provider=payload.get("provider"),
            model=payload.get("model"),
            degraded=bool(payload.get("degraded", not bool(payload.get("accepted", False)))),
            fallbackReason=payload.get("fallbackReason") or (
                str(payload.get("reason")) if not bool(payload.get("accepted", False)) else None
            ),
        )

    def synthesize_speech(self, request: TtsSynthesizeRequest) -> TtsSynthesizeResponse:
        text = (request.text or "").strip()
        if not text:
            return TtsSynthesizeResponse(accepted=False, reason="text_required", degraded=True)
        if len(text) > _TTS_MAX_CHARS:
            truncated = text[:_TTS_MAX_CHARS].rsplit(" ", 1)[0]
            text = truncated + "\u2026"
        payload = self._store.ai_runtime.synthesize_tts(text=text)
        return TtsSynthesizeResponse(
            accepted=bool(payload.get("accepted", False)),
            reason=str(payload.get("reason", "runtime_unavailable")),
            audioDataUrl=payload.get("audioDataUrl"),
            provider=payload.get("provider"),
            model=payload.get("model"),
            degraded=bool(payload.get("degraded", not bool(payload.get("accepted", False)))),
            latencyMs=payload.get("latencyMs"),
        )

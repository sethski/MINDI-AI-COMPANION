"""Notes, document import, OCR, screen perception, and auto-indexer."""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING
from uuid import uuid4

from PIL import Image

if TYPE_CHECKING:
    from .store import RuntimeStore

from .memory_db import ALLOWED_DOCUMENT_SUFFIXES, MemoryDB
from .ocr_service import OCR_IMAGE_SUFFIXES, extract_text_for_ocr
from .privacy_utils import redact_sensitive_text
from .schemas import (
    ActionLogItem,
    ActionTier,
    AutoIndexStatus,
    CreateMemoryNoteRequest,
    DocumentImportRequest,
    DocumentImportResponse,
    DocumentSearchResponse,
    MemoryDocumentChunk,
    MemoryNote,
    MemorySearchResponse,
    OcrImportRequest,
    OcrImportResponse,
    PerceptionAnalyzeRequest,
    PerceptionAnalyzeResponse,
    PerceptionSnapshot,
    PerceptionSnapshotSearchResponse,
    PerceptionUiBlock,
    now_iso,
)

PERCEPTION_SCREEN_SUBJECT = "perception.screen.capture"


# ---------------------------------------------------------------------------
# Pure geometry and retrieval helpers
# ---------------------------------------------------------------------------

def _box_intersection_area(
    a: tuple[int, int, int, int],
    b: tuple[int, int, int, int],
) -> int:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0, ix2 - ix1 + 1)
    ih = max(0, iy2 - iy1 + 1)
    return iw * ih


def _merge_overlapping_boxes(
    boxes: list[tuple[int, int, int, int, float]],
) -> list[tuple[int, int, int, int, float]]:
    if not boxes:
        return []
    merged = sorted(boxes, key=lambda item: (item[1], item[0]))
    changed = True
    while changed:
        changed = False
        next_boxes: list[tuple[int, int, int, int, float]] = []
        while merged:
            current = merged.pop(0)
            cx1, cy1, cx2, cy2, cscore = current
            keep = True
            for index, other in enumerate(merged):
                ox1, oy1, ox2, oy2, oscore = other
                intersection = _box_intersection_area(
                    (cx1, cy1, cx2, cy2),
                    (ox1, oy1, ox2, oy2),
                )
                if intersection <= 0:
                    continue
                c_area = (cx2 - cx1 + 1) * (cy2 - cy1 + 1)
                o_area = (ox2 - ox1 + 1) * (oy2 - oy1 + 1)
                overlap_ratio = intersection / max(1, min(c_area, o_area))
                if overlap_ratio < 0.35:
                    continue
                nx1 = min(cx1, ox1)
                ny1 = min(cy1, oy1)
                nx2 = max(cx2, ox2)
                ny2 = max(cy2, oy2)
                nscore = max(cscore, oscore)
                merged.pop(index)
                merged.insert(0, (nx1, ny1, nx2, ny2, nscore))
                keep = False
                changed = True
                break
            if keep:
                next_boxes.append(current)
        merged = next_boxes
    return merged


def _find_runs(active: list[bool], min_size: int) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(active):
        if value and start is None:
            start = index
        elif not value and start is not None:
            if index - start >= min_size:
                runs.append((start, index - 1))
            start = None
    if start is not None and len(active) - start >= min_size:
        runs.append((start, len(active) - 1))
    return runs


def document_retrieval_mode(items: list[MemoryDocumentChunk]) -> str:
    if not items:
        return "none"
    modes = {item.retrievalMode for item in items}
    if "hybrid" in modes or "semantic" in modes:
        return "hybrid"
    return "keyword"


def document_retrieval_confidence(items: list[MemoryDocumentChunk]) -> float:
    if not items:
        return 0.0
    return round(max(0.0, min(1.0, items[0].score / 6.0)), 3)


def should_attach_document_rag(text: str, items: list[MemoryDocumentChunk]) -> bool:
    if not items:
        return False
    confidence = document_retrieval_confidence(items)
    trimmed = text.strip()
    if not trimmed:
        return False
    word_count = len(trimmed.split())
    if len(trimmed) < 36 and word_count <= 5 and confidence < 0.75:
        return False
    return confidence >= 0.4


# ---------------------------------------------------------------------------
# MemoryService
# ---------------------------------------------------------------------------

class MemoryService:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    # --- Notes ---

    def add_memory_note(self, request: CreateMemoryNoteRequest) -> MemoryNote:
        if request.idempotencyKey:
            cached = self._store._idempotency_cache.get(request.idempotencyKey)
            if cached is not None:
                return cached
        note = self._store.memory_db.add_note(request)
        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"memory_note:create:{note.title}",
                tier=ActionTier.reversible,
                result="allowed",
                reason="stored_locally",
                createdAt=now_iso(),
            ),
        )
        if request.idempotencyKey:
            self._store._idempotency_cache.set(request.idempotencyKey, note)
        return note

    def list_memory_notes(self, limit: int = 50) -> list[MemoryNote]:
        return self._store.memory_db.list_notes(limit=limit)

    def search_memory(self, query: str, limit: int = 50) -> MemorySearchResponse:
        return MemorySearchResponse(
            query=query,
            items=self._store.memory_db.search_notes(query, limit=limit),
        )

    # --- Perception snapshots ---

    def list_perception_snapshots(self, limit: int = 20) -> list[PerceptionSnapshot]:
        return self._store.memory_db.list_perception_snapshots(limit=limit)

    def search_perception_snapshots(
        self, query: str, limit: int = 20
    ) -> PerceptionSnapshotSearchResponse:
        return PerceptionSnapshotSearchResponse(
            query=query,
            items=self._store.memory_db.search_perception_snapshots(query=query, limit=limit),
        )

    # --- Documents ---

    def import_document(self, request: DocumentImportRequest) -> DocumentImportResponse:
        source = Path(request.path).resolve()
        if not source.exists() or not source.is_file():
            return DocumentImportResponse(accepted=False, reason="document_not_found")
        if not self._store._is_path_allowed(source):
            return DocumentImportResponse(accepted=False, reason="folder_not_allowed")
        try:
            document = self._store.memory_db.import_document(source)
        except ValueError as exc:
            return DocumentImportResponse(accepted=False, reason=str(exc))
        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"document_import:{source.name}",
                tier=ActionTier.reversible,
                result="allowed",
                reason="document_indexed",
                createdAt=now_iso(),
            ),
        )
        return DocumentImportResponse(accepted=True, reason="indexed", document=document)

    def search_documents(self, query: str, limit: int = 20) -> DocumentSearchResponse:
        items = self._store.memory_db.search_documents(query=query, limit=limit)
        return DocumentSearchResponse(
            query=query,
            items=items,
            retrievalMode=document_retrieval_mode(items),
            confidence=document_retrieval_confidence(items),
        )

    # --- OCR import ---

    def import_ocr_document(self, request: OcrImportRequest) -> OcrImportResponse:
        source = Path(request.path).resolve()
        if not source.exists() or not source.is_file():
            return OcrImportResponse(accepted=False, reason="document_not_found")
        if not self._store._is_path_allowed(source):
            return OcrImportResponse(accepted=False, reason="folder_not_allowed")

        degraded = False
        fallback_reason: str | None = None
        ocr_backend = "huggingface_local"
        ocr_model = "zai-org/GLM-OCR"
        try:
            runtime_ocr = self._store.ai_runtime.extract_ocr(path=source)
            if runtime_ocr.get("accepted"):
                extracted_text = str(runtime_ocr.get("text") or "").strip()
                extraction_mode = str(runtime_ocr.get("ocrMode") or "image_ocr")
                ocr_backend = str(runtime_ocr.get("provider") or ocr_backend)
                ocr_model = str(runtime_ocr.get("model") or ocr_model)
                if not extracted_text:
                    raise ValueError("ocr_no_text_detected")
            else:
                extracted_text, extraction_mode = extract_text_for_ocr(source)
                degraded = True
                fallback_reason = str(runtime_ocr.get("reason") or "runtime_unavailable")
                ocr_backend = "pytesseract_fallback"
                ocr_model = "local_tesseract"
            document = self._store.memory_db.import_extracted_document(
                source_path=source,
                text=extracted_text,
                title=source.name,
            )
        except ValueError as exc:
            return OcrImportResponse(accepted=False, reason=str(exc))

        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"ocr_import:{source.name}",
                tier=ActionTier.reversible,
                result="allowed",
                reason=extraction_mode,
                createdAt=now_iso(),
            ),
        )
        return OcrImportResponse(
            accepted=True,
            reason=extraction_mode,
            document=document,
            ocrBackend=ocr_backend,
            ocrModel=ocr_model,
            degraded=degraded,
            fallbackReason=fallback_reason,
        )

    # --- Screen analysis (perception) ---

    def _extract_ui_blocks_from_image(
        self,
        source: Path,
        max_blocks: int,
    ) -> tuple[int, int, list[PerceptionUiBlock]]:
        with Image.open(source) as image:
            grayscale = image.convert("L")
            width, height = grayscale.size
            scale = max(1.0, max(width, height) / 480.0)
            sample_width = max(1, int(width / scale))
            sample_height = max(1, int(height / scale))
            sampled = grayscale.resize((sample_width, sample_height))

            pixels = sampled.load()
            row_active: list[bool] = []
            for y in range(sample_height):
                active_count = 0
                for x in range(sample_width):
                    if pixels[x, y] < 232:
                        active_count += 1
                row_active.append(active_count >= max(2, int(sample_width * 0.03)))

            row_runs = _find_runs(row_active, min_size=max(2, int(sample_height * 0.01)))
            boxes: list[tuple[int, int, int, int, float]] = []
            for y0, y1 in row_runs:
                column_active: list[bool] = []
                run_height = y1 - y0 + 1
                for x in range(sample_width):
                    active_count = 0
                    for y in range(y0, y1 + 1):
                        if pixels[x, y] < 232:
                            active_count += 1
                    column_active.append(active_count >= max(1, int(run_height * 0.08)))

                col_runs = _find_runs(column_active, min_size=max(3, int(sample_width * 0.02)))
                for x0, x1 in col_runs:
                    sx1 = int(x0 * scale)
                    sy1 = int(y0 * scale)
                    sx2 = min(width - 1, int((x1 + 1) * scale) - 1)
                    sy2 = min(height - 1, int((y1 + 1) * scale) - 1)
                    area = (sx2 - sx1 + 1) * (sy2 - sy1 + 1)
                    if area < max(200, int(width * height * 0.0003)):
                        continue
                    density = min(
                        1.0,
                        ((x1 - x0 + 1) * (y1 - y0 + 1))
                        / max(1.0, float(sample_width * sample_height)),
                    )
                    boxes.append((sx1, sy1, sx2, sy2, max(0.05, density * 30)))

            merged = _merge_overlapping_boxes(boxes)
            merged = sorted(
                merged,
                key=lambda item: ((item[2] - item[0] + 1) * (item[3] - item[1] + 1)),
                reverse=True,
            )[:max_blocks]
            ui_blocks = [
                PerceptionUiBlock(
                    x=x1,
                    y=y1,
                    width=max(1, x2 - x1 + 1),
                    height=max(1, y2 - y1 + 1),
                    kind="text_region",
                    confidence=round(min(0.99, score), 3),
                    textSnippet=None,
                )
                for x1, y1, x2, y2, score in merged
            ]
        return width, height, ui_blocks

    def analyze_screen(self, request: PerceptionAnalyzeRequest) -> PerceptionAnalyzeResponse:
        if not self._store._is_action_allowed(PERCEPTION_SCREEN_SUBJECT):
            decision = self._store._resolve_action_permission_decision(PERCEPTION_SCREEN_SUBJECT)
            reason = "screen_permission_denied" if decision == "deny" else "screen_permission_required"
            self._store.logs.insert(
                0,
                ActionLogItem(
                    id=str(uuid4()),
                    intent="perception_screen_analyze",
                    tier=ActionTier.risky,
                    result="blocked",
                    reason=reason,
                    createdAt=now_iso(),
                ),
            )
            return PerceptionAnalyzeResponse(accepted=False, reason=reason)

        source: Path | None = None
        remove_source_after = False

        image_data_url = (request.imageDataUrl or "").strip()
        path_value = (request.path or "").strip()
        if image_data_url:
            if not image_data_url.startswith("data:image/") or ";base64," not in image_data_url:
                return PerceptionAnalyzeResponse(accepted=False, reason="invalid_image_data_url")
            header, encoded = image_data_url.split(",", 1)
            mime_part = header[5:].split(";", 1)[0].lower()
            suffix = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/webp": ".webp",
                "image/bmp": ".bmp",
                "image/tiff": ".tiff",
            }.get(mime_part)
            if suffix is None:
                return PerceptionAnalyzeResponse(accepted=False, reason="unsupported_file_type")
            try:
                image_bytes = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                return PerceptionAnalyzeResponse(accepted=False, reason="invalid_image_data_url")
            if not image_bytes:
                return PerceptionAnalyzeResponse(accepted=False, reason="invalid_image_data_url")
            captures_dir = Path("data/runtime/perception").resolve()
            captures_dir.mkdir(parents=True, exist_ok=True)
            source = captures_dir / f"capture-{uuid4()}{suffix}"
            source.write_bytes(image_bytes)
            remove_source_after = True
        elif path_value:
            source = Path(path_value).resolve()
            if not source.exists() or not source.is_file():
                return PerceptionAnalyzeResponse(accepted=False, reason="image_not_found")
            if source.suffix.lower() not in OCR_IMAGE_SUFFIXES:
                return PerceptionAnalyzeResponse(accepted=False, reason="unsupported_file_type")
            if not self._store._is_path_allowed(source):
                return PerceptionAnalyzeResponse(accepted=False, reason="folder_not_allowed")
        else:
            return PerceptionAnalyzeResponse(accepted=False, reason="path_or_image_required")

        try:
            width, height, blocks = self._extract_ui_blocks_from_image(
                source=source,
                max_blocks=request.maxBlocks,
            )
        except Exception:
            if remove_source_after:
                try:
                    source.unlink(missing_ok=True)
                except Exception:
                    pass
            return PerceptionAnalyzeResponse(accepted=False, reason="image_parse_failed")

        text: str | None = None
        ocr_mode: str | None = None
        ocr_error: str | None = None
        ocr_backend: str | None = None
        ocr_model: str | None = None
        degraded = False
        fallback_reason: str | None = None
        if request.includeOcr:
            try:
                runtime_ocr = self._store.ai_runtime.extract_ocr(path=source)
                if runtime_ocr.get("accepted"):
                    text = str(runtime_ocr.get("text") or "").strip() or None
                    ocr_mode = runtime_ocr.get("ocrMode")
                    ocr_backend = runtime_ocr.get("provider")
                    ocr_model = runtime_ocr.get("model")
                    if text is None:
                        ocr_error = "ocr_no_text_detected"
                else:
                    text, ocr_mode = extract_text_for_ocr(source)
                    degraded = True
                    fallback_reason = str(runtime_ocr.get("reason") or "runtime_unavailable")
                    ocr_backend = "pytesseract_fallback"
                    ocr_model = "local_tesseract"
            except ValueError as exc:
                ocr_error = str(exc)

        reason = "ok"
        if request.includeOcr and ocr_error is not None:
            reason = "ocr_unavailable_blocks_extracted"

        storage_redacted = False
        redaction_count = 0
        storage_text = text
        if self._store.privacy_redaction_enabled and text:
            storage_text, redaction_count = redact_sensitive_text(text)
            storage_redacted = redaction_count > 0

        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"perception_screen_analyze:{source.name}",
                tier=ActionTier.reversible,
                result="allowed",
                reason=f"blocks:{len(blocks)}",
                createdAt=now_iso(),
            ),
        )

        snapshot = self._store.memory_db.add_perception_snapshot(
            source_path=str(source),
            reason=reason,
            ocr_mode=ocr_mode,
            text=storage_text,
            block_count=len(blocks),
            image_width=width,
            image_height=height,
        )

        response = PerceptionAnalyzeResponse(
            accepted=True,
            reason=reason,
            snapshotId=snapshot.id,
            storageRedacted=storage_redacted,
            redactionCount=redaction_count,
            path=str(source),
            imageWidth=width,
            imageHeight=height,
            ocrMode=ocr_mode,
            ocrError=ocr_error,
            ocrBackend=ocr_backend,
            ocrModel=ocr_model,
            degraded=degraded,
            fallbackReason=fallback_reason,
            text=text,
            textLength=len(text or ""),
            blocks=blocks,
        )
        if remove_source_after:
            try:
                source.unlink(missing_ok=True)
            except Exception:
                pass
        return response

    # --- Auto-indexer ---

    def watched_paths(self) -> list[Path]:
        defaults = [Path("data/inbox"), Path("data/notes"), Path("data/screenshots")]
        folder_grants = [
            Path(grant.subject)
            for grant in self._store.permission_grants
            if grant.scope == "folder" and grant.decision == "allow"
        ]
        seen: set[str] = set()
        resolved_dirs: list[Path] = []
        for candidate in defaults + folder_grants:
            path = candidate.resolve()
            if not path.exists() or not path.is_dir():
                continue
            key = str(path).lower()
            if key in seen:
                continue
            seen.add(key)
            resolved_dirs.append(path)
        return resolved_dirs

    def auto_index_status(self) -> AutoIndexStatus:
        paths = [str(p) for p in self.watched_paths()]
        return AutoIndexStatus(
            running=self._store.auto_index_thread is not None and self._store.auto_index_thread.is_alive(),
            watchedPaths=paths,
            lastScanAt=self._store.auto_index_last_scan,
            indexedTotal=self._store.auto_index_indexed_total,
            indexedLastRun=self._store.auto_index_indexed_last_run,
            lastError=self._store.auto_index_last_error,
        )

    def start_auto_indexer(self) -> None:
        if self._store.auto_index_thread is not None and self._store.auto_index_thread.is_alive():
            return
        self._store.auto_index_stop.clear()
        self._store.auto_index_thread = Thread(target=self._auto_index_loop, daemon=True)
        self._store.auto_index_thread.start()

    def _auto_index_loop(self) -> None:
        while not self._store.auto_index_stop.is_set():
            self.auto_index_scan_once()
            self._store.auto_index_stop.wait(30)

    def auto_index_scan_once(self) -> AutoIndexStatus:
        indexed_now = 0
        self._store.auto_index_last_error = None
        supported_suffixes = ALLOWED_DOCUMENT_SUFFIXES | OCR_IMAGE_SUFFIXES | {".pdf"}

        for directory in self.watched_paths():
            for file_path in directory.rglob("*"):
                if not file_path.is_file():
                    continue
                if file_path.suffix.lower() not in supported_suffixes:
                    continue
                try:
                    mtime_ns = file_path.stat().st_mtime_ns
                except OSError:
                    continue
                file_key = str(file_path.resolve())
                if self._store.auto_index_seen_mtime.get(file_key) == mtime_ns:
                    continue

                try:
                    if file_path.suffix.lower() in ALLOWED_DOCUMENT_SUFFIXES:
                        self._store.memory_db.import_document(file_path)
                    else:
                        extracted_text, _ = extract_text_for_ocr(file_path)
                        self._store.memory_db.import_extracted_document(
                            source_path=file_path,
                            text=extracted_text,
                            title=file_path.name,
                        )
                    self._store.auto_index_seen_mtime[file_key] = mtime_ns
                    indexed_now += 1
                except ValueError as exc:
                    self._store.auto_index_seen_mtime[file_key] = mtime_ns
                    self._store.auto_index_last_error = str(exc)

        self._store.auto_index_last_scan = now_iso()
        self._store.auto_index_indexed_last_run = indexed_now
        self._store.auto_index_indexed_total += indexed_now
        return self.auto_index_status()

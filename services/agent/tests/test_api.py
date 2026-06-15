from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone
from pathlib import Path
import base64
import io
import subprocess
from unittest.mock import patch
from uuid import uuid4
from PIL import Image, ImageDraw

from mindi_agent.main import app, store

client = TestClient(app)


class _MockUrlResponse:
    def __init__(self, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        self._body = body
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            return self._body
        return self._body[:size]


def _reset_intelligence_state_for_adaptation_tests() -> None:
    store.intelligence_language_mode = "english"
    store.intelligence_slang_enabled = False
    store.intelligence_slang_terms = []
    store.intelligence_tuning_preset = "safe"
    store.intelligence_tuning_verbosity = "balanced"
    store.intelligence_tuning_custom_risky_terms = []
    store.intelligence_tuning_pending_preset = None
    store.intelligence_tuning_pending_verbosity = None
    store.intelligence_tuning_pending_custom_risky_terms = []
    store.intelligence_tuning_pending_version = None
    store.intelligence_tuning_last_active_eval_score = None
    store.intelligence_tuning_last_pending_eval_score = None
    store.intelligence_tuning_last_pending_eval_version = None
    store.intelligence_eval_history = []
    store.intelligence_learning_sources = {}
    store.intelligence_learning_candidates = []
    store.intelligence_learning_candidate_version = None
    store.intelligence_learning_last_run_at = None
    store.intelligence_learning_last_eval_score = None
    store.intelligence_learning_last_eval_version = None
    store.intelligence_learning_last_eval_signature = None
    store.intelligence_learning_last_applied_at = None
    if hasattr(store, "intelligence_adaptation_last_export_at"):
        store.intelligence_adaptation_last_export_at = None
    if hasattr(store, "intelligence_adaptation_last_export_path"):
        store.intelligence_adaptation_last_export_path = None


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_safe_prompt_allowed() -> None:
    response = client.post("/assistant/respond", json={"text": "summarize my notes"})
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["allowed"] is True
    assert body["status"] == "ready"


def test_risky_prompt_blocked() -> None:
    response = client.post("/assistant/respond", json={"text": "delete all files"})
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["allowed"] is False
    assert body["decision"]["requiresUnlock"] is True


def test_permissions_roundtrip() -> None:
    create = client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": "data/inbox", "decision": "allow"},
    )
    assert create.status_code == 200
    listed = client.get("/control/permissions")
    assert listed.status_code == 200
    assert any(item["subject"] == "data/inbox" for item in listed.json())


def test_file_organize_preview_and_apply(tmp_path: Path) -> None:
    source = tmp_path / "inbox"
    target = tmp_path / "sorted"
    source.mkdir(parents=True, exist_ok=True)
    (source / "a.txt").write_text("hello", encoding="utf-8")
    (source / "b.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )

    preview = client.post(
        "/control/file-organize",
        json={"sourceDir": str(source), "targetDir": str(target), "mode": "preview"},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["accepted"] is True
    assert len(preview_body["items"]) == 2
    assert (source / "a.txt").exists()

    apply = client.post(
        "/control/file-organize",
        json={"sourceDir": str(source), "targetDir": str(target), "mode": "apply"},
    )
    assert apply.status_code == 200
    apply_body = apply.json()
    assert apply_body["accepted"] is True
    assert apply_body["movedCount"] == 2
    assert not (source / "a.txt").exists()
    assert (target / "documents" / "a.txt").exists()


def test_app_control_requires_allowlist_and_confirmation() -> None:
    denied = client.post(
        "/control/apps/action",
        json={"action": "open", "appId": "calc.exe", "confirm": True},
    )
    assert denied.status_code == 200
    denied_body = denied.json()
    assert denied_body["accepted"] is False
    assert denied_body["reason"] == "app_not_allowlisted"

    client.post(
        "/control/permissions",
        json={"scope": "app", "subject": "calc.exe", "decision": "allow"},
    )
    close_needs_confirm = client.post(
        "/control/apps/action",
        json={"action": "close", "appId": "calc.exe", "confirm": False},
    )
    assert close_needs_confirm.status_code == 200
    close_body = close_needs_confirm.json()
    assert close_body["accepted"] is False
    assert close_body["requiresConfirmation"] is True


def test_app_control_open_and_close_success() -> None:
    client.post(
        "/control/permissions",
        json={"scope": "app", "subject": "calc.exe", "decision": "allow"},
    )

    with patch("mindi_agent.automation_service.subprocess.Popen") as mock_open:
        mock_open.return_value = None
        open_response = client.post(
            "/control/apps/action",
            json={"action": "open", "appId": "calc.exe", "confirm": True},
        )
        assert open_response.status_code == 200
        assert open_response.json()["accepted"] is True

    with patch("mindi_agent.automation_service.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        close_response = client.post(
            "/control/apps/action",
            json={"action": "close", "appId": "calc.exe", "confirm": True},
        )
        assert close_response.status_code == 200
        assert close_response.json()["accepted"] is True


def test_memory_note_create_and_search() -> None:
    create = client.post(
        "/memory/notes",
        json={"title": "Sprint Plan", "content": "Ship memory API", "tags": ["planning"]},
    )
    assert create.status_code == 200
    created = create.json()
    assert created["title"] == "Sprint Plan"

    listed = client.get("/memory/notes?limit=20")
    assert listed.status_code == 200
    assert any(item["id"] == created["id"] for item in listed.json())

    searched = client.get("/memory/search?query=memory")
    assert searched.status_code == 200
    body = searched.json()
    assert body["query"] == "memory"
    assert any(item["id"] == created["id"] for item in body["items"])


def test_document_import_and_search(tmp_path: Path) -> None:
    doc = tmp_path / "knowledge.md"
    marker = "doc-search-marker-6129"
    doc.write_text(f"MINDI local memory retrieval {marker} and chunk index", encoding="utf-8")

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )

    imported = client.post("/memory/documents/import", json={"path": str(doc)})
    assert imported.status_code == 200
    imported_body = imported.json()
    assert imported_body["accepted"] is True
    assert imported_body["document"]["chunkCount"] >= 1

    searched = client.get(f"/memory/documents/search?query={marker}")
    assert searched.status_code == 200
    items = searched.json()["items"]
    assert any(item["sourcePath"] == str(doc.resolve()) for item in items)


def test_document_search_uses_semantic_hybrid_retrieval(tmp_path: Path) -> None:
    doc = tmp_path / "file-helper.md"
    doc.write_text(
        "MINDI organizes folders safely, renames documents, and sorts downloads into clean categories.",
        encoding="utf-8",
    )

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )

    imported = client.post("/memory/documents/import", json={"path": str(doc)})
    assert imported.status_code == 200
    assert imported.json()["accepted"] is True

    searched = client.get("/memory/documents/search", params={"query": "arrange my messy files"})

    assert searched.status_code == 200
    body = searched.json()
    assert body["retrievalMode"] == "hybrid"
    assert body["confidence"] > 0
    assert any(
        item["sourcePath"] == str(doc.resolve()) and item["retrievalMode"] in {"semantic", "hybrid"}
        for item in body["items"]
    )


def test_assistant_response_includes_rag_citations(tmp_path: Path) -> None:
    doc = tmp_path / "assistant-file-help.md"
    doc.write_text(
        "MINDI can organize folders, rename files, sort downloads, and keep destructive actions confirmation gated.",
        encoding="utf-8",
    )

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )

    imported = client.post("/memory/documents/import", json={"path": str(doc)})
    assert imported.status_code == 200
    assert imported.json()["accepted"] is True

    captured: dict[str, str] = {}

    def fake_generate_reply(*, prompt: str, language_mode: str):
        captured["prompt"] = prompt
        return {
            "accepted": True,
            "response": "MINDI can organize and sort your files while requiring confirmation for risky actions.",
            "provider": "local",
            "model": "test-model",
        }

    original = store.ai_runtime.generate_reply
    store.ai_runtime.generate_reply = fake_generate_reply
    try:
        response = client.post(
            "/assistant/respond",
            json={"text": "How can MINDI arrange my messy files?"},
        )
    finally:
        store.ai_runtime.generate_reply = original

    assert response.status_code == 200
    body = response.json()
    assert body["citations"]
    assert body["citations"][0]["sourcePath"] == str(doc.resolve())
    assert body["rag"]["retrievalMode"] == "hybrid"
    assert "assistant-file-help.md" in captured["prompt"]


def test_document_import_rejects_unsupported_type(tmp_path: Path) -> None:
    doc = tmp_path / "payload.exe"
    doc.write_bytes(b"MZ")

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )

    imported = client.post("/memory/documents/import", json={"path": str(doc)})
    assert imported.status_code == 200
    body = imported.json()
    assert body["accepted"] is False
    assert body["reason"] == "unsupported_file_type"


def test_ocr_import_success_with_mock(tmp_path: Path) -> None:
    image = tmp_path / "scan.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )

    with patch("mindi_agent.memory_service.extract_text_for_ocr") as mock_ocr:
        mock_ocr.return_value = ("invoice total 4200", "image_ocr")
        response = client.post("/memory/ocr/import", json={"path": str(image)})
        assert response.status_code == 200
        body = response.json()
        assert body["accepted"] is True
        assert body["reason"] == "image_ocr"
        assert body["document"]["chunkCount"] >= 1


def test_ocr_import_missing_file() -> None:
    response = client.post("/memory/ocr/import", json={"path": "missing/file.png"})
    assert response.status_code == 200
    assert response.json()["accepted"] is False


def test_ocr_import_prefers_runtime_backend_when_available(tmp_path: Path) -> None:
    image = tmp_path / "runtime-scan.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )

    with patch.object(
        store.ai_runtime,
        "extract_ocr",
        return_value={
            "accepted": True,
            "text": "runtime ocr text",
            "ocrMode": "glm_ocr_markdown",
            "provider": "huggingface_local",
            "model": "zai-org/GLM-OCR",
            "degraded": False,
        },
    ):
        with patch("mindi_agent.memory_service.extract_text_for_ocr", side_effect=AssertionError("fallback should not run")):
            response = client.post("/memory/ocr/import", json={"path": str(image)})

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["reason"] == "glm_ocr_markdown"
    assert body["ocrBackend"] == "huggingface_local"
    assert body["ocrModel"] == "zai-org/GLM-OCR"
    assert body["degraded"] is False
    assert body["fallbackReason"] is None


def test_ocr_import_falls_back_with_explicit_runtime_reason(tmp_path: Path) -> None:
    image = tmp_path / "runtime-fallback.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )

    with patch.object(
        store.ai_runtime,
        "extract_ocr",
        return_value={
            "accepted": False,
            "reason": "ocr_model_not_ready",
            "provider": "huggingface_local",
            "model": "zai-org/GLM-OCR",
            "degraded": True,
        },
    ):
        with patch("mindi_agent.memory_service.extract_text_for_ocr") as mock_ocr:
            mock_ocr.return_value = ("fallback text", "image_ocr")
            response = client.post("/memory/ocr/import", json={"path": str(image)})

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["reason"] == "image_ocr"
    assert body["ocrBackend"] == "pytesseract_fallback"
    assert body["ocrModel"] == "local_tesseract"
    assert body["degraded"] is True
    assert body["fallbackReason"] == "ocr_model_not_ready"


def test_auto_index_scan_and_status(tmp_path: Path) -> None:
    doc = tmp_path / "watcher.md"
    marker = f"autoindex-marker-{uuid4()}"
    doc.write_text(f"MINDI {marker}", encoding="utf-8")

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )

    status_before = client.get("/memory/auto-index/status")
    assert status_before.status_code == 200
    assert "running" in status_before.json()

    scan = client.post("/memory/auto-index/scan")
    assert scan.status_code == 200

    searched = client.get(f"/memory/documents/search?query={marker}")
    assert searched.status_code == 200
    items = searched.json()["items"]
    assert any(item["sourcePath"] == str(doc.resolve()) for item in items)


def test_scheduler_generates_due_alerts() -> None:
    title = "scheduler-alert-task-5581"
    due_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")

    status_before = client.get("/ops/scheduler/status")
    assert status_before.status_code == 200
    alerts_before = status_before.json()["alertsTotal"]

    create_task = client.post("/tasks", json={"title": title, "dueAt": due_at})
    assert create_task.status_code == 200

    scan = client.post("/ops/scheduler/scan")
    assert scan.status_code == 200
    scan_body = scan.json()
    assert scan_body["trackedTasks"] >= 1

    status_after = client.get("/ops/scheduler/status")
    assert status_after.status_code == 200
    assert status_after.json()["alertsTotal"] >= alerts_before

    hub = client.get("/hub/snapshot")
    assert hub.status_code == 200
    alert_titles = [item["title"] for item in hub.json()["alerts"]]
    assert any(title in alert for alert in alert_titles)


def test_scheduler_next_run_endpoint() -> None:
    due_at = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    response = client.post(
        "/ops/scheduler/next-run",
        json={"dueAt": due_at, "recurrence": "daily"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["nextRunAt"] is not None


def test_update_task_status_roundtrip() -> None:
    created = client.post("/tasks", json={"title": "status-roundtrip-4512"})
    assert created.status_code == 200
    task = created.json()

    done = client.patch(f"/tasks/{task['id']}/status", json={"status": "done"})
    assert done.status_code == 200
    assert done.json()["status"] == "done"

    reopened = client.patch(f"/tasks/{task['id']}/status", json={"status": "todo"})
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "todo"


def test_update_task_fields_and_clear_due_recurrence() -> None:
    due_at = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    created = client.post(
        "/tasks",
        json={"title": "task-edit-source-8834", "dueAt": due_at, "recurrence": "weekly"},
    )
    assert created.status_code == 200
    task_id = created.json()["id"]

    updated = client.patch(
        f"/tasks/{task_id}",
        json={"title": "task-edit-target-8834", "dueAt": None, "recurrence": None, "status": "in_progress"},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["title"] == "task-edit-target-8834"
    assert body["dueAt"] is None
    assert body["recurrence"] is None
    assert body["status"] == "in_progress"


def test_delete_task_removes_task() -> None:
    created = client.post("/tasks", json={"title": "task-delete-1229"})
    assert created.status_code == 200
    task_id = created.json()["id"]

    deleted = client.delete(f"/tasks/{task_id}")
    assert deleted.status_code == 200
    assert deleted.json()["accepted"] is True
    assert deleted.json()["deletedId"] == task_id

    tasks = client.get("/tasks")
    assert tasks.status_code == 200
    assert not any(item["id"] == task_id for item in tasks.json())


def test_scheduler_skips_done_task_and_realerts_when_reopened() -> None:
    title = "scheduler-status-gate-9143"
    due_at = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    created = client.post("/tasks", json={"title": title, "dueAt": due_at})
    assert created.status_code == 200
    task_id = created.json()["id"]

    done = client.patch(f"/tasks/{task_id}/status", json={"status": "done"})
    assert done.status_code == 200

    status_before_done_scan = client.get("/ops/scheduler/status")
    assert status_before_done_scan.status_code == 200
    alerts_before_done_scan = status_before_done_scan.json()["alertsTotal"]

    done_scan = client.post("/ops/scheduler/scan")
    assert done_scan.status_code == 200

    status_after_done_scan = client.get("/ops/scheduler/status")
    assert status_after_done_scan.status_code == 200
    assert status_after_done_scan.json()["alertsTotal"] == alerts_before_done_scan

    reopened = client.patch(f"/tasks/{task_id}/status", json={"status": "todo"})
    assert reopened.status_code == 200

    status_before_reopen_scan = client.get("/ops/scheduler/status")
    assert status_before_reopen_scan.status_code == 200
    alerts_before_reopen_scan = status_before_reopen_scan.json()["alertsTotal"]

    reopen_scan = client.post("/ops/scheduler/scan")
    assert reopen_scan.status_code == 200

    status_after_reopen_scan = client.get("/ops/scheduler/status")
    assert status_after_reopen_scan.status_code == 200
    assert status_after_reopen_scan.json()["alertsTotal"] == alerts_before_reopen_scan + 1


def test_recurring_task_rolls_to_next_due() -> None:
    due_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    title = "recurring-rollover-9122"
    created = client.post(
        "/tasks",
        json={"title": title, "dueAt": due_at, "recurrence": "daily"},
    )
    assert created.status_code == 200

    scan = client.post("/ops/scheduler/scan")
    assert scan.status_code == 200

    tasks = client.get("/tasks")
    assert tasks.status_code == 200
    matched = [item for item in tasks.json() if item["title"] == title]
    assert matched
    task = matched[0]
    assert task["dueAt"] is not None
    assert task["nextRunAt"] is not None
    # Should roll forward after scan for recurring task.
    assert task["dueAt"] != due_at


def test_parse_time_relative_phrase() -> None:
    response = client.post(
        "/ops/scheduler/parse-time",
        json={"text": "in 2 hours", "timezone": "UTC"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["dueAt"] is not None


def test_parse_time_next_weekday_phrase() -> None:
    response = client.post(
        "/ops/scheduler/parse-time",
        json={"text": "next monday 9am", "timezone": "Asia/Manila"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["dueAt"] is not None


def test_calendar_export_creates_ics_file() -> None:
    due_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    client.post(
        "/tasks",
        json={"title": "Calendar Export Task", "dueAt": due_at, "recurrence": "weekly"},
    )

    response = client.post(
        "/calendar/export",
        json={"fileName": "test-export.ics", "includeCompleted": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["eventCount"] >= 1
    assert body["filePath"] is not None

    export_file = Path(body["filePath"])
    assert export_file.exists()
    text = export_file.read_text(encoding="utf-8")
    assert "BEGIN:VCALENDAR" in text
    assert "BEGIN:VEVENT" in text
    assert "SUMMARY:Calendar Export Task" in text
    assert "RRULE:FREQ=WEEKLY" in text


def test_calendar_import_creates_tasks_from_ics(tmp_path: Path) -> None:
    ics = tmp_path / "import.ics"
    ics.write_text(
        "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "BEGIN:VEVENT",
                "UID:a1@test",
                "DTSTART:20260701T090000Z",
                "SUMMARY:Imported Task A",
                "END:VEVENT",
                "BEGIN:VEVENT",
                "UID:b2@test",
                "DTSTART:20260702T100000Z",
                "SUMMARY:Imported Task B",
                "RRULE:FREQ=DAILY",
                "END:VEVENT",
                "END:VCALENDAR",
                "",
            ]
        ),
        encoding="utf-8",
    )

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )

    imported = client.post("/calendar/import", json={"filePath": str(ics)})
    assert imported.status_code == 200
    body = imported.json()
    assert body["accepted"] is True
    assert body["importedCount"] == 2

    tasks = client.get("/tasks")
    assert tasks.status_code == 200
    titles = [item["title"] for item in tasks.json()]
    assert "Imported Task A" in titles
    assert "Imported Task B" in titles


def test_calendar_import_rejects_non_ics(tmp_path: Path) -> None:
    file = tmp_path / "not-calendar.txt"
    file.write_text("hello", encoding="utf-8")
    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )
    imported = client.post("/calendar/import", json={"filePath": str(file)})
    assert imported.status_code == 200
    body = imported.json()
    assert body["accepted"] is False
    assert body["reason"] == "unsupported_file_type"


def test_calendar_import_dedup_updates_existing_tasks(tmp_path: Path) -> None:
    ics = tmp_path / "dedup.ics"
    ics.write_text(
        "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "BEGIN:VEVENT",
                "UID:d1@test",
                "DTSTART:20260703T110000Z",
                "SUMMARY:Dedup Task",
                "RRULE:FREQ=WEEKLY",
                "END:VEVENT",
                "END:VCALENDAR",
                "",
            ]
        ),
        encoding="utf-8",
    )
    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )

    first = client.post("/calendar/import", json={"filePath": str(ics)})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["accepted"] is True
    assert first_body["createdCount"] == 1
    assert first_body["updatedCount"] == 0

    second = client.post("/calendar/import", json={"filePath": str(ics)})
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["accepted"] is True
    assert second_body["createdCount"] == 0
    assert second_body["updatedCount"] == 1

    tasks = client.get("/tasks")
    assert tasks.status_code == 200
    dedup_titles = [item for item in tasks.json() if item["title"] == "Dedup Task"]
    assert len(dedup_titles) == 1


def test_calendar_import_uid_match_updates_even_if_due_changes(tmp_path: Path) -> None:
    first = tmp_path / "uid-first.ics"
    first.write_text(
        "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "BEGIN:VEVENT",
                "UID:u-123@test",
                "DTSTART:20260705T080000Z",
                "SUMMARY:UID Task",
                "END:VEVENT",
                "END:VCALENDAR",
                "",
            ]
        ),
        encoding="utf-8",
    )
    second = tmp_path / "uid-second.ics"
    second.write_text(
        "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "BEGIN:VEVENT",
                "UID:u-123@test",
                "DTSTART:20260706T090000Z",
                "SUMMARY:UID Task Renamed",
                "RRULE:FREQ=DAILY",
                "END:VEVENT",
                "END:VCALENDAR",
                "",
            ]
        ),
        encoding="utf-8",
    )

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )
    one = client.post("/calendar/import", json={"filePath": str(first)})
    assert one.status_code == 200
    assert one.json()["createdCount"] == 1

    two = client.post("/calendar/import", json={"filePath": str(second)})
    assert two.status_code == 200
    body = two.json()
    assert body["createdCount"] == 0
    assert body["updatedCount"] == 1

    tasks = client.get("/tasks")
    assert tasks.status_code == 200
    uid_tasks = [item for item in tasks.json() if item.get("externalId") == "u-123@test"]
    assert len(uid_tasks) == 1
    assert uid_tasks[0]["title"] == "UID Task Renamed"
    assert uid_tasks[0]["dueAt"] == "2026-07-06T09:00:00Z"
    assert uid_tasks[0]["recurrence"] == "daily"


def test_calendar_import_tzid_and_valarm_parsed(tmp_path: Path) -> None:
    ics = tmp_path / "tzid-valarm.ics"
    ics.write_text(
        "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "BEGIN:VEVENT",
                "UID:tz-1@test",
                "DTSTART;TZID=Asia/Manila:20260708T090000",
                "SUMMARY:TZID Alarm Task",
                "BEGIN:VALARM",
                "TRIGGER:-PT30M",
                "ACTION:DISPLAY",
                "DESCRIPTION:Reminder",
                "END:VALARM",
                "END:VEVENT",
                "END:VCALENDAR",
                "",
            ]
        ),
        encoding="utf-8",
    )
    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )

    imported = client.post("/calendar/import", json={"filePath": str(ics)})
    assert imported.status_code == 200
    assert imported.json()["createdCount"] == 1

    tasks = client.get("/tasks")
    assert tasks.status_code == 200
    matched = [item for item in tasks.json() if item.get("externalId") == "tz-1@test"]
    assert len(matched) == 1
    assert matched[0]["dueAt"] == "2026-07-08T01:00:00Z"
    assert matched[0]["reminderMinutesBefore"] == 30


def test_calendar_import_exdate_skips_occurrence(tmp_path: Path) -> None:
    ics = tmp_path / "exdate.ics"
    ics.write_text(
        "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "BEGIN:VEVENT",
                "UID:ex-1@test",
                "DTSTART;TZID=Asia/Manila:20260709T090000",
                "SUMMARY:EXDATE Task",
                "RRULE:FREQ=DAILY",
                "EXDATE;TZID=Asia/Manila:20260709T090000",
                "END:VEVENT",
                "END:VCALENDAR",
                "",
            ]
        ),
        encoding="utf-8",
    )
    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )

    imported = client.post("/calendar/import", json={"filePath": str(ics)})
    assert imported.status_code == 200
    body = imported.json()
    assert body["createdCount"] == 0
    assert body["updatedCount"] == 0
    assert body["skippedCount"] == 1

    tasks = client.get("/tasks")
    assert tasks.status_code == 200
    assert not any(item.get("externalId") == "ex-1@test" for item in tasks.json())


def test_calendar_export_writes_valarm_when_reminder_present(tmp_path: Path) -> None:
    ics = tmp_path / "for-export-alarm.ics"
    ics.write_text(
        "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "BEGIN:VEVENT",
                "UID:alarm-export@test",
                "DTSTART:20260710T120000Z",
                "SUMMARY:Alarm Export Task",
                "BEGIN:VALARM",
                "TRIGGER:-PT45M",
                "ACTION:DISPLAY",
                "DESCRIPTION:Reminder",
                "END:VALARM",
                "END:VEVENT",
                "END:VCALENDAR",
                "",
            ]
        ),
        encoding="utf-8",
    )
    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )
    imported = client.post("/calendar/import", json={"filePath": str(ics)})
    assert imported.status_code == 200
    assert imported.json()["createdCount"] == 1

    exported = client.post(
        "/calendar/export",
        json={"fileName": "alarm-export-test.ics", "includeCompleted": False},
    )
    assert exported.status_code == 200
    body = exported.json()
    assert body["accepted"] is True
    export_file = Path(body["filePath"])
    text = export_file.read_text(encoding="utf-8")
    assert "SUMMARY:Alarm Export Task" in text
    assert "BEGIN:VALARM" in text
    assert "TRIGGER:-PT45M" in text


def test_ops_web_scrape_success_and_store_note() -> None:
    html = """
    <html>
      <head><title>Ops News</title></head>
      <body>
        <p>Threat bulletin critical update marker-ops-1173.</p>
        <a href="/alert">Alert</a>
      </body>
    </html>
    """.encode("utf-8")

    client.post(
        "/control/permissions",
        json={"scope": "domain", "subject": "example.com", "decision": "allow"},
    )

    with patch("mindi_agent.web_service.build_opener") as mock_build:
        mock_build.return_value.open.return_value = _MockUrlResponse(html)
        response = client.post(
            "/ops/web/scrape",
            json={"url": "https://example.com/security", "maxChars": 800, "storeAsNote": True},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["reason"] == "ok"
    assert body["title"] == "Ops News"
    assert body["textLength"] > 0
    assert body["storedNoteId"] is not None
    assert len(body["links"]) >= 1

    searched = client.get("/memory/search?query=marker-ops-1173")
    assert searched.status_code == 200
    assert any("marker-ops-1173" in item["content"] for item in searched.json()["items"])


def test_ops_web_scrape_blocked_by_domain_policy() -> None:
    client.post(
        "/control/permissions",
        json={"scope": "domain", "subject": "blocked.example.com", "decision": "deny"},
    )
    response = client.post(
        "/ops/web/scrape",
        json={"url": "https://blocked.example.com/page", "storeAsNote": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is False
    assert body["reason"] == "domain_not_allowed"


def test_ops_web_scrape_rejects_invalid_url() -> None:
    response = client.post(
        "/ops/web/scrape",
        json={"url": "file:///tmp/secret.txt", "storeAsNote": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is False
    assert body["reason"] == "invalid_url"


def test_ops_security_scan_detects_suspicious_process_and_recover_deny_app() -> None:
    def fake_run(args, **kwargs):
        cmd = [str(part).lower() for part in args]
        if cmd[:1] == ["tasklist"]:
            stdout = '"mimikatz.exe","4321","Console","1","10,000 K"\n'
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")
        if cmd[:2] == ["sc", "query"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="SERVICE_NAME: WinDefend\nSTATE              : 4  RUNNING\n",
                stderr="",
            )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    with patch("mindi_agent.security_service.subprocess.run", side_effect=fake_run):
        scan = client.post("/ops/security/scan")
    assert scan.status_code == 200
    scan_body = scan.json()
    assert scan_body["accepted"] is True
    assert scan_body["newAlerts"] >= 1
    assert any(event["processName"] == "mimikatz.exe" for event in scan_body["events"])

    events = client.get("/ops/security/events?status=open&limit=20")
    assert events.status_code == 200
    items = events.json()
    target = next((item for item in items if item.get("processName") == "mimikatz.exe"), None)
    assert target is not None

    recover = client.post(
        "/ops/security/recover",
        json={"eventId": target["id"], "action": "deny_app", "target": "mimikatz.exe", "confirm": False},
    )
    assert recover.status_code == 200
    recover_body = recover.json()
    assert recover_body["accepted"] is True
    assert recover_body["reason"] == "app_denied"

    permissions = client.get("/control/permissions")
    assert permissions.status_code == 200
    assert any(
        item["scope"] == "app" and item["subject"].lower() == "mimikatz.exe" and item["decision"] == "deny"
        for item in permissions.json()
    )


def test_ops_security_recovery_kill_requires_confirmation() -> None:
    def fake_run(args, **kwargs):
        cmd = [str(part).lower() for part in args]
        if cmd[:1] == ["tasklist"]:
            stdout = '"ncat.exe","5544","Console","1","8,000 K"\n'
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")
        if cmd[:2] == ["sc", "query"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="SERVICE_NAME: WinDefend\nSTATE              : 4  RUNNING\n",
                stderr="",
            )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    with patch("mindi_agent.security_service.subprocess.run", side_effect=fake_run):
        scan = client.post("/ops/security/scan")
    assert scan.status_code == 200
    events = client.get("/ops/security/events?status=open&limit=20")
    assert events.status_code == 200
    target = next((item for item in events.json() if item.get("processName") == "ncat.exe"), None)
    assert target is not None

    recover = client.post(
        "/ops/security/recover",
        json={"eventId": target["id"], "action": "kill_process", "target": "ncat.exe", "confirm": False},
    )
    assert recover.status_code == 200
    body = recover.json()
    assert body["accepted"] is False
    assert body["reason"] == "confirmation_required"


def test_ops_automation_chain_success() -> None:
    html = """
    <html>
      <head><title>Chain Source</title></head>
      <body><p>chain-marker-3001</p></body>
    </html>
    """.encode("utf-8")

    client.post(
        "/control/permissions",
        json={"scope": "domain", "subject": "example.com", "decision": "allow"},
    )

    def fake_run(args, **kwargs):
        cmd = [str(part).lower() for part in args]
        if cmd[:1] == ["tasklist"]:
            stdout = '"explorer.exe","1111","Console","1","12,000 K"\n'
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")
        if cmd[:2] == ["sc", "query"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="SERVICE_NAME: WinDefend\nSTATE              : 4  RUNNING\n",
                stderr="",
            )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    with patch("mindi_agent.web_service.build_opener") as mock_build, patch(
        "mindi_agent.security_service.subprocess.run",
        side_effect=fake_run,
    ):
        mock_build.return_value.open.return_value = _MockUrlResponse(html)
        response = client.post(
            "/ops/automation/run",
            json={
                "name": "ops-chain-a",
                "continueOnFailure": False,
                "steps": [
                    {"kind": "web_scrape", "url": "https://example.com/a", "storeAsNote": True},
                    {"kind": "security_scan"},
                    {"kind": "create_task", "title": "chain task"},
                    {"kind": "create_note", "title": "chain note", "text": "chain done"},
                ],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["reason"] == "ok"
    assert body["completedSteps"] == 4
    assert body["totalSteps"] == 4
    assert len(body["steps"]) == 4
    assert all(step["accepted"] is True for step in body["steps"])


def test_ops_automation_chain_failure_reports_recovery() -> None:
    client.post(
        "/control/permissions",
        json={"scope": "domain", "subject": "blocked-chain.example.com", "decision": "deny"},
    )

    response = client.post(
        "/ops/automation/run",
        json={
            "name": "ops-chain-b",
            "continueOnFailure": False,
            "steps": [
                {"kind": "web_scrape", "url": "https://blocked-chain.example.com/a"},
                {"kind": "create_task", "title": "should not run"},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is False
    assert body["reason"] == "partial_failure"
    assert body["failedStepIndex"] == 0
    assert body["completedSteps"] == 0
    assert body["recoverySummary"] is not None
    assert body["steps"][0]["accepted"] is False
    assert body["steps"][0]["recoveryHint"] is not None


def test_ops_alert_feed_and_actions() -> None:
    def fake_run(args, **kwargs):
        cmd = [str(part).lower() for part in args]
        if cmd[:1] == ["tasklist"]:
            stdout = "\n".join(
                [
                    '"ncat.exe","5544","Console","1","8,000 K"',
                    '"mimikatz.exe","7788","Console","1","11,000 K"',
                ]
            )
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")
        if cmd[:2] == ["sc", "query"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="SERVICE_NAME: WinDefend\nSTATE              : 4  RUNNING\n",
                stderr="",
            )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    with patch("mindi_agent.security_service.subprocess.run", side_effect=fake_run):
        scan = client.post("/ops/security/scan")
    assert scan.status_code == 200
    assert scan.json()["accepted"] is True

    feed = client.get("/ops/alerts/feed?limit=20")
    assert feed.status_code == 200
    feed_body = feed.json()
    assert feed_body["accepted"] is True
    assert feed_body["total"] >= 2
    assert feed_body["critical"] >= 1
    assert feed_body["warning"] >= 1
    items = feed_body["items"]
    assert items
    assert items[0]["severity"] == "critical"

    target_id = items[0]["id"]
    create_task = client.post(
        "/ops/alerts/action",
        json={"alertId": target_id, "action": "create_recovery_task"},
    )
    assert create_task.status_code == 200
    task_body = create_task.json()
    assert task_body["accepted"] is True
    assert task_body["createdTaskId"] is not None

    export = client.post(
        "/ops/alerts/action",
        json={"alertId": target_id, "action": "export_report"},
    )
    assert export.status_code == 200
    export_body = export.json()
    assert export_body["accepted"] is True
    assert export_body["reportPath"] is not None
    assert Path(export_body["reportPath"]).exists()

    dismiss = client.post(
        "/ops/alerts/action",
        json={"alertId": target_id, "action": "dismiss"},
    )
    assert dismiss.status_code == 200
    dismiss_body = dismiss.json()
    assert dismiss_body["accepted"] is True

    feed_after = client.get("/ops/alerts/feed?limit=20")
    assert feed_after.status_code == 200
    assert not any(item["id"] == target_id for item in feed_after.json()["items"])


def test_ops_privacy_status_and_update() -> None:
    before = client.get("/ops/privacy/status")
    assert before.status_code == 200
    body = before.json()
    assert body["safeStorageDefault"] is True
    assert "redactionEnabled" in body

    flipped = client.post("/ops/privacy/update", json={"redactionEnabled": not body["redactionEnabled"]})
    assert flipped.status_code == 200
    flipped_body = flipped.json()
    assert flipped_body["redactionEnabled"] is (not body["redactionEnabled"])

    reset = client.post("/ops/privacy/update", json={"redactionEnabled": True})
    assert reset.status_code == 200
    assert reset.json()["redactionEnabled"] is True


def test_ops_web_scrape_storage_redaction_applies_to_note() -> None:
    html = """
    <html>
      <head><title>Sensitive Page</title></head>
      <body>
        Contact john.doe@example.com and password=TopSecret123 for support.
      </body>
    </html>
    """.encode("utf-8")
    client.post("/ops/privacy/update", json={"redactionEnabled": True})
    client.post(
        "/control/permissions",
        json={"scope": "domain", "subject": "example.com", "decision": "allow"},
    )

    with patch("mindi_agent.web_service.build_opener") as mock_build:
        mock_build.return_value.open.return_value = _MockUrlResponse(html)
        response = client.post(
            "/ops/web/scrape",
            json={"url": "https://example.com/private", "storeAsNote": True},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["storageRedacted"] is True
    assert body["redactionCount"] >= 1

    notes = client.get("/memory/search?query=Sensitive Page")
    assert notes.status_code == 200
    items = notes.json()["items"]
    assert items
    assert any("[REDACTED_EMAIL]" in item["content"] or "[REDACTED_PASSWORD]" in item["content"] for item in items)


def test_perception_storage_redaction_applies_to_snapshot() -> None:
    marker = "perception-private-marker-8891"
    client.post("/ops/privacy/update", json={"redactionEnabled": True})
    client.post(
        "/control/permissions",
        json={"scope": "action", "subject": "perception.screen.capture", "decision": "allow"},
    )
    image = Image.new("RGB", (220, 120), color="white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([10, 10, 160, 36], fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    data_url = f"data:image/png;base64,{encoded}"

    with patch("mindi_agent.memory_service.extract_text_for_ocr") as mock_ocr:
        mock_ocr.return_value = (f"{marker} email admin@example.com", "image_ocr")
        analyzed = client.post(
            "/perception/screen/analyze",
            json={"imageDataUrl": data_url, "includeOcr": True, "maxBlocks": 6},
        )
    assert analyzed.status_code == 200
    analyzed_body = analyzed.json()
    assert analyzed_body["accepted"] is True
    assert analyzed_body["storageRedacted"] is True
    assert analyzed_body["redactionCount"] >= 1

    searched = client.get(f"/memory/perception/search?query={marker}&limit=10")
    assert searched.status_code == 200
    items = searched.json()["items"]
    assert items
    assert any("[REDACTED_EMAIL]" in (item.get("text") or "") for item in items)


def test_intelligence_style_update_and_reply_mode() -> None:
    style_before = client.get("/ops/intelligence/style")
    assert style_before.status_code == 200

    updated = client.post(
        "/ops/intelligence/style",
        json={
            "languageMode": "taglish",
            "slangEnabled": True,
            "addSlangTerms": ["solid"],
        },
    )
    assert updated.status_code == 200
    updated_body = updated.json()
    assert updated_body["languageMode"] == "taglish"
    assert updated_body["slangEnabled"] is True
    assert "solid" in updated_body["slangTerms"]

    assistant = client.post("/assistant/respond", json={"text": "summarize my notes"})
    assert assistant.status_code == 200
    reply = assistant.json()["reply"]
    assert "Sige." in reply
    assert "[solid]" in reply

    reset = client.post(
        "/ops/intelligence/style",
        json={"languageMode": "english", "slangEnabled": False, "resetSlangTerms": True},
    )
    assert reset.status_code == 200
    reset_body = reset.json()
    assert reset_body["languageMode"] == "english"
    assert reset_body["slangEnabled"] is False
    assert reset_body["slangTerms"] == []


def test_intelligence_eval_run_and_history() -> None:
    run = client.post("/ops/intelligence/eval/run")
    assert run.status_code == 200
    body = run.json()
    assert body["accepted"] is True
    assert body["reason"] == "ok"
    assert body["scope"] == "active"
    assert body["totalCases"] >= 3
    assert body["passedCases"] >= 3
    assert len(body["cases"]) == body["totalCases"]

    history = client.get("/ops/intelligence/eval/history?limit=5")
    assert history.status_code == 200
    items = history.json()
    assert items
    assert any(item["runId"] == body["runId"] for item in items)


def test_intelligence_tuning_apply_requires_eval_gate() -> None:
    discarded = client.delete("/ops/intelligence/tuning/pending")
    assert discarded.status_code == 200

    staged = client.post(
        "/ops/intelligence/tuning/stage",
        json={"preset": "balanced", "responseVerbosity": "brief", "resetCustomRiskyTerms": True},
    )
    assert staged.status_code == 200
    staged_body = staged.json()
    assert staged_body["pending"]["preset"] == "balanced"
    assert staged_body["pending"]["responseVerbosity"] == "brief"
    pending_version = staged_body["pendingVersion"]
    assert pending_version

    blocked_apply = client.post("/ops/intelligence/tuning/apply")
    assert blocked_apply.status_code == 200
    blocked_apply_body = blocked_apply.json()
    assert blocked_apply_body["accepted"] is False
    assert blocked_apply_body["reason"] == "pending_candidate_not_evaluated"

    eval_pending = client.post("/ops/intelligence/eval/run", json={"scope": "pending"})
    assert eval_pending.status_code == 200
    eval_pending_body = eval_pending.json()
    assert eval_pending_body["accepted"] is True
    assert eval_pending_body["scope"] == "pending"
    assert eval_pending_body["gatePassed"] is True
    assert eval_pending_body["score"] == 1.0

    applied = client.post("/ops/intelligence/tuning/apply")
    assert applied.status_code == 200
    applied_body = applied.json()
    assert applied_body["accepted"] is True
    assert applied_body["reason"] == "applied"
    assert applied_body["status"]["pending"] is None
    assert applied_body["status"]["pendingVersion"] is None
    assert applied_body["status"]["active"]["preset"] == "balanced"
    assert applied_body["status"]["active"]["responseVerbosity"] == "brief"
    assert applied_body["status"]["lastActiveEvalScore"] == 1.0

    assistant = client.post("/assistant/respond", json={"text": "summarize my notes"})
    assert assistant.status_code == 200
    reply = assistant.json()["reply"]
    assert reply
    assert not reply.startswith("Status: ")

    reset = client.post(
        "/ops/intelligence/tuning/stage",
        json={"preset": "safe", "responseVerbosity": "balanced", "resetCustomRiskyTerms": True},
    )
    assert reset.status_code == 200
    reset_eval = client.post("/ops/intelligence/eval/run", json={"scope": "pending"})
    assert reset_eval.status_code == 200
    reset_apply = client.post("/ops/intelligence/tuning/apply")
    assert reset_apply.status_code == 200
    assert reset_apply.json()["accepted"] is True


def test_intelligence_tuning_gate_blocks_bad_candidate() -> None:
    discarded = client.delete("/ops/intelligence/tuning/pending")
    assert discarded.status_code == 200

    staged = client.post(
        "/ops/intelligence/tuning/stage",
        json={"preset": "safe", "responseVerbosity": "balanced", "addCustomRiskyTerms": ["notepad"]},
    )
    assert staged.status_code == 200
    staged_body = staged.json()
    assert "notepad" in staged_body["pending"]["customRiskyTerms"]

    eval_pending = client.post("/ops/intelligence/eval/run", json={"scope": "pending"})
    assert eval_pending.status_code == 200
    eval_pending_body = eval_pending.json()
    assert eval_pending_body["accepted"] is True
    assert eval_pending_body["scope"] == "pending"
    assert eval_pending_body["gatePassed"] is False
    assert eval_pending_body["score"] < 1.0
    assert any(case["id"] == "policy_open_app" and case["accepted"] is False for case in eval_pending_body["cases"])

    apply_attempt = client.post("/ops/intelligence/tuning/apply")
    assert apply_attempt.status_code == 200
    apply_attempt_body = apply_attempt.json()
    assert apply_attempt_body["accepted"] is False
    assert apply_attempt_body["reason"] == "pending_eval_below_threshold"
    assert apply_attempt_body["status"]["canApplyPending"] is False

    cleanup = client.delete("/ops/intelligence/tuning/pending")
    assert cleanup.status_code == 200
    assert cleanup.json()["pending"] is None


def test_intelligence_learning_requires_approved_source() -> None:
    run = client.post("/ops/intelligence/learning/run")
    assert run.status_code == 200
    body = run.json()
    assert body["accepted"] is False
    assert body["reason"] == "no_approved_sources"
    assert body["candidateCount"] == 0


def test_intelligence_learning_can_extract_and_apply_slang_from_approved_note() -> None:
    style_reset = client.post(
        "/ops/intelligence/style",
        json={"languageMode": "english", "slangEnabled": False, "resetSlangTerms": True},
    )
    assert style_reset.status_code == 200

    note = client.post(
        "/memory/notes",
        json={
            "title": "Taglish style note",
            "content": "slang: astig\nterm: lodi\nnoise line without marker\nsolid - taglish",
            "tags": ["style", "taglish"],
        },
    )
    assert note.status_code == 200
    note_body = note.json()

    approved = client.post(
        "/ops/intelligence/learning/source",
        json={"noteId": note_body["id"], "approved": True},
    )
    assert approved.status_code == 200
    approved_body = approved.json()
    assert approved_body["accepted"] is True
    assert any(item["noteId"] == note_body["id"] for item in approved_body["status"]["approvedSources"])

    learning_run = client.post("/ops/intelligence/learning/run")
    assert learning_run.status_code == 200
    learning_run_body = learning_run.json()
    assert learning_run_body["accepted"] is True
    assert learning_run_body["candidateCount"] >= 3
    extracted_terms = {item["term"] for item in learning_run_body["candidates"]}
    assert {"astig", "lodi", "solid"}.issubset(extracted_terms)

    learning_eval = client.post(
        "/ops/intelligence/eval/run",
        json={"scope": "learning", "terms": ["astig", "solid"]},
    )
    assert learning_eval.status_code == 200
    learning_eval_body = learning_eval.json()
    assert learning_eval_body["accepted"] is True
    assert learning_eval_body["scope"] == "learning"
    assert learning_eval_body["gatePassed"] is True

    apply = client.post(
        "/ops/intelligence/learning/apply",
        json={"terms": ["astig", "solid"], "enableSlang": True},
    )
    assert apply.status_code == 200
    apply_body = apply.json()
    assert apply_body["accepted"] is True
    assert set(apply_body["appliedTerms"]) == {"astig", "solid"}
    assert apply_body["style"]["slangEnabled"] is True
    assert "astig" in apply_body["style"]["slangTerms"]
    assert "solid" in apply_body["style"]["slangTerms"]
    remaining_terms = {item["term"] for item in apply_body["status"]["candidates"]}
    assert "lodi" in remaining_terms

    reply = client.post("/assistant/respond", json={"text": "summarize my notes"})
    assert reply.status_code == 200
    assert "[astig]" in reply.json()["reply"]


def test_intelligence_learning_source_requires_style_context() -> None:
    note = client.post(
        "/memory/notes",
        json={
            "title": "General note",
            "content": "This is a generic memory note without explicit learning markers.",
            "tags": ["general"],
        },
    )
    assert note.status_code == 200
    note_body = note.json()

    approved = client.post(
        "/ops/intelligence/learning/source",
        json={"noteId": note_body["id"], "approved": True},
    )
    assert approved.status_code == 200
    approved_body = approved.json()
    assert approved_body["accepted"] is False
    assert approved_body["reason"] == "note_not_learning_source"


def test_intelligence_learning_filters_candidates_and_requires_eval_gate() -> None:
    style_reset = client.post(
        "/ops/intelligence/style",
        json={"languageMode": "english", "slangEnabled": False, "resetSlangTerms": True},
    )
    assert style_reset.status_code == 200

    note = client.post(
        "/memory/notes",
        json={
            "title": "Filtered style note",
            "content": "slang: astig\nslang: notepad\nterm: lodi\nfirewall - taglish",
            "tags": ["style", "taglish"],
        },
    )
    assert note.status_code == 200
    note_body = note.json()

    approved = client.post(
        "/ops/intelligence/learning/source",
        json={"noteId": note_body["id"], "approved": True},
    )
    assert approved.status_code == 200
    assert approved.json()["accepted"] is True

    learning_run = client.post("/ops/intelligence/learning/run")
    assert learning_run.status_code == 200
    learning_run_body = learning_run.json()
    assert learning_run_body["accepted"] is True
    extracted_terms = {item["term"] for item in learning_run_body["candidates"]}
    assert "astig" in extracted_terms
    assert "lodi" in extracted_terms
    assert "notepad" not in extracted_terms
    assert "firewall" not in extracted_terms

    blocked_apply = client.post(
        "/ops/intelligence/learning/apply",
        json={"terms": ["astig"], "enableSlang": True},
    )
    assert blocked_apply.status_code == 200
    blocked_apply_body = blocked_apply.json()
    assert blocked_apply_body["accepted"] is False
    assert blocked_apply_body["reason"] == "learning_candidates_not_evaluated"

    learning_eval = client.post(
        "/ops/intelligence/eval/run",
        json={"scope": "learning", "terms": ["astig"]},
    )
    assert learning_eval.status_code == 200
    learning_eval_body = learning_eval.json()
    assert learning_eval_body["accepted"] is True
    assert learning_eval_body["scope"] == "learning"
    assert learning_eval_body["gatePassed"] is True
    assert learning_eval_body["score"] == 1.0
    assert any(case["id"] == "style_learned_slang_reply" and case["accepted"] is True for case in learning_eval_body["cases"])

    applied = client.post(
        "/ops/intelligence/learning/apply",
        json={"terms": ["astig"], "enableSlang": True},
    )
    assert applied.status_code == 200
    applied_body = applied.json()
    assert applied_body["accepted"] is True
    assert applied_body["reason"] == "applied"
    assert applied_body["appliedTerms"] == ["astig"]
    assert "astig" in applied_body["style"]["slangTerms"]


def test_intelligence_adaptation_status_requires_justified_evidence() -> None:
    _reset_intelligence_state_for_adaptation_tests()

    status = client.get("/ops/intelligence/adaptation/status")
    assert status.status_code == 200
    status_body = status.json()
    assert status_body["justified"] is False
    assert status_body["recommendedMethod"] == "none"
    assert status_body["exportReady"] is False
    assert status_body["reason"] == "insufficient_eval_evidence"

    export_attempt = client.post("/ops/intelligence/adaptation/export")
    assert export_attempt.status_code == 200
    export_body = export_attempt.json()
    assert export_body["accepted"] is False
    assert export_body["reason"] == "adaptation_not_justified"
    assert export_body["status"]["exportReady"] is False


def test_intelligence_adaptation_status_prefers_prompt_controls_without_style_signal() -> None:
    _reset_intelligence_state_for_adaptation_tests()

    active_eval = client.post("/ops/intelligence/eval/run", json={"scope": "active"})
    assert active_eval.status_code == 200
    assert active_eval.json()["gatePassed"] is False

    staged = client.post(
        "/ops/intelligence/tuning/stage",
        json={"preset": "balanced", "responseVerbosity": "brief"},
    )
    assert staged.status_code == 200
    pending_eval = client.post("/ops/intelligence/eval/run", json={"scope": "pending"})
    assert pending_eval.status_code == 200
    assert pending_eval.json()["gatePassed"] is True
    applied = client.post("/ops/intelligence/tuning/apply")
    assert applied.status_code == 200
    assert applied.json()["accepted"] is True

    status = client.get("/ops/intelligence/adaptation/status")
    assert status.status_code == 200
    status_body = status.json()
    assert status_body["justified"] is False
    assert status_body["recommendedMethod"] == "prompt_only"
    assert status_body["exportReady"] is False
    assert status_body["reason"] == "prompt_controls_sufficient"


def test_intelligence_adaptation_export_creates_lora_pack_when_style_signal_is_stable() -> None:
    _reset_intelligence_state_for_adaptation_tests()

    note = client.post(
        "/memory/notes",
        json={
            "title": "LoRA style note",
            "content": "slang: astig\nterm: lodi\nsolid - taglish",
            "tags": ["style", "taglish"],
        },
    )
    assert note.status_code == 200
    note_id = note.json()["id"]

    approved = client.post("/ops/intelligence/learning/source", json={"noteId": note_id, "approved": True})
    assert approved.status_code == 200
    assert approved.json()["accepted"] is True

    learning_run = client.post("/ops/intelligence/learning/run")
    assert learning_run.status_code == 200
    assert learning_run.json()["accepted"] is True

    learning_eval = client.post(
        "/ops/intelligence/eval/run",
        json={"scope": "learning", "terms": ["astig"]},
    )
    assert learning_eval.status_code == 200
    assert learning_eval.json()["gatePassed"] is True

    learning_apply = client.post(
        "/ops/intelligence/learning/apply",
        json={"terms": ["astig"], "enableSlang": True},
    )
    assert learning_apply.status_code == 200
    assert learning_apply.json()["accepted"] is True

    active_eval = client.post("/ops/intelligence/eval/run", json={"scope": "active"})
    assert active_eval.status_code == 200
    staged = client.post(
        "/ops/intelligence/tuning/stage",
        json={"preset": "companion", "responseVerbosity": "balanced"},
    )
    assert staged.status_code == 200
    pending_eval = client.post("/ops/intelligence/eval/run", json={"scope": "pending"})
    assert pending_eval.status_code == 200
    assert pending_eval.json()["gatePassed"] is True
    tuning_apply = client.post("/ops/intelligence/tuning/apply")
    assert tuning_apply.status_code == 200
    assert tuning_apply.json()["accepted"] is True

    status = client.get("/ops/intelligence/adaptation/status")
    assert status.status_code == 200
    status_body = status.json()
    assert status_body["justified"] is True
    assert status_body["recommendedMethod"] == "lora"
    assert status_body["exportReady"] is True
    assert status_body["appliedSlangCount"] == 1
    assert status_body["passedLearningRuns"] >= 1
    assert status_body["passedPendingRuns"] >= 1

    export_response = client.post("/ops/intelligence/adaptation/export")
    assert export_response.status_code == 200
    export_body = export_response.json()
    assert export_body["accepted"] is True
    assert export_body["reason"] == "exported"
    assert export_body["method"] == "lora"
    assert export_body["exampleCount"] >= 3
    assert export_body["exportPath"]

    export_path = Path(export_body["exportPath"])
    assert export_path.exists() is True
    payload = export_path.read_text(encoding="utf-8")
    assert '"recommendedMethod": "lora"' in payload
    assert '"appliedSlangTerms": [' in payload
    assert '"astig"' in payload

def test_perception_permissions_status_defaults_unset() -> None:
    response = client.get("/perception/permissions")
    assert response.status_code == 200
    body = response.json()
    assert body["screenSubject"] == "perception.screen.capture"
    assert body["cameraSubject"] == "perception.camera.capture"
    assert body["screenDecision"] in {"allow", "deny", "unset"}
    assert body["cameraDecision"] in {"allow", "deny", "unset"}


def test_perception_screen_analyze_blocked_without_permission_and_audited() -> None:
    image = Image.new("RGB", (200, 120), color="white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([12, 12, 140, 36], fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    data_url = f"data:image/png;base64,{encoded}"

    # Force an explicit deny to make behavior deterministic even if prior tests granted allow.
    client.post(
        "/control/permissions",
        json={"scope": "action", "subject": "perception.screen.capture", "decision": "deny"},
    )

    blocked = client.post(
        "/perception/screen/analyze",
        json={"imageDataUrl": data_url, "includeOcr": False},
    )
    assert blocked.status_code == 200
    body = blocked.json()
    assert body["accepted"] is False
    assert body["reason"] == "screen_permission_denied"

    logs = client.get("/audit/logs")
    assert logs.status_code == 200
    first = logs.json()[0]
    assert first["intent"] == "perception_screen_analyze"
    assert first["result"] == "blocked"
    assert first["reason"] == "screen_permission_denied"


def test_perception_screen_analyze_success(tmp_path: Path) -> None:
    image_path = tmp_path / "screen.png"
    image = Image.new("RGB", (320, 180), color="white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([20, 20, 260, 60], fill="black")
    draw.rectangle([20, 80, 220, 120], fill="black")
    image.save(image_path)

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )
    client.post(
        "/control/permissions",
        json={"scope": "action", "subject": "perception.screen.capture", "decision": "allow"},
    )

    with patch("mindi_agent.memory_service.extract_text_for_ocr") as mock_ocr:
        mock_ocr.return_value = ("open settings panel", "image_ocr")
        response = client.post(
            "/perception/screen/analyze",
            json={"path": str(image_path), "includeOcr": True, "maxBlocks": 10},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["reason"] == "ok"
    assert body["ocrMode"] == "image_ocr"
    assert body["textLength"] == len("open settings panel")
    assert body["imageWidth"] == 320
    assert body["imageHeight"] == 180
    assert len(body["blocks"]) >= 1


def test_perception_screen_analyze_allows_blocks_when_ocr_fails(tmp_path: Path) -> None:
    image_path = tmp_path / "screen-ocr-fail.png"
    image = Image.new("RGB", (300, 160), color="white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([30, 30, 240, 70], fill="black")
    image.save(image_path)

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )
    client.post(
        "/control/permissions",
        json={"scope": "action", "subject": "perception.screen.capture", "decision": "allow"},
    )

    with patch("mindi_agent.memory_service.extract_text_for_ocr") as mock_ocr:
        mock_ocr.side_effect = ValueError("tesseract_not_installed")
        response = client.post(
            "/perception/screen/analyze",
            json={"path": str(image_path), "includeOcr": True, "maxBlocks": 5},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["reason"] == "ocr_unavailable_blocks_extracted"
    assert body["ocrError"] == "tesseract_not_installed"
    assert body["text"] is None
    assert len(body["blocks"]) >= 1


def test_perception_screen_analyze_prefers_runtime_ocr_backend(tmp_path: Path) -> None:
    image_path = tmp_path / "screen-runtime-ocr.png"
    image = Image.new("RGB", (320, 180), color="white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([20, 20, 260, 60], fill="black")
    image.save(image_path)

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )
    client.post(
        "/control/permissions",
        json={"scope": "action", "subject": "perception.screen.capture", "decision": "allow"},
    )

    with patch.object(
        store.ai_runtime,
        "extract_ocr",
        return_value={
            "accepted": True,
            "text": "runtime screen text",
            "ocrMode": "glm_ocr_markdown",
            "provider": "huggingface_local",
            "model": "zai-org/GLM-OCR",
            "degraded": False,
        },
    ):
        with patch("mindi_agent.memory_service.extract_text_for_ocr", side_effect=AssertionError("fallback should not run")):
            response = client.post(
                "/perception/screen/analyze",
                json={"path": str(image_path), "includeOcr": True, "maxBlocks": 10},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["reason"] == "ok"
    assert body["ocrMode"] == "glm_ocr_markdown"
    assert body["ocrBackend"] == "huggingface_local"
    assert body["ocrModel"] == "zai-org/GLM-OCR"
    assert body["degraded"] is False
    assert body["fallbackReason"] is None
    assert body["text"] == "runtime screen text"
    assert len(body["blocks"]) >= 1


def test_perception_screen_analyze_runtime_ocr_failure_keeps_blocks(tmp_path: Path) -> None:
    image_path = tmp_path / "screen-runtime-fallback.png"
    image = Image.new("RGB", (280, 160), color="white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([22, 22, 240, 68], fill="black")
    image.save(image_path)

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )
    client.post(
        "/control/permissions",
        json={"scope": "action", "subject": "perception.screen.capture", "decision": "allow"},
    )

    with patch.object(
        store.ai_runtime,
        "extract_ocr",
        return_value={
            "accepted": False,
            "reason": "ocr_model_not_ready",
            "provider": "huggingface_local",
            "model": "zai-org/GLM-OCR",
            "degraded": True,
        },
    ):
        with patch("mindi_agent.memory_service.extract_text_for_ocr") as mock_ocr:
            mock_ocr.return_value = ("fallback screen text", "image_ocr")
            response = client.post(
                "/perception/screen/analyze",
                json={"path": str(image_path), "includeOcr": True, "maxBlocks": 8},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["reason"] == "ok"
    assert body["ocrMode"] == "image_ocr"
    assert body["ocrBackend"] == "pytesseract_fallback"
    assert body["ocrModel"] == "local_tesseract"
    assert body["degraded"] is True
    assert body["fallbackReason"] == "ocr_model_not_ready"
    assert body["text"] == "fallback screen text"
    assert len(body["blocks"]) >= 1


def test_perception_screen_analyze_rejects_unsupported_type(tmp_path: Path) -> None:
    payload = tmp_path / "note.txt"
    payload.write_text("not an image", encoding="utf-8")
    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )
    client.post(
        "/control/permissions",
        json={"scope": "action", "subject": "perception.screen.capture", "decision": "allow"},
    )

    response = client.post(
        "/perception/screen/analyze",
        json={"path": str(payload), "includeOcr": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is False
    assert body["reason"] == "unsupported_file_type"


def test_perception_screen_analyze_inline_data_url() -> None:
    image = Image.new("RGB", (240, 140), color="white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([12, 12, 180, 42], fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    data_url = f"data:image/png;base64,{encoded}"

    client.post(
        "/control/permissions",
        json={"scope": "action", "subject": "perception.screen.capture", "decision": "allow"},
    )

    with patch("mindi_agent.memory_service.extract_text_for_ocr") as mock_ocr:
        mock_ocr.return_value = ("quick panel", "image_ocr")
        response = client.post(
            "/perception/screen/analyze",
            json={"imageDataUrl": data_url, "includeOcr": True, "maxBlocks": 8},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["reason"] == "ok"
    assert body["imageWidth"] == 240
    assert body["imageHeight"] == 140
    assert body["textLength"] == len("quick panel")
    assert len(body["blocks"]) >= 1


def test_perception_snapshot_memory_bridge_list_and_search() -> None:
    marker = "perception-bridge-marker-9917"
    image = Image.new("RGB", (220, 120), color="white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([10, 10, 160, 38], fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    data_url = f"data:image/png;base64,{encoded}"

    client.post(
        "/control/permissions",
        json={"scope": "action", "subject": "perception.screen.capture", "decision": "allow"},
    )

    with patch("mindi_agent.memory_service.extract_text_for_ocr") as mock_ocr:
        mock_ocr.return_value = (f"screen says {marker}", "image_ocr")
        analyzed = client.post(
            "/perception/screen/analyze",
            json={"imageDataUrl": data_url, "includeOcr": True, "maxBlocks": 6},
        )

    assert analyzed.status_code == 200
    analyzed_body = analyzed.json()
    assert analyzed_body["accepted"] is True
    assert analyzed_body["snapshotId"] is not None

    listed = client.get("/memory/perception?limit=10")
    assert listed.status_code == 200
    listed_items = listed.json()
    assert any(item["id"] == analyzed_body["snapshotId"] for item in listed_items)

    searched = client.get(f"/memory/perception/search?query={marker}&limit=10")
    assert searched.status_code == 200
    search_body = searched.json()
    assert search_body["query"] == marker
    assert any(marker in (item.get("text") or "") for item in search_body["items"])


def test_assistant_uses_latest_perception_snapshot_context() -> None:
    marker = "assistant-screen-context-7634"
    image = Image.new("RGB", (180, 100), color="white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([8, 8, 130, 34], fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    data_url = f"data:image/png;base64,{encoded}"

    client.post(
        "/control/permissions",
        json={"scope": "action", "subject": "perception.screen.capture", "decision": "allow"},
    )

    with patch("mindi_agent.memory_service.extract_text_for_ocr") as mock_ocr:
        mock_ocr.return_value = (f"latest ui text {marker}", "image_ocr")
        analyzed = client.post(
            "/perception/screen/analyze",
            json={"imageDataUrl": data_url, "includeOcr": True, "maxBlocks": 5},
        )
    assert analyzed.status_code == 200

    assistant = client.post(
        "/assistant/respond",
        json={"text": "what's on screen right now?"},
    )
    assert assistant.status_code == 200
    body = assistant.json()
    assert body["status"] == "ready"
    assert "Latest perception snapshot available." in body["reply"]
    assert marker in body["reply"]


def test_ai_runtime_status_endpoint_shape() -> None:
    response = client.get("/ops/ai/status")
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert "runtime" in body
    assert "features" in body
    assert "llm" in body["features"]
    assert "asr" in body["features"]
    assert "ocr" in body["features"]
    assert "lastFailureReason" in body["features"]["llm"]
    assert "lastLatencyMs" in body["features"]["llm"]


def test_asr_transcribe_rejects_invalid_source() -> None:
    response = client.post(
        "/ops/asr/transcribe",
        json={"sourceType": "unsupported", "sourceValue": "data/inbox/sample.wav"},
    )
    assert response.status_code == 422


def test_asr_transcribe_file_missing_returns_controlled_response() -> None:
    response = client.post(
        "/ops/asr/transcribe",
        json={"sourceType": "file", "sourceValue": "data/inbox/missing.wav"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is False
    assert body["reason"] in {"runtime_unavailable", "audio_not_found", "audio_file_not_allowed"}


def test_assistant_response_includes_runtime_metadata() -> None:
    response = client.post("/assistant/respond", json={"text": "summarize my notes"})
    assert response.status_code == 200
    body = response.json()
    assert "provider" in body
    assert "model" in body
    assert "degraded" in body
    assert "fallbackReason" in body


def test_assistant_response_runtime_success_path() -> None:
    with patch.object(
        store.ai_runtime,
        "generate_reply",
        return_value={
            "accepted": True,
            "reply": "runtime response",
            "provider": "llama.cpp",
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "latencyMs": 42,
        },
    ):
        response = client.post("/assistant/respond", json={"text": "summarize my notes"})
    assert response.status_code == 200
    body = response.json()
    assert body["degraded"] is False
    assert body["fallbackReason"] is None
    assert body["provider"] == "llama.cpp"
    assert body["model"] == "Qwen/Qwen2.5-7B-Instruct"


def test_assistant_response_runtime_failure_falls_back() -> None:
    with patch.object(
        store.ai_runtime,
        "generate_reply",
        return_value={
            "accepted": False,
            "reason": "llama_cpp_timeout",
            "provider": "llama.cpp",
            "model": "Qwen/Qwen2.5-7B-Instruct",
        },
    ):
        response = client.post("/assistant/respond", json={"text": "summarize my notes"})
    assert response.status_code == 200
    body = response.json()
    assert body["degraded"] is True
    assert body["fallbackReason"] == "llama_cpp_timeout"
    assert body["provider"] == "llama.cpp"
    assert body["model"] == "Qwen/Qwen2.5-7B-Instruct"


def test_assistant_greeting_skips_document_rag() -> None:
    with patch.object(
        store.memory_db,
        "search_documents",
        return_value=[],
    ) as search_mock, patch.object(
        store.ai_runtime,
        "generate_reply",
        return_value={
            "accepted": True,
            "reply": "Hey. Good to see you.",
            "provider": "ollama",
            "model": "qwen2.5:0.5b",
            "latencyMs": 12,
        },
    ) as generate_mock:
        response = client.post("/assistant/respond", json={"text": "hi"})

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "ollama"
    assert body["rag"]["retrievalMode"] == "none"
    search_mock.assert_not_called()
    assert generate_mock.call_args.kwargs["prompt"] == "<user_turn>hi</user_turn>"


def test_short_chat_with_docs_does_not_attach_rag() -> None:
    with patch.object(
        store.memory_db,
        "search_documents",
        return_value=[],
    ) as search_mock, patch.object(
        store.ai_runtime,
        "generate_reply",
        return_value={
            "accepted": True,
            "reply": "Hey. I'm here.",
            "provider": "ollama",
            "model": "qwen2.5:0.5b",
            "latencyMs": 12,
        },
    ) as generate_mock:
        response = client.post("/assistant/respond", json={"text": "how are you"})

    assert response.status_code == 200
    body = response.json()
    assert body["rag"]["retrievalMode"] == "none"
    search_mock.assert_not_called()
    assert generate_mock.call_args.kwargs["prompt"] == "<user_turn>how are you</user_turn>"


def test_ai_runtime_config_update_roundtrip() -> None:
    response = client.post(
        "/ops/ai/config",
        json={
            "llmModelPath": "C:/models/qwen2.5-7b-instruct.gguf",
            "llmLanguagePackPath": "C:/models/language_pack_ph.json",
            "asrModelPath": "C:/models/qwen3-asr-1.7b",
            "ocrModelPath": "C:/models/glm-ocr",
            "llmContextSize": 8192,
            "llmMaxTokens": 384,
            "asrLanguageHint": "Filipino",
            "asrReturnTimestamps": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["config"]["llmModelPath"] == "C:/models/qwen2.5-7b-instruct.gguf"
    assert body["config"]["llmLanguagePackPath"] == "C:/models/language_pack_ph.json"
    assert body["config"]["llmContextSize"] == 8192
    assert body["config"]["llmMaxTokens"] == 384
    assert body["config"]["asrLanguageHint"] == "Filipino"
    assert body["config"]["asrReturnTimestamps"] is True


def test_ai_runtime_smoke_runtime_unreachable() -> None:
    with patch.object(
        store.ai_runtime,
        "get_status",
        return_value={
            "accepted": True,
            "runtime": {
                "service": "mindi-ai-runtime",
                "reachable": False,
                "url": store.ai_runtime.base_url,
                "offlineMode": True,
                "lastError": "runtime_unreachable",
            },
            "features": {
                "llm": {
                    "enabled": True,
                    "ready": False,
                    "experimental": False,
                    "pathConfigured": False,
                    "provider": "llama.cpp",
                    "model": "Qwen/Qwen2.5-7B-Instruct",
                },
                "asr": {
                    "enabled": True,
                    "ready": False,
                    "experimental": True,
                    "pathConfigured": False,
                    "provider": "huggingface_local",
                    "model": "Qwen/Qwen3-ASR-1.7B",
                },
                "ocr": {
                    "enabled": True,
                    "ready": False,
                    "experimental": True,
                    "pathConfigured": False,
                    "provider": "huggingface_local",
                    "model": "zai-org/GLM-OCR",
                },
            },
            "config": store.ai_runtime._config,
        },
    ):
        response = client.post("/ops/ai/smoke", json={"includeLlm": True, "includeAsr": True, "includeOcr": True})
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is False
    assert body["reason"] == "runtime_unreachable"
    assert body["probes"]["llm"]["attempted"] is False
    assert body["probes"]["asr"]["attempted"] is False
    assert body["probes"]["ocr"]["attempted"] is False


def test_ai_runtime_smoke_success_with_mocked_probes(tmp_path: Path) -> None:
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"RIFF....WAVEfmt ")
    image = tmp_path / "sample.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )

    runtime_status = {
        "accepted": True,
        "runtime": {
            "service": "mindi-ai-runtime",
            "reachable": True,
            "url": store.ai_runtime.base_url,
            "offlineMode": True,
            "lastError": None,
        },
        "features": {
            "llm": {
                "enabled": True,
                "ready": True,
                "experimental": False,
                "pathConfigured": True,
                "provider": "llama.cpp",
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "lastLatencyMs": 41,
            },
            "asr": {
                "enabled": True,
                "ready": True,
                "experimental": True,
                "pathConfigured": True,
                "provider": "huggingface_local",
                "model": "Qwen/Qwen3-ASR-1.7B",
                "lastLatencyMs": 133,
            },
            "ocr": {
                "enabled": True,
                "ready": True,
                "experimental": True,
                "pathConfigured": True,
                "provider": "huggingface_local",
                "model": "zai-org/GLM-OCR",
                "lastLatencyMs": 88,
            },
        },
        "config": store.ai_runtime._config,
    }

    with patch.object(store.ai_runtime, "get_status", return_value=runtime_status):
        with patch.object(
            store.ai_runtime,
            "generate_reply",
            return_value={
                "accepted": True,
                "reason": "ok",
                "reply": "runtime llm ok",
                "provider": "llama.cpp",
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "latencyMs": 41,
            },
        ):
            with patch.object(
                store.ai_runtime,
                "transcribe",
                return_value={
                    "accepted": True,
                    "reason": "ok",
                    "text": "kumusta mundo",
                    "segments": [{"startMs": 0, "endMs": 900, "text": "kumusta mundo"}],
                    "provider": "huggingface_local",
                    "model": "Qwen/Qwen3-ASR-1.7B",
                    "degraded": False,
                },
            ):
                with patch.object(
                    store.ai_runtime,
                    "extract_ocr",
                    return_value={
                        "accepted": True,
                        "reason": "ok",
                        "text": "OCR sample",
                        "provider": "huggingface_local",
                        "model": "zai-org/GLM-OCR",
                        "degraded": False,
                        "latencyMs": 88,
                    },
                ):
                    response = client.post(
                        "/ops/ai/smoke",
                        json={
                            "includeLlm": True,
                            "includeAsr": True,
                            "includeOcr": True,
                            "llmPrompt": "hello",
                            "languageMode": "taglish",
                            "asrFilePath": str(audio),
                            "ocrImagePath": str(image),
                        },
                    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["reason"] == "ok"
    assert body["probes"]["llm"]["attempted"] is True
    assert body["probes"]["llm"]["accepted"] is True
    assert body["probes"]["llm"]["latencyMs"] == 41
    assert body["probes"]["asr"]["attempted"] is True
    assert body["probes"]["asr"]["accepted"] is True
    assert body["probes"]["asr"]["segmentCount"] == 1
    assert body["probes"]["asr"]["latencyMs"] == 133
    assert body["probes"]["ocr"]["attempted"] is True
    assert body["probes"]["ocr"]["accepted"] is True
    assert body["probes"]["ocr"]["latencyMs"] == 88


def test_dataset_prepare_missing_path() -> None:
    response = client.post(
        "/ops/intelligence/dataset/prepare",
        json={"datasetPath": "data/datasets/missing-ph-pretrain"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is False
    assert body["reason"] == "dataset_not_found"
    assert body["validationPassed"] is False
    assert body["languagePackLoaded"] is False


def test_dataset_prepare_success_and_loads_language_pack(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    sample_rows = "\n".join(
        f'{{"text": "Kamusta sample line {index} para sa Taglish adaptation."}}' for index in range(12)
    )
    (dataset_dir / "sample.jsonl").write_text(sample_rows, encoding="utf-8")
    output_dir = tmp_path / "artifacts"

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )

    response = client.post(
        "/ops/intelligence/dataset/prepare",
        json={"datasetPath": str(dataset_dir), "outputDir": str(output_dir)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["reason"] == "prepared"
    assert body["validationPassed"] is True
    assert body["validationIssues"] == []
    assert body["languagePackLoaded"] is True
    assert body["languagePackLoadReason"] == "loaded"
    assert body["languagePackPath"]
    assert Path(body["languagePackPath"]).exists() is True
    assert body["trainJsonlPath"]
    assert Path(body["trainJsonlPath"]).exists() is True
    assert body["valJsonlPath"]
    assert Path(body["valJsonlPath"]).exists() is True
    assert body["configPath"]
    assert Path(body["configPath"]).exists() is True
    assert body["manifestPath"]
    assert Path(body["manifestPath"]).exists() is True

    status = client.get("/ops/ai/status")
    assert status.status_code == 200
    status_body = status.json()
    assert status_body["config"]["llmLanguagePackPath"] == body["languagePackPath"]


def test_dataset_prepare_parquet_uses_filters_and_loads_language_pack(tmp_path: Path, monkeypatch) -> None:
    from mindi_agent import dataset_pipeline

    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = dataset_dir / "train.parquet"
    parquet_path.write_bytes(b"placeholder")
    output_dir = tmp_path / "artifacts"

    def fake_parquet_reader(
        file_path: Path,
        *,
        max_samples: int | None = None,
        languages: list[str] | None = None,
        quality_buckets: list[str] | None = None,
    ):
        assert file_path == parquet_path
        assert max_samples == 2
        assert languages == ["fil", "tgl"]
        assert quality_buckets == ["high"]
        return [
            "Kamusta MINDI Taglish helper para sa araw araw.",
            "Ayusin ang files nang safe at malinaw.",
        ]

    monkeypatch.setattr(dataset_pipeline, "_iter_parquet_text_samples", fake_parquet_reader)

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )

    response = client.post(
        "/ops/intelligence/dataset/prepare",
        json={
            "datasetPath": str(dataset_dir),
            "outputDir": str(output_dir),
            "maxSamples": 2,
            "languages": ["fil", "tgl"],
            "qualityBuckets": ["high"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["reason"] == "prepared"
    assert body["validationPassed"] is True
    assert body["languagePackLoaded"] is True
    assert body["sampleCount"] == 2
    assert Path(body["languagePackPath"]).exists() is True

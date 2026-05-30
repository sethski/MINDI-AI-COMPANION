from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
from unittest.mock import patch

from mindi_agent.main import app

client = TestClient(app)


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

    with patch("mindi_agent.store.subprocess.Popen") as mock_open:
        mock_open.return_value = None
        open_response = client.post(
            "/control/apps/action",
            json={"action": "open", "appId": "calc.exe", "confirm": True},
        )
        assert open_response.status_code == 200
        assert open_response.json()["accepted"] is True

    with patch("mindi_agent.store.subprocess.run") as mock_run:
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
    doc.write_text("MINDI local memory retrieval and chunk index", encoding="utf-8")

    client.post(
        "/control/permissions",
        json={"scope": "folder", "subject": str(tmp_path), "decision": "allow"},
    )

    imported = client.post("/memory/documents/import", json={"path": str(doc)})
    assert imported.status_code == 200
    imported_body = imported.json()
    assert imported_body["accepted"] is True
    assert imported_body["document"]["chunkCount"] >= 1

    searched = client.get("/memory/documents/search?query=chunk")
    assert searched.status_code == 200
    items = searched.json()["items"]
    assert any(item["sourcePath"] == str(doc.resolve()) for item in items)


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

    with patch("mindi_agent.store.extract_text_for_ocr") as mock_ocr:
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


def test_auto_index_scan_and_status(tmp_path: Path) -> None:
    doc = tmp_path / "watcher.md"
    marker = "autoindex-marker-7734"
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

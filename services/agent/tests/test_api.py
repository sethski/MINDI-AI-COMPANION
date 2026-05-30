from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone
from pathlib import Path
import base64
import io
import subprocess
from unittest.mock import patch
from uuid import uuid4
from PIL import Image, ImageDraw

from mindi_agent.main import app

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

    with patch("mindi_agent.store.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _MockUrlResponse(html)
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

    with patch("mindi_agent.store.subprocess.run", side_effect=fake_run):
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

    with patch("mindi_agent.store.subprocess.run", side_effect=fake_run):
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

    with patch("mindi_agent.store.urlopen") as mock_urlopen, patch(
        "mindi_agent.store.subprocess.run",
        side_effect=fake_run,
    ):
        mock_urlopen.return_value = _MockUrlResponse(html)
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

    with patch("mindi_agent.store.subprocess.run", side_effect=fake_run):
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

    with patch("mindi_agent.store.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _MockUrlResponse(html)
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

    with patch("mindi_agent.store.extract_text_for_ocr") as mock_ocr:
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
    assert reply.startswith("Status: ")

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

    with patch("mindi_agent.store.extract_text_for_ocr") as mock_ocr:
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

    with patch("mindi_agent.store.extract_text_for_ocr") as mock_ocr:
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

    with patch("mindi_agent.store.extract_text_for_ocr") as mock_ocr:
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

    with patch("mindi_agent.store.extract_text_for_ocr") as mock_ocr:
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

    with patch("mindi_agent.store.extract_text_for_ocr") as mock_ocr:
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

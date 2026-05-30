from fastapi.testclient import TestClient
from pathlib import Path

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

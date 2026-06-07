from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mindi_agent.agent_state import load_agent_state, save_agent_state
from mindi_agent.main import app, store
from mindi_agent.schemas import PermissionGrant, TaskItem, now_iso


def test_agent_state_roundtrip(tmp_path: Path) -> None:
    state_path = tmp_path / "agent_state.json"
    tasks = [TaskItem(id="task-1", title="Persist me", status="todo", source="manual")]
    grants = [
        PermissionGrant(
            id="grant-1",
            scope="folder",
            subject="data/inbox",
            decision="allow",
            createdAt=now_iso(),
        )
    ]

    save_agent_state(tasks, grants, state_path)
    loaded = load_agent_state(state_path)

    assert loaded is not None
    assert loaded.tasks[0].title == "Persist me"
    assert loaded.permission_grants[0].subject == "data/inbox"


def test_load_agent_state_missing_file(tmp_path: Path) -> None:
    assert load_agent_state(tmp_path / "missing.json") is None


def test_add_task_persists_via_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_path = tmp_path / "agent_state.json"
    monkeypatch.setattr(store, "agent_state_path", state_path)

    client = TestClient(app)
    created = client.post("/tasks", json={"title": "api-persist-task"}).json()
    assert created["title"] == "api-persist-task"
    assert state_path.exists()
    assert "api-persist-task" in state_path.read_text(encoding="utf-8")

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .schemas import PermissionGrant, TaskItem

DEFAULT_AGENT_STATE_PATH = Path("data/runtime/agent_state.json")


@dataclass
class AgentStateSnapshot:
    tasks: list[TaskItem]
    permission_grants: list[PermissionGrant]


def load_agent_state(path: Path | None = None) -> AgentStateSnapshot | None:
    target = path or DEFAULT_AGENT_STATE_PATH
    if not target.exists():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        tasks = [TaskItem.model_validate(item) for item in raw.get("tasks", [])]
        grants = [PermissionGrant.model_validate(item) for item in raw.get("permissionGrants", [])]
        return AgentStateSnapshot(tasks=tasks, permission_grants=grants)
    except Exception:
        return None


def save_agent_state(
    tasks: list[TaskItem],
    permission_grants: list[PermissionGrant],
    path: Path | None = None,
) -> None:
    target = path or DEFAULT_AGENT_STATE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "tasks": [task.model_dump() for task in tasks],
        "permissionGrants": [grant.model_dump() for grant in permission_grants],
    }
    target.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

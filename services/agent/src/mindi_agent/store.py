from dataclasses import dataclass, field
from pathlib import Path
from shutil import move
from time import time
from uuid import uuid4

from .schemas import (
    ActionLogItem,
    ActionTier,
    AddPermissionGrantRequest,
    AlertItem,
    AgentStatus,
    AssistantRequest,
    AssistantResponse,
    CreateTaskRequest,
    FileOrganizeItem,
    FileOrganizeRequest,
    FileOrganizeResponse,
    HubSnapshot,
    PermissionGrant,
    PolicyDecision,
    SyncQueueRequest,
    TaskItem,
    now_iso,
)


def _category_for_suffix(suffix: str) -> str:
    by_suffix = {
        ".png": "images",
        ".jpg": "images",
        ".jpeg": "images",
        ".gif": "images",
        ".webp": "images",
        ".pdf": "documents",
        ".docx": "documents",
        ".txt": "documents",
        ".md": "documents",
        ".csv": "data",
        ".json": "data",
        ".zip": "archives",
        ".7z": "archives",
    }
    return by_suffix.get(suffix.lower(), "other")


@dataclass
class RuntimeStore:
    started_at: float = field(default_factory=time)
    tasks: list[TaskItem] = field(default_factory=list)
    alerts: list[AlertItem] = field(default_factory=list)
    logs: list[ActionLogItem] = field(default_factory=list)
    sync_queue: list[dict] = field(default_factory=list)
    permission_grants: list[PermissionGrant] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Safe default for local file organization sandbox.
        self.permission_grants.append(
            PermissionGrant(
                id=str(uuid4()),
                scope="folder",
                subject="data",
                decision="allow",
                createdAt=now_iso(),
            )
        )

    def status(self) -> AgentStatus:
        return AgentStatus(
            state="ready",
            uptimeSeconds=max(0, int(time() - self.started_at)),
            listening=True,
            agentVersion="0.2.0",
            currentProfile="safe",
        )

    def snapshot(self) -> HubSnapshot:
        return HubSnapshot(
            status=self.status(),
            alerts=self.alerts[:5],
            tasks=self.tasks[:10],
            logs=self.logs[:10],
        )

    def policy_decision(self, request: AssistantRequest) -> PolicyDecision:
        text = request.text.lower()
        risky_terms = ["delete", "remove", "uninstall", "registry", "firewall", "credential"]
        if any(term in text for term in risky_terms):
            return PolicyDecision(
                allowed=False,
                tier=ActionTier.risky,
                reason="requires_confirmation_or_unlock",
                requiresUnlock=True,
            )
        return PolicyDecision(
            allowed=True,
            tier=ActionTier.read_only,
            reason="safe_read_or_chat",
            requiresUnlock=False,
        )

    def respond(self, request: AssistantRequest) -> AssistantResponse:
        decision = self.policy_decision(request)
        result = "allowed" if decision.allowed else "blocked"
        self.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=request.text,
                tier=decision.tier,
                result=result,
                reason=decision.reason,
                createdAt=now_iso(),
            ),
        )
        if decision.allowed:
            reply = "Acknowledged. I can proceed locally and keep this action in audit logs."
            suggestions = ["Create note", "Add task", "Show status"]
            status = "ready"
        else:
            reply = "Blocked for safety. Confirm or unlock before risky execution."
            suggestions = ["Explain risk", "Request confirmation", "Open safety panel"]
            status = "blocked"
        return AssistantResponse(
            reply=reply,
            decision=decision,
            suggestedActions=suggestions,
            status=status,
        )

    def add_task(self, request: CreateTaskRequest) -> TaskItem:
        task = TaskItem(
            id=str(uuid4()),
            title=request.title,
            dueAt=request.dueAt,
            status="todo",
            source="manual",
        )
        self.tasks.insert(0, task)
        return task

    def enqueue_sync(self, request: SyncQueueRequest) -> dict:
        item = {
            "id": str(uuid4()),
            "type": request.type,
            "payload": request.payload,
            "createdAt": now_iso(),
            "status": "queued",
        }
        self.sync_queue.insert(0, item)
        return item

    def list_permissions(self) -> list[PermissionGrant]:
        return self.permission_grants

    def add_permission(self, request: AddPermissionGrantRequest) -> PermissionGrant:
        grant = PermissionGrant(
            id=str(uuid4()),
            scope=request.scope,
            subject=request.subject,
            decision=request.decision,
            createdAt=now_iso(),
        )
        self.permission_grants.insert(0, grant)
        return grant

    def _is_path_allowed(self, path: Path) -> bool:
        normalized = path.resolve()
        grants = [g for g in self.permission_grants if g.scope == "folder"]
        denies = [Path(g.subject).resolve() for g in grants if g.decision == "deny"]
        allows = [Path(g.subject).resolve() for g in grants if g.decision == "allow"]

        if any(str(normalized).startswith(str(deny)) for deny in denies):
            return False
        if not allows:
            return False
        return any(str(normalized).startswith(str(allow)) for allow in allows)

    def file_organize(self, request: FileOrganizeRequest) -> FileOrganizeResponse:
        source = Path(request.sourceDir).resolve()
        target = Path(request.targetDir).resolve()

        if not source.exists() or not source.is_dir():
            return FileOrganizeResponse(
                accepted=False,
                reason="source_not_found",
                movedCount=0,
                items=[],
            )

        if not self._is_path_allowed(source) or not self._is_path_allowed(target):
            return FileOrganizeResponse(
                accepted=False,
                reason="folder_not_allowed",
                movedCount=0,
                items=[],
            )

        items: list[FileOrganizeItem] = []
        for child in source.iterdir():
            if child.is_file():
                category = _category_for_suffix(child.suffix)
                dest = target / category / child.name
                items.append(
                    FileOrganizeItem(
                        fileName=child.name,
                        sourcePath=str(child),
                        targetPath=str(dest),
                        category=category,
                    )
                )

        if request.mode == "apply":
            for item in items:
                destination = Path(item.targetPath)
                destination.parent.mkdir(parents=True, exist_ok=True)
                move(item.sourcePath, item.targetPath)
            reason = "applied"
        else:
            reason = "preview_only"

        self.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"file_organize:{request.mode}",
                tier=ActionTier.reversible,
                result="allowed",
                reason=reason,
                createdAt=now_iso(),
            ),
        )

        return FileOrganizeResponse(
            accepted=True,
            reason=reason,
            movedCount=len(items) if request.mode == "apply" else 0,
            items=items,
        )

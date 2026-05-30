from dataclasses import dataclass, field
from pathlib import Path
from shutil import move
import subprocess
from time import time
from uuid import uuid4

from .memory_db import MemoryDB
from .schemas import (
    AppControlRequest,
    AppControlResponse,
    ActionLogItem,
    ActionTier,
    AddPermissionGrantRequest,
    AlertItem,
    AgentStatus,
    AssistantRequest,
    AssistantResponse,
    CreateMemoryNoteRequest,
    CreateTaskRequest,
    DocumentImportRequest,
    DocumentImportResponse,
    DocumentSearchResponse,
    FileOrganizeItem,
    FileOrganizeRequest,
    FileOrganizeResponse,
    HubSnapshot,
    MemoryDocument,
    MemoryDocumentChunk,
    MemoryNote,
    MemorySearchResponse,
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
    memory_db: MemoryDB = field(default_factory=MemoryDB)

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
        self.permission_grants.append(
            PermissionGrant(
                id=str(uuid4()),
                scope="app",
                subject="notepad.exe",
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

    def list_allowed_apps(self) -> list[str]:
        app_grants = [grant for grant in self.permission_grants if grant.scope == "app"]
        denied = {grant.subject.lower() for grant in app_grants if grant.decision == "deny"}
        allowed = [grant.subject for grant in app_grants if grant.decision == "allow"]
        return [app for app in allowed if app.lower() not in denied]

    def _is_app_allowed(self, app_id: str) -> bool:
        return app_id.lower() in {app.lower() for app in self.list_allowed_apps()}

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

    def control_app(self, request: AppControlRequest) -> AppControlResponse:
        app_id = request.appId.strip()
        if not app_id:
            return AppControlResponse(
                accepted=False,
                reason="app_id_required",
                tier=ActionTier.read_only,
                requiresConfirmation=False,
            )

        if not self._is_app_allowed(app_id):
            return AppControlResponse(
                accepted=False,
                reason="app_not_allowlisted",
                tier=ActionTier.risky,
                requiresConfirmation=False,
            )

        tier = ActionTier.reversible
        requires_confirmation = False
        if request.action == "close":
            tier = ActionTier.risky
            if not request.confirm:
                return AppControlResponse(
                    accepted=False,
                    reason="confirmation_required_for_close",
                    tier=tier,
                    requiresConfirmation=True,
                )
            requires_confirmation = True

        try:
            if request.action == "open":
                subprocess.Popen(
                    ["cmd", "/c", "start", "", app_id],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                reason = "opened"
            elif request.action == "close":
                subprocess.run(
                    ["taskkill", "/IM", app_id, "/T"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                reason = "close_requested"
            else:
                # Windows focus control is layered for now; this is a readiness hook.
                reason = "focus_requested"
        except Exception as exc:
            return AppControlResponse(
                accepted=False,
                reason=f"app_control_failed:{exc.__class__.__name__}",
                tier=tier,
                requiresConfirmation=requires_confirmation,
            )

        self.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"app_control:{request.action}:{app_id}",
                tier=tier,
                result="allowed",
                reason=reason,
                createdAt=now_iso(),
            ),
        )

        return AppControlResponse(
            accepted=True,
            reason=reason,
            tier=tier,
            requiresConfirmation=requires_confirmation,
        )

    def add_memory_note(self, request: CreateMemoryNoteRequest) -> MemoryNote:
        note = self.memory_db.add_note(request)
        self.logs.insert(
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
        return note

    def list_memory_notes(self, limit: int = 50) -> list[MemoryNote]:
        return self.memory_db.list_notes(limit=limit)

    def search_memory(self, query: str, limit: int = 50) -> MemorySearchResponse:
        return MemorySearchResponse(query=query, items=self.memory_db.search_notes(query, limit=limit))

    def import_document(self, request: DocumentImportRequest) -> DocumentImportResponse:
        source = Path(request.path).resolve()
        if not source.exists() or not source.is_file():
            return DocumentImportResponse(accepted=False, reason="document_not_found")
        if not self._is_path_allowed(source):
            return DocumentImportResponse(accepted=False, reason="folder_not_allowed")

        try:
            document = self.memory_db.import_document(source)
        except ValueError as exc:
            return DocumentImportResponse(accepted=False, reason=str(exc))

        self.logs.insert(
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
        items = self.memory_db.search_documents(query=query, limit=limit)
        return DocumentSearchResponse(query=query, items=items)

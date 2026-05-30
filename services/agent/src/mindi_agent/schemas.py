from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ActionTier(str, Enum):
    read_only = "read_only"
    reversible = "reversible"
    risky = "risky"
    destructive = "destructive"


class PolicyDecision(BaseModel):
    allowed: bool
    tier: ActionTier
    reason: str
    requiresUnlock: bool


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str
    timestamp: str | None = None


class AssistantRequest(BaseModel):
    text: str
    mode: Literal["chat", "action"] = "chat"
    tab: str | None = None
    conversation: list[ChatMessage] | None = None


class AssistantResponse(BaseModel):
    reply: str
    decision: PolicyDecision
    suggestedActions: list[str]
    status: str


class AgentStatus(BaseModel):
    state: Literal["ready", "offline", "busy", "blocked"] = "ready"
    uptimeSeconds: int
    activeTask: str | None = None
    listening: bool = True
    agentVersion: str = "0.1.0"
    currentProfile: str = "safe"


class AlertItem(BaseModel):
    id: str
    severity: Literal["info", "warning", "critical"]
    title: str
    detail: str
    createdAt: str


class TaskItem(BaseModel):
    id: str
    externalId: str | None = None
    title: str
    status: Literal["todo", "in_progress", "done"] = "todo"
    dueAt: str | None = None
    recurrence: Literal["daily", "weekly"] | None = None
    nextRunAt: str | None = None
    source: Literal["manual", "assistant"] = "manual"


class ActionLogItem(BaseModel):
    id: str
    intent: str
    tier: ActionTier
    result: Literal["allowed", "blocked"]
    reason: str
    createdAt: str


class HubSnapshot(BaseModel):
    status: AgentStatus
    alerts: list[AlertItem] = Field(default_factory=list)
    tasks: list[TaskItem] = Field(default_factory=list)
    logs: list[ActionLogItem] = Field(default_factory=list)


class CreateTaskRequest(BaseModel):
    title: str
    dueAt: str | None = None
    recurrence: Literal["daily", "weekly"] | None = None


class SyncQueueRequest(BaseModel):
    type: Literal["chat", "action", "note", "scrape", "ocr"]
    payload: dict


class PermissionGrant(BaseModel):
    id: str
    scope: Literal["folder", "app", "domain", "action"]
    subject: str
    decision: Literal["allow", "deny"]
    createdAt: str


class AddPermissionGrantRequest(BaseModel):
    scope: Literal["folder", "app", "domain", "action"]
    subject: str
    decision: Literal["allow", "deny"]


class FileOrganizeRequest(BaseModel):
    sourceDir: str
    targetDir: str
    mode: Literal["preview", "apply"] = "preview"


class FileOrganizeItem(BaseModel):
    fileName: str
    sourcePath: str
    targetPath: str
    category: str


class FileOrganizeResponse(BaseModel):
    accepted: bool
    reason: str
    movedCount: int
    items: list[FileOrganizeItem]


class AppControlRequest(BaseModel):
    action: Literal["open", "focus", "close"]
    appId: str
    confirm: bool = False


class AppControlResponse(BaseModel):
    accepted: bool
    reason: str
    tier: ActionTier
    requiresConfirmation: bool


class MemoryNote(BaseModel):
    id: str
    title: str
    content: str
    tags: list[str]
    createdAt: str
    updatedAt: str


class CreateMemoryNoteRequest(BaseModel):
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)


class MemorySearchResponse(BaseModel):
    query: str
    items: list[MemoryNote]


class DocumentImportRequest(BaseModel):
    path: str


class MemoryDocument(BaseModel):
    id: str
    sourcePath: str
    title: str
    importedAt: str
    chunkCount: int


class MemoryDocumentChunk(BaseModel):
    id: str
    documentId: str
    sourcePath: str
    title: str
    text: str
    chunkIndex: int
    score: float


class DocumentImportResponse(BaseModel):
    accepted: bool
    reason: str
    document: MemoryDocument | None = None


class DocumentSearchResponse(BaseModel):
    query: str
    items: list[MemoryDocumentChunk]


class OcrImportRequest(BaseModel):
    path: str


class OcrImportResponse(BaseModel):
    accepted: bool
    reason: str
    document: MemoryDocument | None = None


class AutoIndexStatus(BaseModel):
    running: bool
    watchedPaths: list[str]
    lastScanAt: str | None = None
    indexedTotal: int = 0
    indexedLastRun: int = 0
    lastError: str | None = None


class SchedulerStatus(BaseModel):
    running: bool
    lastScanAt: str | None = None
    alertsTotal: int = 0
    alertsLastRun: int = 0
    trackedTasks: int = 0
    lastError: str | None = None


class TaskNextRunRequest(BaseModel):
    dueAt: str
    recurrence: Literal["daily", "weekly"]


class TaskNextRunResponse(BaseModel):
    accepted: bool
    reason: str
    nextRunAt: str | None = None


class TaskTimeParseRequest(BaseModel):
    text: str
    timezone: str | None = None


class TaskTimeParseResponse(BaseModel):
    accepted: bool
    reason: str
    dueAt: str | None = None


class CalendarExportRequest(BaseModel):
    fileName: str | None = None
    includeCompleted: bool = False


class CalendarExportResponse(BaseModel):
    accepted: bool
    reason: str
    filePath: str | None = None
    eventCount: int


class CalendarImportRequest(BaseModel):
    filePath: str


class CalendarImportResponse(BaseModel):
    accepted: bool
    reason: str
    importedCount: int
    createdCount: int
    updatedCount: int
    skippedCount: int


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")

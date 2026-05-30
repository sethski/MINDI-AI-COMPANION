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
    provider: str | None = None
    model: str | None = None
    degraded: bool = False
    fallbackReason: str | None = None


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
    reminderMinutesBefore: int | None = None
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


class TaskStatusUpdateRequest(BaseModel):
    status: Literal["todo", "in_progress", "done"]


class TaskUpdateRequest(BaseModel):
    title: str | None = None
    dueAt: str | None = None
    recurrence: Literal["daily", "weekly"] | None = None
    status: Literal["todo", "in_progress", "done"] | None = None


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
    ocrBackend: str | None = None
    ocrModel: str | None = None
    degraded: bool = False
    fallbackReason: str | None = None


class PerceptionAnalyzeRequest(BaseModel):
    path: str | None = None
    imageDataUrl: str | None = None
    includeOcr: bool = True
    maxBlocks: int = Field(default=25, ge=1, le=200)


class PerceptionUiBlock(BaseModel):
    x: int
    y: int
    width: int
    height: int
    kind: Literal["text_region"]
    confidence: float
    textSnippet: str | None = None


class PerceptionAnalyzeResponse(BaseModel):
    accepted: bool
    reason: str
    snapshotId: str | None = None
    storageRedacted: bool = False
    redactionCount: int = 0
    path: str | None = None
    imageWidth: int | None = None
    imageHeight: int | None = None
    ocrMode: str | None = None
    ocrError: str | None = None
    ocrBackend: str | None = None
    ocrModel: str | None = None
    degraded: bool = False
    fallbackReason: str | None = None
    text: str | None = None
    textLength: int = 0
    blocks: list[PerceptionUiBlock] = Field(default_factory=list)


class AiRuntimeFeatureStatus(BaseModel):
    enabled: bool = True
    ready: bool = False
    experimental: bool = False
    pathConfigured: bool = False
    provider: str = ""
    model: str = ""
    lastError: str | None = None


class AiRuntimeServiceStatus(BaseModel):
    service: str = "mindi-ai-runtime"
    reachable: bool = False
    url: str
    offlineMode: bool = True
    lastError: str | None = None


class AiRuntimeConfig(BaseModel):
    llmModelPath: str = ""
    asrModelPath: str = ""
    ocrModelPath: str = ""
    llmCommand: str = "llama-cli"
    llmContextSize: int = 4096
    llmMaxTokens: int = 256
    llmTemperature: float = 0.2
    llmThreads: int = 0
    llmProvider: str = "llama.cpp"
    asrProvider: str = "huggingface_local"
    ocrProvider: str = "huggingface_local"
    llmModel: str = "Qwen/Qwen2.5-7B-Instruct"
    asrModel: str = "Qwen/Qwen3-ASR-1.7B"
    ocrModel: str = "zai-org/GLM-OCR"
    asrLanguageHint: str | None = None
    asrReturnTimestamps: bool = False
    asrMaxTokens: int = 256
    offlineMode: bool = True
    experimentalAsr: bool = True
    experimentalOcr: bool = True


class AiRuntimeStatusResponse(BaseModel):
    accepted: bool
    runtime: AiRuntimeServiceStatus
    features: dict[Literal["llm", "asr", "ocr"], AiRuntimeFeatureStatus]
    config: AiRuntimeConfig


class AiRuntimeConfigUpdateRequest(BaseModel):
    llmModelPath: str | None = None
    asrModelPath: str | None = None
    ocrModelPath: str | None = None
    llmCommand: str | None = None
    llmContextSize: int | None = None
    llmMaxTokens: int | None = None
    llmTemperature: float | None = None
    llmThreads: int | None = None
    llmProvider: str | None = None
    asrProvider: str | None = None
    ocrProvider: str | None = None
    llmModel: str | None = None
    asrModel: str | None = None
    ocrModel: str | None = None
    asrLanguageHint: str | None = None
    asrReturnTimestamps: bool | None = None
    asrMaxTokens: int | None = None
    offlineMode: bool | None = None
    experimentalAsr: bool | None = None
    experimentalOcr: bool | None = None


class AsrSegment(BaseModel):
    startMs: int
    endMs: int
    text: str


class AsrTranscribeRequest(BaseModel):
    sourceType: Literal["file", "mic"]
    sourceValue: str
    languageHint: str | None = None
    returnTimestamps: bool | None = None


class AsrTranscribeResponse(BaseModel):
    accepted: bool
    reason: str
    text: str | None = None
    segments: list[AsrSegment] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    degraded: bool = False
    fallbackReason: str | None = None


class DatasetPrepareRequest(BaseModel):
    datasetPath: str
    outputDir: str | None = None


class DatasetPrepareResponse(BaseModel):
    accepted: bool
    reason: str
    datasetPath: str
    outputDir: str
    rawSamples: int
    trainSamples: int
    valSamples: int
    languagePackPath: str | None = None
    trainJsonlPath: str | None = None
    valJsonlPath: str | None = None
    configPath: str | None = None
    manifestPath: str | None = None


class PerceptionSnapshot(BaseModel):
    id: str
    sourcePath: str | None = None
    reason: str
    ocrMode: str | None = None
    text: str | None = None
    textLength: int = 0
    blockCount: int = 0
    imageWidth: int | None = None
    imageHeight: int | None = None
    createdAt: str


class PerceptionSnapshotSearchResponse(BaseModel):
    query: str
    items: list[PerceptionSnapshot]


class PerceptionPermissionStatus(BaseModel):
    screenSubject: str
    cameraSubject: str
    screenAllowed: bool
    cameraAllowed: bool
    screenDecision: Literal["allow", "deny", "unset"] = "unset"
    cameraDecision: Literal["allow", "deny", "unset"] = "unset"


class WebScrapeRequest(BaseModel):
    url: str
    maxChars: int = Field(default=3500, ge=200, le=15000)
    storeAsNote: bool = False


class WebScrapeResponse(BaseModel):
    accepted: bool
    reason: str
    url: str
    storageRedacted: bool = False
    redactionCount: int = 0
    title: str | None = None
    text: str | None = None
    textLength: int = 0
    links: list[str] = Field(default_factory=list)
    storedNoteId: str | None = None


class SecurityEvent(BaseModel):
    id: str
    severity: Literal["info", "warning", "critical"]
    title: str
    detail: str
    source: Literal["process_scan", "defender_service", "manual"]
    status: Literal["open", "resolved"] = "open"
    processName: str | None = None
    pid: int | None = None
    recoveryActions: list[str] = Field(default_factory=list)
    createdAt: str
    resolvedAt: str | None = None


class SecurityScanResponse(BaseModel):
    accepted: bool
    reason: str
    scannedProcessCount: int = 0
    newAlerts: int = 0
    events: list[SecurityEvent] = Field(default_factory=list)


class SecurityRecoveryRequest(BaseModel):
    eventId: str
    action: Literal["dismiss", "deny_app", "kill_process"]
    target: str | None = None
    confirm: bool = False


class SecurityRecoveryResponse(BaseModel):
    accepted: bool
    reason: str
    event: SecurityEvent | None = None


class AutomationChainStep(BaseModel):
    kind: Literal["web_scrape", "create_task", "create_note", "security_scan"]
    title: str | None = None
    url: str | None = None
    text: str | None = None
    dueAt: str | None = None
    recurrence: Literal["daily", "weekly"] | None = None
    storeAsNote: bool | None = None


class AutomationChainRequest(BaseModel):
    name: str
    continueOnFailure: bool = False
    steps: list[AutomationChainStep] = Field(default_factory=list)


class AutomationChainStepResult(BaseModel):
    index: int
    kind: str
    accepted: bool
    reason: str
    startedAt: str
    finishedAt: str
    recoveryHint: str | None = None
    detail: str | None = None


class AutomationChainResponse(BaseModel):
    accepted: bool
    reason: str
    name: str
    totalSteps: int
    completedSteps: int
    failedStepIndex: int | None = None
    steps: list[AutomationChainStepResult] = Field(default_factory=list)
    recoverySummary: str | None = None


class AlertFeedResponse(BaseModel):
    accepted: bool
    reason: str
    total: int
    critical: int = 0
    warning: int = 0
    info: int = 0
    items: list[AlertItem] = Field(default_factory=list)


class AlertActionRequest(BaseModel):
    alertId: str
    action: Literal["dismiss", "create_recovery_task", "export_report"]


class AlertActionResponse(BaseModel):
    accepted: bool
    reason: str
    createdTaskId: str | None = None
    reportPath: str | None = None


class PrivacyStatus(BaseModel):
    redactionEnabled: bool
    safeStorageDefault: bool
    sensitivePatternCount: int


class PrivacyUpdateRequest(BaseModel):
    redactionEnabled: bool


class IntelligenceStyleStatus(BaseModel):
    languageMode: Literal["english", "taglish", "tagalog"] = "english"
    slangEnabled: bool = False
    slangTerms: list[str] = Field(default_factory=list)


class IntelligenceStyleUpdateRequest(BaseModel):
    languageMode: Literal["english", "taglish", "tagalog"] | None = None
    slangEnabled: bool | None = None
    addSlangTerms: list[str] = Field(default_factory=list)
    resetSlangTerms: bool = False


class IntelligenceTuningConfig(BaseModel):
    preset: Literal["safe", "balanced", "companion"] = "safe"
    responseVerbosity: Literal["brief", "balanced", "detailed"] = "balanced"
    customRiskyTerms: list[str] = Field(default_factory=list)


class IntelligenceTuningStatus(BaseModel):
    active: IntelligenceTuningConfig
    pending: IntelligenceTuningConfig | None = None
    pendingVersion: str | None = None
    lastActiveEvalScore: float | None = None
    lastPendingEvalScore: float | None = None
    lastPendingEvalVersion: str | None = None
    minApplyScore: float = 1.0
    canApplyPending: bool = False


class IntelligenceTuningStageRequest(BaseModel):
    preset: Literal["safe", "balanced", "companion"] | None = None
    responseVerbosity: Literal["brief", "balanced", "detailed"] | None = None
    addCustomRiskyTerms: list[str] = Field(default_factory=list)
    resetCustomRiskyTerms: bool = False


class IntelligenceEvalRunRequest(BaseModel):
    scope: Literal["active", "pending", "learning"] = "active"
    terms: list[str] = Field(default_factory=list)


class IntelligenceEvalCaseResult(BaseModel):
    id: str
    accepted: bool
    score: float
    expected: str
    observed: str


class IntelligenceEvalRunResponse(BaseModel):
    accepted: bool
    reason: str
    runId: str
    createdAt: str
    scope: Literal["active", "pending", "learning"] = "active"
    gatePassed: bool = False
    totalCases: int
    passedCases: int
    score: float
    candidateVersion: str | None = None
    evaluatedTerms: list[str] = Field(default_factory=list)
    cases: list[IntelligenceEvalCaseResult] = Field(default_factory=list)


class IntelligenceTuningApplyResponse(BaseModel):
    accepted: bool
    reason: str
    status: IntelligenceTuningStatus


class IntelligenceLearningSourceRequest(BaseModel):
    noteId: str
    approved: bool = True


class IntelligenceLearningSourceSummary(BaseModel):
    noteId: str
    title: str
    tags: list[str] = Field(default_factory=list)
    approvedAt: str


class IntelligenceLearningCandidate(BaseModel):
    term: str
    sourceNoteId: str
    sourceTitle: str
    evidence: str


class IntelligenceLearningStatus(BaseModel):
    approvedSources: list[IntelligenceLearningSourceSummary] = Field(default_factory=list)
    candidates: list[IntelligenceLearningCandidate] = Field(default_factory=list)
    candidateVersion: str | None = None
    lastRunAt: str | None = None
    lastEvalScore: float | None = None
    lastEvalVersion: str | None = None
    lastAppliedAt: str | None = None
    minApplyScore: float = 1.0
    canApplyCandidates: bool = False


class IntelligenceLearningSourceResponse(BaseModel):
    accepted: bool
    reason: str
    status: IntelligenceLearningStatus


class IntelligenceLearningRunResponse(BaseModel):
    accepted: bool
    reason: str
    scannedSources: int
    candidateCount: int
    candidates: list[IntelligenceLearningCandidate] = Field(default_factory=list)
    status: IntelligenceLearningStatus


class IntelligenceLearningApplyRequest(BaseModel):
    terms: list[str] = Field(default_factory=list)
    enableSlang: bool = True


class IntelligenceLearningApplyResponse(BaseModel):
    accepted: bool
    reason: str
    appliedTerms: list[str] = Field(default_factory=list)
    style: IntelligenceStyleStatus
    status: IntelligenceLearningStatus


class IntelligenceAdaptationStatus(BaseModel):
    justified: bool
    recommendedMethod: Literal["none", "prompt_only", "lora"] = "none"
    reason: str
    totalEvalRuns: int = 0
    passedActiveRuns: int = 0
    passedPendingRuns: int = 0
    passedLearningRuns: int = 0
    latestActiveScore: float | None = None
    latestPendingScore: float | None = None
    latestLearningScore: float | None = None
    approvedSourceCount: int = 0
    appliedSlangCount: int = 0
    customRiskyTermCount: int = 0
    exportReady: bool = False
    lastExportAt: str | None = None
    lastExportPath: str | None = None


class IntelligenceAdaptationExportResponse(BaseModel):
    accepted: bool
    reason: str
    method: Literal["none", "prompt_only", "lora"] = "none"
    exportPath: str | None = None
    exampleCount: int = 0
    status: IntelligenceAdaptationStatus


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

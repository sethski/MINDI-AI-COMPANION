import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import re
from threading import Event, Lock, Thread
from time import monotonic, time
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo
from .agent_state import DEFAULT_AGENT_STATE_PATH, load_agent_state, save_agent_state
from .automation_service import AutomationService
from .file_service import FileService, category_for_suffix
from .launcher_service import LauncherService
from .proactive_service import ProactiveService
from .research_service import ResearchService
from .intelligence_service import (
    LEARNING_BLOCKED_TERMS,
    LEARNING_SOURCE_TAGS,
    SLANG_EXPLICIT_PATTERNS,
    IntelligenceService,
)
from .memory_service import (
    MemoryService,
    document_retrieval_confidence,
    document_retrieval_mode,
    should_attach_document_rag,
)
from .permission_service import (
    PERCEPTION_CAMERA_SUBJECT,
    PERCEPTION_SCREEN_SUBJECT,
    PermissionService,
)
from .privacy_utils import SENSITIVE_TEXT_PATTERNS, redact_sensitive_text
from .respond_service import RespondService
from .security_service import SUSPICIOUS_PROCESS_RULES, SecurityService, parse_tasklist_csv
from .task_service import TaskService
from .voice_service import VoiceService
from .web_service import WebService
from .scheduler_utils import (
    compute_next_run,
    format_utc,
    ics_dt,
    ics_escape,
    ics_unescape,
    parse_due_at,
    parse_ics_datetime,
    parse_ics_property,
    parse_ics_trigger_minutes,
    parse_time_component,
    resolve_timezone,
    unfold_ics_lines,
)
from .ai_runtime_client import LocalAiRuntimeClient
from .memory_db import MemoryDB
from .schemas import (
    AiRuntimeConfig,
    AiRuntimeConfigUpdateRequest,
    AiRuntimeSmokeRequest,
    AiRuntimeSmokeResponse,
    AiRuntimeFeatureStatus,
    AiSmokeProbeResult,
    AiRuntimeServiceStatus,
    AiRuntimeStatusResponse,
    AsrTranscribeRequest,
    AsrTranscribeResponse,
    TtsSynthesizeRequest,
    TtsSynthesizeResponse,
    OrbListeningRequest,
    OrbListeningResponse,
    AutoIndexStatus,
    SchedulerStatus,
    SecurityEvent,
    AutomationChainRequest,
    AutomationChainResponse,
    SecurityRecoveryRequest,
    SecurityRecoveryResponse,
    SecurityScanResponse,
    TaskNextRunRequest,
    TaskNextRunResponse,
    TaskTimeParseRequest,
    TaskTimeParseResponse,
    CalendarExportRequest,
    CalendarExportResponse,
    CalendarImportRequest,
    CalendarImportResponse,
    AppControlRequest,
    AppControlResponse,
    ActionLogItem,
    ActionTier,
    AddPermissionGrantRequest,
    AlertActionRequest,
    AlertActionResponse,
    AlertFeedResponse,
    AlertItem,
    AgentStatus,
    AssistantRequest,
    AssistantResponse,
    CreateMemoryNoteRequest,
    CreateTaskRequest,
    TaskStatusUpdateRequest,
    TaskUpdateRequest,
    DocumentImportRequest,
    DatasetPrepareRequest,
    DatasetPrepareResponse,
    DocumentImportResponse,
    DocumentSearchResponse,
    FileOrganizeItem,
    FileOrganizeRequest,
    FileOrganizeResponse,
    HubSnapshot,
    LauncherRequest,
    LauncherResponse,
    MemoryDocument,
    MemoryDocumentChunk,
    MemoryNote,
    MemoryGraphResponse,
    ChatHistoryMessage,
    ChatHistoryResponse,
    ProactiveNudge,
    ProactiveOrbActivityRequest,
    ProactiveStatus,
    MemorySearchResponse,
    OcrImportRequest,
    OcrImportResponse,
    PerceptionAnalyzeRequest,
    PerceptionAnalyzeResponse,
    PerceptionPermissionStatus,
    PerceptionSnapshot,
    PerceptionSnapshotSearchResponse,
    PerceptionUiBlock,
    IntelligenceEvalCaseResult,
    IntelligenceEvalRunRequest,
    IntelligenceEvalRunResponse,
    IntelligenceAdaptationExportResponse,
    IntelligenceAdaptationStatus,
    IntelligenceLearningApplyRequest,
    IntelligenceLearningApplyResponse,
    IntelligenceLearningCandidate,
    IntelligenceLearningRunResponse,
    IntelligenceLearningSourceRequest,
    IntelligenceLearningSourceResponse,
    IntelligenceLearningSourceSummary,
    IntelligenceLearningStatus,
    IntelligenceTuningApplyResponse,
    IntelligenceTuningConfig,
    IntelligenceTuningStageRequest,
    IntelligenceTuningStatus,
    IntelligenceStyleStatus,
    IntelligenceStyleUpdateRequest,
    PrivacyStatus,
    PrivacyUpdateRequest,
    PermissionGrant,
    PolicyDecision,
    RagTrace,
    SyncQueueRequest,
    TaskItem,
    WebScrapeRequest,
    WebScrapeResponse,
    now_iso,
)





class _IdempotencyCache:
    """Deduplicates retried create requests within a short window."""

    _TTL_S = 30.0

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            self._evict()
            entry = self._store.get(key)
            return entry[1] if entry is not None else None

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (monotonic(), value)

    def _evict(self) -> None:
        now = monotonic()
        expired = [k for k, (ts, _) in self._store.items() if now - ts > self._TTL_S]
        for k in expired:
            del self._store[k]


@dataclass
class RuntimeStore:
    started_at: float = field(default_factory=time)
    tasks: list[TaskItem] = field(default_factory=list)
    alerts: list[AlertItem] = field(default_factory=list)
    logs: list[ActionLogItem] = field(default_factory=list)
    sync_queue: list[dict] = field(default_factory=list)
    permission_grants: list[PermissionGrant] = field(default_factory=list)
    memory_db: MemoryDB = field(default_factory=MemoryDB)
    auto_index_stop: Event = field(default_factory=Event)
    auto_index_thread: Thread | None = field(default=None, init=False)
    auto_index_last_scan: str | None = None
    auto_index_last_error: str | None = None
    auto_index_indexed_total: int = 0
    auto_index_indexed_last_run: int = 0
    auto_index_seen_mtime: dict[str, int] = field(default_factory=dict)
    scheduler_stop: Event = field(default_factory=Event)
    scheduler_thread: Thread | None = field(default=None, init=False)
    scheduler_last_scan: str | None = None
    scheduler_last_error: str | None = None
    scheduler_alerts_total: int = 0
    scheduler_alerts_last_run: int = 0
    scheduler_alerted_due: dict[str, str] = field(default_factory=dict)
    security_events: list[SecurityEvent] = field(default_factory=list)
    security_last_scan: str | None = None
    security_last_error: str | None = None
    privacy_redaction_enabled: bool = True
    intelligence_language_mode: str = "english"
    intelligence_slang_enabled: bool = False
    intelligence_slang_terms: list[str] = field(default_factory=list)
    intelligence_tuning_preset: str = "safe"
    intelligence_tuning_verbosity: str = "balanced"
    intelligence_tuning_custom_risky_terms: list[str] = field(default_factory=list)
    intelligence_tuning_pending_preset: str | None = None
    intelligence_tuning_pending_verbosity: str | None = None
    intelligence_tuning_pending_custom_risky_terms: list[str] = field(default_factory=list)
    intelligence_tuning_pending_version: str | None = None
    intelligence_tuning_last_active_eval_score: float | None = None
    intelligence_tuning_last_pending_eval_score: float | None = None
    intelligence_tuning_last_pending_eval_version: str | None = None
    intelligence_eval_history: list[IntelligenceEvalRunResponse] = field(default_factory=list)
    intelligence_learning_sources: dict[str, IntelligenceLearningSourceSummary] = field(default_factory=dict)
    intelligence_learning_candidates: list[IntelligenceLearningCandidate] = field(default_factory=list)
    intelligence_learning_candidate_version: str | None = None
    intelligence_learning_last_run_at: str | None = None
    intelligence_learning_last_eval_score: float | None = None
    intelligence_learning_last_eval_version: str | None = None
    intelligence_learning_last_eval_signature: str | None = None
    intelligence_learning_last_applied_at: str | None = None
    intelligence_adaptation_last_export_at: str | None = None
    intelligence_adaptation_last_export_path: str | None = None
    ai_runtime: LocalAiRuntimeClient = field(default_factory=LocalAiRuntimeClient)
    orb_listening: bool = False
    respond_lock: Lock = field(default_factory=Lock)
    _idempotency_cache: _IdempotencyCache = field(default_factory=_IdempotencyCache)
    agent_state_path: Path = field(default_factory=lambda: DEFAULT_AGENT_STATE_PATH)

    def __post_init__(self) -> None:
        self._security_svc: SecurityService = SecurityService(self)
        self._web_svc: WebService = WebService(self)
        self._file_svc: FileService = FileService(self)
        self._memory_svc: MemoryService = MemoryService(self)
        self._intel_svc: IntelligenceService = IntelligenceService(self)
        self._voice_svc: VoiceService = VoiceService(self)
        self._task_svc: TaskService = TaskService(self)
        self._perm_svc: PermissionService = PermissionService(self)
        self._automation_svc: AutomationService = AutomationService(self)
        self._launcher_svc: LauncherService = LauncherService(self)
        self._research_svc: ResearchService = ResearchService(self)
        self._proactive_svc: ProactiveService = ProactiveService(self)
        self._respond_svc: RespondService = RespondService(self)
        snapshot = load_agent_state(self.agent_state_path)
        if snapshot is not None:
            self.tasks = snapshot.tasks
            self.permission_grants = snapshot.permission_grants
        else:
            self._seed_default_permissions()
        self.start_auto_indexer()
        self.start_scheduler()

    def _seed_default_permissions(self) -> None:
        # Safe defaults for local file organization and app control on first run.
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
        home = Path.home()
        for folder_name in ("Documents", "Desktop", "Downloads"):
            folder = home / folder_name
            if folder.exists():
                self.permission_grants.append(
                    PermissionGrant(
                        id=str(uuid4()),
                        scope="folder",
                        subject=str(folder),
                        decision="allow",
                        createdAt=now_iso(),
                    )
                )

    def _persist_durable_state(self) -> None:
        save_agent_state(self.tasks, self.permission_grants, self.agent_state_path)

    def status(self) -> AgentStatus:
        return AgentStatus(
            state="ready",
            uptimeSeconds=max(0, int(time() - self.started_at)),
            listening=self.orb_listening,
            agentVersion="0.2.0",
            currentProfile="safe",
        )

    def set_orb_listening(self, request: OrbListeningRequest) -> OrbListeningResponse:
        self.orb_listening = bool(request.listening)
        return OrbListeningResponse(accepted=True, listening=self.orb_listening)

    def append_debug_session_log(self, payload: dict[str, object]) -> dict[str, bool]:
        line = json.dumps(payload, ensure_ascii=False)
        repo_root = Path(__file__).resolve().parents[4]
        paths = [
            repo_root / ".cursor" / "debug-ddb680.log",
            repo_root / "debug-ddb680.log",
            Path.home() / "AppData" / "Roaming" / "com.mindi.desktop" / "debug-ddb680.log",
        ]
        for path in paths:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(f"{line}\n")
            except OSError:
                continue
        return {"ok": True}

    def snapshot(self) -> HubSnapshot:
        return HubSnapshot(
            status=self.status(),
            alerts=self.alerts[:5],
            tasks=self.tasks[:10],
            logs=self.logs[:10],
        )

    def ai_runtime_status(self) -> AiRuntimeStatusResponse:
        payload = self.ai_runtime.get_status()
        runtime_payload = payload.get("runtime", {})
        feature_payload = payload.get("features", {})
        config_payload = payload.get("config", {})
        return AiRuntimeStatusResponse(
            accepted=bool(payload.get("accepted", True)),
            runtime=AiRuntimeServiceStatus(
                service=str(runtime_payload.get("service", "mindi-ai-runtime")),
                reachable=bool(runtime_payload.get("reachable", False)),
                url=str(runtime_payload.get("url", self.ai_runtime.base_url)),
                offlineMode=bool(runtime_payload.get("offlineMode", True)),
                lastError=runtime_payload.get("lastError"),
            ),
            features={
                "llm": AiRuntimeFeatureStatus(**feature_payload.get("llm", {})),
                "asr": AiRuntimeFeatureStatus(**feature_payload.get("asr", {})),
                "ocr": AiRuntimeFeatureStatus(**feature_payload.get("ocr", {})),
            },
            config=AiRuntimeConfig(**config_payload),
        )

    def update_ai_runtime_config(self, request: AiRuntimeConfigUpdateRequest) -> AiRuntimeStatusResponse:
        update = request.model_dump(exclude_none=True)
        payload = self.ai_runtime.update_config(update)
        self.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent="ai_runtime_config_update",
                tier=ActionTier.reversible,
                result="allowed",
                reason="updated",
                createdAt=now_iso(),
            ),
        )
        runtime_payload = payload.get("runtime", {})
        feature_payload = payload.get("features", {})
        config_payload = payload.get("config", {})
        return AiRuntimeStatusResponse(
            accepted=bool(payload.get("accepted", True)),
            runtime=AiRuntimeServiceStatus(
                service=str(runtime_payload.get("service", "mindi-ai-runtime")),
                reachable=bool(runtime_payload.get("reachable", False)),
                url=str(runtime_payload.get("url", self.ai_runtime.base_url)),
                offlineMode=bool(runtime_payload.get("offlineMode", True)),
                lastError=runtime_payload.get("lastError"),
            ),
            features={
                "llm": AiRuntimeFeatureStatus(**feature_payload.get("llm", {})),
                "asr": AiRuntimeFeatureStatus(**feature_payload.get("asr", {})),
                "ocr": AiRuntimeFeatureStatus(**feature_payload.get("ocr", {})),
            },
            config=AiRuntimeConfig(**config_payload),
        )

    def ai_runtime_smoke(self, request: AiRuntimeSmokeRequest) -> AiRuntimeSmokeResponse:
        started_at = now_iso()
        status = self.ai_runtime_status()
        llm_probe = AiSmokeProbeResult(
            attempted=False,
            accepted=False,
            reason="not_requested",
            degraded=False,
        )
        asr_probe = AiSmokeProbeResult(
            attempted=False,
            accepted=False,
            reason="not_requested",
            degraded=False,
        )
        ocr_probe = AiSmokeProbeResult(
            attempted=False,
            accepted=False,
            reason="not_requested",
            degraded=False,
        )

        if not status.runtime.reachable:
            finished_at = now_iso()
            return AiRuntimeSmokeResponse(
                accepted=False,
                reason="runtime_unreachable",
                startedAt=started_at,
                finishedAt=finished_at,
                probes={
                    "llm": llm_probe,
                    "asr": asr_probe,
                    "ocr": ocr_probe,
                },
            )

        if request.includeLlm:
            llm_probe.attempted = True
            llm_result = self.ai_runtime.generate_reply(
                prompt=(request.llmPrompt or "").strip(),
                language_mode=request.languageMode,
            )
            llm_probe.accepted = bool(llm_result.get("accepted", False))
            llm_probe.reason = str(llm_result.get("reason", "runtime_unavailable"))
            llm_probe.provider = llm_result.get("provider")
            llm_probe.model = llm_result.get("model")
            llm_probe.latencyMs = int(llm_result.get("latencyMs", 0)) if llm_result.get("latencyMs") is not None else None
            llm_probe.degraded = not llm_probe.accepted
            llm_probe.fallbackReason = None if llm_probe.accepted else llm_probe.reason
            if llm_probe.accepted:
                llm_probe.textPreview = str(llm_result.get("reply", ""))[:180]

        if request.includeAsr:
            asr_probe.attempted = True
            source_value = (request.asrFilePath or "").strip()
            if not source_value:
                asr_probe.reason = "asr_file_path_required"
            else:
                asr_response = self.transcribe_audio(
                    AsrTranscribeRequest(
                        sourceType="file",
                        sourceValue=source_value,
                        languageHint=request.asrLanguageHint,
                        returnTimestamps=True,
                    )
                )
                asr_probe.accepted = asr_response.accepted
                asr_probe.reason = asr_response.reason
                asr_probe.provider = asr_response.provider
                asr_probe.model = asr_response.model
                asr_probe.degraded = asr_response.degraded
                asr_probe.fallbackReason = asr_response.fallbackReason
                asr_probe.textPreview = (asr_response.text or "")[:180] if asr_response.text else None
                asr_probe.segmentCount = len(asr_response.segments)
                status_after_asr = self.ai_runtime_status()
                asr_probe.latencyMs = status_after_asr.features["asr"].lastLatencyMs

        if request.includeOcr:
            ocr_probe.attempted = True
            ocr_path_raw = (request.ocrImagePath or "").strip()
            if not ocr_path_raw:
                ocr_probe.reason = "ocr_image_path_required"
            else:
                source = Path(ocr_path_raw).resolve()
                if not source.exists() or not source.is_file():
                    ocr_probe.reason = "image_not_found"
                elif not self._is_path_allowed(source):
                    ocr_probe.reason = "image_file_not_allowed"
                else:
                    payload = self.ai_runtime.extract_ocr(path=source)
                    ocr_probe.accepted = bool(payload.get("accepted", False))
                    ocr_probe.reason = str(payload.get("reason", "runtime_unavailable"))
                    ocr_probe.provider = payload.get("provider")
                    ocr_probe.model = payload.get("model")
                    ocr_probe.degraded = bool(payload.get("degraded", not ocr_probe.accepted))
                    ocr_probe.fallbackReason = (
                        None if ocr_probe.accepted else str(payload.get("fallbackReason") or payload.get("reason"))
                    )
                    ocr_text = str(payload.get("text", "") or "")
                    ocr_probe.textPreview = ocr_text[:180] if ocr_text else None
                    if payload.get("latencyMs") is not None:
                        ocr_probe.latencyMs = int(payload.get("latencyMs"))
                    else:
                        status_after_ocr = self.ai_runtime_status()
                        ocr_probe.latencyMs = status_after_ocr.features["ocr"].lastLatencyMs

        all_ok = True
        for probe in (llm_probe, asr_probe, ocr_probe):
            if probe.attempted and not probe.accepted:
                all_ok = False
                break
        finished_at = now_iso()
        return AiRuntimeSmokeResponse(
            accepted=all_ok,
            reason="ok" if all_ok else "one_or_more_probes_failed",
            startedAt=started_at,
            finishedAt=finished_at,
            probes={
                "llm": llm_probe,
                "asr": asr_probe,
                "ocr": ocr_probe,
            },
        )

    def transcribe_audio(self, request: AsrTranscribeRequest) -> AsrTranscribeResponse:
        return self._voice_svc.transcribe_audio(request)

    def synthesize_speech(self, request: TtsSynthesizeRequest) -> TtsSynthesizeResponse:
        return self._voice_svc.synthesize_speech(request)

    def prepare_intelligence_dataset(self, request: DatasetPrepareRequest) -> DatasetPrepareResponse:
        return self._intel_svc.prepare_intelligence_dataset(request)

    def _active_tuning_config(self) -> IntelligenceTuningConfig:
        return self._intel_svc.active_tuning_config()

    def _pending_tuning_config(self) -> IntelligenceTuningConfig | None:
        return self._intel_svc.pending_tuning_config()

    @staticmethod
    def _normalized_risky_terms(config: IntelligenceTuningConfig) -> set[str]:
        return IntelligenceService.normalized_risky_terms(config)

    def policy_decision(
        self, request: AssistantRequest, config: IntelligenceTuningConfig | None = None
    ) -> PolicyDecision:
        return self._respond_svc.policy_decision(request, config=config)

    def _build_wake_invoke_prompt(self) -> str:
        return self._respond_svc._build_wake_invoke_prompt()

    @staticmethod
    def _is_casual_chat_request(text: str) -> bool:
        return RespondService.is_casual_chat_request(text)

    def respond(self, request: AssistantRequest) -> AssistantResponse:
        return self._respond_svc.respond(request)

    def stream_respond(self, request: AssistantRequest):
        return self._respond_svc.stream_respond(request)

    def _respond_unlocked(self, request: AssistantRequest) -> AssistantResponse:
        return self._respond_svc._respond_unlocked(request)

    def _style_reply(
        self,
        reply: str,
        *,
        decision: PolicyDecision,
        config: IntelligenceTuningConfig | None = None,
        language_mode: str | None = None,
        slang_enabled: bool | None = None,
        slang_terms: list[str] | None = None,
    ) -> str:
        return self._respond_svc._style_reply(
            reply, decision=decision, config=config,
            language_mode=language_mode, slang_enabled=slang_enabled, slang_terms=slang_terms,
        )

    def add_task(self, request: CreateTaskRequest) -> TaskItem:
        return self._task_svc.add_task(request)

    def update_task_status(self, task_id: str, request: TaskStatusUpdateRequest) -> TaskItem | None:
        return self._task_svc.update_task_status(task_id, request)

    def update_task(self, task_id: str, request: TaskUpdateRequest) -> TaskItem | None:
        return self._task_svc.update_task(task_id, request)

    def delete_task(self, task_id: str) -> TaskItem | None:
        return self._task_svc.delete_task(task_id)

    def enqueue_sync(self, request: SyncQueueRequest) -> dict:
        return self._task_svc.enqueue_sync(request)

    def list_permissions(self) -> list[PermissionGrant]:
        return self._perm_svc.list_permissions()

    def add_permission(self, request: AddPermissionGrantRequest) -> PermissionGrant:
        return self._perm_svc.add_permission(request)

    @staticmethod
    def _subject_matches(grant_subject: str, target_subject: str) -> bool:
        return PermissionService.subject_matches(grant_subject, target_subject)

    def _resolve_action_permission_decision(self, subject: str) -> str:
        return self._perm_svc.resolve_action_permission(subject)

    def _is_action_allowed(self, subject: str) -> bool:
        return self._perm_svc.is_action_allowed(subject)

    def perception_permission_status(self) -> PerceptionPermissionStatus:
        return self._perm_svc.perception_permission_status()

    def privacy_status(self) -> PrivacyStatus:
        return self._perm_svc.privacy_status()

    def update_privacy(self, request: PrivacyUpdateRequest) -> PrivacyStatus:
        return self._perm_svc.update_privacy(request)

    def intelligence_style_status(self) -> IntelligenceStyleStatus:
        return self._intel_svc.intelligence_style_status()

    def _latest_eval_score(self, scope: str) -> float | None:
        return self._intel_svc._latest_eval_score(scope)

    def intelligence_adaptation_status(self) -> IntelligenceAdaptationStatus:
        return self._intel_svc.intelligence_adaptation_status()

    def intelligence_tuning_status(self) -> IntelligenceTuningStatus:
        return self._intel_svc.intelligence_tuning_status()

    @staticmethod
    def _learning_terms_signature(terms: list[str]) -> str:
        from .intelligence_service import _learning_terms_signature
        return _learning_terms_signature(terms)

    def _clear_learning_eval_gate(self) -> None:
        self._intel_svc._clear_learning_eval_gate()

    def _set_learning_candidates(self, candidates: list[IntelligenceLearningCandidate]) -> None:
        self._intel_svc._set_learning_candidates(candidates)

    def _selected_learning_terms(self, request_terms: list[str]) -> list[str]:
        return self._intel_svc._selected_learning_terms(request_terms)

    def _note_is_learning_source_eligible(self, note: MemoryNote) -> bool:
        return self._intel_svc._note_is_learning_source_eligible(note)

    def _learning_candidate_allowed(self, term: str) -> bool:
        return self._intel_svc._learning_candidate_allowed(term)

    def intelligence_learning_status(self) -> IntelligenceLearningStatus:
        return self._intel_svc.intelligence_learning_status()

    def update_intelligence_style(self, request: IntelligenceStyleUpdateRequest) -> IntelligenceStyleStatus:
        return self._intel_svc.update_intelligence_style(request)

    def stage_intelligence_tuning(self, request: IntelligenceTuningStageRequest) -> IntelligenceTuningStatus:
        return self._intel_svc.stage_intelligence_tuning(request)

    def discard_intelligence_tuning(self) -> IntelligenceTuningStatus:
        return self._intel_svc.discard_intelligence_tuning()

    def run_intelligence_eval(
        self, request: IntelligenceEvalRunRequest | None = None
    ) -> IntelligenceEvalRunResponse:
        return self._intel_svc.run_intelligence_eval(request)

    def list_intelligence_eval_history(self, limit: int = 20) -> list[IntelligenceEvalRunResponse]:
        return self._intel_svc.list_intelligence_eval_history(limit=limit)

    def update_intelligence_learning_source(
        self, request: IntelligenceLearningSourceRequest
    ) -> IntelligenceLearningSourceResponse:
        return self._intel_svc.update_intelligence_learning_source(request)

    @staticmethod
    def _extract_slang_candidates_from_text(text: str) -> list[tuple[str, str]]:
        return IntelligenceService.extract_slang_candidates_from_text(text)

    def run_intelligence_learning(self) -> IntelligenceLearningRunResponse:
        return self._intel_svc.run_intelligence_learning()

    def apply_intelligence_learning(
        self, request: IntelligenceLearningApplyRequest
    ) -> IntelligenceLearningApplyResponse:
        return self._intel_svc.apply_intelligence_learning(request)

    def apply_intelligence_tuning(self) -> IntelligenceTuningApplyResponse:
        return self._intel_svc.apply_intelligence_tuning()

    def export_intelligence_adaptation(self) -> IntelligenceAdaptationExportResponse:
        return self._intel_svc.export_intelligence_adaptation()

    def _redact_sensitive_text(self, text: str) -> tuple[str, int]:
        return redact_sensitive_text(text)

    def list_allowed_apps(self) -> list[str]:
        return self._web_svc.list_allowed_apps()

    def _is_app_allowed(self, app_id: str) -> bool:
        return self._web_svc.is_app_allowed(app_id)

    def _resolve_domain_permission_decision(self, hostname: str) -> str:
        return self._web_svc.resolve_domain_permission(hostname)

    def _is_domain_allowed(self, hostname: str) -> bool:
        return self._web_svc.is_domain_allowed(hostname)

    def _persist_mic_payload(self, payload: str) -> str | None:
        return self._voice_svc._persist_mic_payload(payload)

    def _is_path_allowed(self, path: Path) -> bool:
        return self._perm_svc.is_path_allowed(path)

    def file_organize(self, request: FileOrganizeRequest) -> FileOrganizeResponse:
        return self._file_svc.file_organize(request)

    def scrape_web(self, request: WebScrapeRequest) -> WebScrapeResponse:
        return self._web_svc.scrape_web(request)

    def run_automation_chain(self, request: AutomationChainRequest) -> AutomationChainResponse:
        return self._automation_svc.run_automation_chain(request)

    def alerts_feed(self, limit: int = 25) -> AlertFeedResponse:
        return self._automation_svc.alerts_feed(limit=limit)

    def alerts_action(self, request: AlertActionRequest) -> AlertActionResponse:
        return self._automation_svc.alerts_action(request)

    @staticmethod
    def _parse_tasklist_csv(stdout: str) -> list[tuple[str, int | None]]:
        return parse_tasklist_csv(stdout)

    def _create_security_event(
        self,
        *,
        severity: str,
        title: str,
        detail: str,
        source: str,
        process_name: str | None = None,
        pid: int | None = None,
        recovery_actions: list[str] | None = None,
    ) -> SecurityEvent:
        return self._security_svc.create_security_event(
            severity=severity,
            title=title,
            detail=detail,
            source=source,
            process_name=process_name,
            pid=pid,
            recovery_actions=recovery_actions,
        )

    def list_security_events(self, status: str = "open", limit: int = 25) -> list[SecurityEvent]:
        return self._security_svc.list_security_events(status=status, limit=limit)

    def scan_security(self) -> SecurityScanResponse:
        return self._security_svc.scan_security()

    def recover_security_event(self, request: SecurityRecoveryRequest) -> SecurityRecoveryResponse:
        return self._security_svc.recover_security_event(request)

    def control_app(self, request: AppControlRequest) -> AppControlResponse:
        return self._automation_svc.control_app(request)

    def add_memory_note(self, request: CreateMemoryNoteRequest) -> MemoryNote:
        return self._memory_svc.add_memory_note(request)

    def list_memory_notes(self, limit: int = 50) -> list[MemoryNote]:
        return self._memory_svc.list_memory_notes(limit=limit)

    def search_memory(self, query: str, limit: int = 50) -> MemorySearchResponse:
        return self._memory_svc.search_memory(query=query, limit=limit)

    def list_perception_snapshots(self, limit: int = 20) -> list[PerceptionSnapshot]:
        return self._memory_svc.list_perception_snapshots(limit=limit)

    def search_perception_snapshots(self, query: str, limit: int = 20) -> PerceptionSnapshotSearchResponse:
        return self._memory_svc.search_perception_snapshots(query=query, limit=limit)

    def import_document(self, request: DocumentImportRequest) -> DocumentImportResponse:
        return self._memory_svc.import_document(request)

    def search_documents(self, query: str, limit: int = 20) -> DocumentSearchResponse:
        return self._memory_svc.search_documents(query=query, limit=limit)

    @staticmethod
    def _document_retrieval_mode(items: list[MemoryDocumentChunk]) -> str:
        return document_retrieval_mode(items)

    @staticmethod
    def _document_retrieval_confidence(items: list[MemoryDocumentChunk]) -> float:
        return document_retrieval_confidence(items)

    @staticmethod
    def _should_attach_document_rag(text: str, items: list[MemoryDocumentChunk]) -> bool:
        return should_attach_document_rag(text, items)

    def import_ocr_document(self, request: OcrImportRequest) -> OcrImportResponse:
        return self._memory_svc.import_ocr_document(request)

    def analyze_screen(self, request: PerceptionAnalyzeRequest) -> PerceptionAnalyzeResponse:
        return self._memory_svc.analyze_screen(request)

    def _watched_paths(self) -> list[Path]:
        return self._memory_svc.watched_paths()

    def auto_index_status(self) -> AutoIndexStatus:
        return self._memory_svc.auto_index_status()

    def start_auto_indexer(self) -> None:
        self._memory_svc.start_auto_indexer()

    def _auto_index_loop(self) -> None:
        self._memory_svc._auto_index_loop()

    def auto_index_scan_once(self, *, include_user_folders: bool = False) -> AutoIndexStatus:
        return self._memory_svc.auto_index_scan_once(include_user_folders=include_user_folders)

    def get_memory_graph(self) -> MemoryGraphResponse:
        return self._memory_svc.get_memory_graph()

    def get_chat_history(self, *, limit: int = 100) -> ChatHistoryResponse:
        rows = self.memory_db.list_chat_messages(limit=limit)
        return ChatHistoryResponse(
            messages=[
                ChatHistoryMessage(
                    id=row["id"],
                    role=row["role"],
                    content=row["content"],
                    ts=row["ts"],
                    meta=row.get("meta"),
                )
                for row in rows
            ]
        )

    def append_chat_turn(self, *, user_text: str, assistant_text: str, meta: str | None = None) -> None:
        trimmed_user = user_text.strip()
        trimmed_assistant = assistant_text.strip()
        if not trimmed_user:
            return
        self.memory_db.append_chat_message(role="user", content=trimmed_user)
        if trimmed_assistant:
            self.memory_db.append_chat_message(role="assistant", content=trimmed_assistant, meta=meta)

    def clear_chat_history(self) -> int:
        return self.memory_db.clear_chat_messages()

    def proactive_status(self) -> ProactiveStatus:
        return self._proactive_svc.status()

    def proactive_set_orb_idle(self, request: ProactiveOrbActivityRequest) -> ProactiveStatus:
        return self._proactive_svc.set_orb_idle(request.idle)

    def proactive_consume_nudges(self, *, limit: int = 3) -> list[ProactiveNudge]:
        return self._proactive_svc.consume_nudges(limit=limit)

    def proactive_run_briefing(self) -> ProactiveNudge:
        return self._proactive_svc.run_briefing_now("morning")

    def open_launcher(self, request: LauncherRequest) -> LauncherResponse:
        if request.kind == "url":
            return self._launcher_svc.open_url(request)
        return self._launcher_svc.open_file(request)

    def scheduler_status(self) -> SchedulerStatus:
        return SchedulerStatus(
            running=self.scheduler_thread is not None and self.scheduler_thread.is_alive(),
            lastScanAt=self.scheduler_last_scan,
            alertsTotal=self.scheduler_alerts_total,
            alertsLastRun=self.scheduler_alerts_last_run,
            trackedTasks=len(self.tasks),
            lastError=self.scheduler_last_error,
        )

    def start_scheduler(self) -> None:
        if self.scheduler_thread is not None and self.scheduler_thread.is_alive():
            return
        self.scheduler_stop.clear()
        self.scheduler_thread = Thread(target=self._scheduler_loop, daemon=True)
        self.scheduler_thread.start()

    def _scheduler_loop(self) -> None:
        while not self.scheduler_stop.is_set():
            self.scheduler_scan_once()
            self._proactive_svc.tick()
            self.scheduler_stop.wait(20)

    @staticmethod
    def _parse_due_at(value: str | None) -> datetime | None:
        return parse_due_at(value)

    @staticmethod
    def _parse_time_component(raw: str | None) -> tuple[int, int]:
        return parse_time_component(raw)

    @staticmethod
    def _resolve_timezone(name: str | None) -> tuple[timezone | ZoneInfo, bool]:
        return resolve_timezone(name)

    @staticmethod
    def _format_utc(value: datetime) -> str:
        return format_utc(value)

    @staticmethod
    def _compute_next_run(due: datetime, recurrence: str, now_utc: datetime) -> datetime:
        return compute_next_run(due, recurrence, now_utc)

    def task_next_run(self, request: TaskNextRunRequest) -> TaskNextRunResponse:
        due = self._parse_due_at(request.dueAt)
        if due is None:
            return TaskNextRunResponse(accepted=False, reason="invalid_dueAt")
        now_utc = datetime.now(timezone.utc)
        next_due = self._compute_next_run(due=due, recurrence=request.recurrence, now_utc=now_utc)
        return TaskNextRunResponse(
            accepted=True,
            reason="ok",
            nextRunAt=self._format_utc(next_due),
        )

    def parse_task_time(self, request: TaskTimeParseRequest) -> TaskTimeParseResponse:
        text = (request.text or "").strip()
        if not text:
            return TaskTimeParseResponse(accepted=False, reason="empty_text")

        tz_name = request.timezone
        tz, timezone_fallback = self._resolve_timezone(tz_name or "UTC")

        now_local = datetime.now(tz)
        lowered = text.lower()

        # Direct ISO path first.
        direct = self._parse_due_at(text)
        if direct is not None:
            reason = "iso_with_timezone_fallback" if timezone_fallback else "iso"
            return TaskTimeParseResponse(accepted=True, reason=reason, dueAt=self._format_utc(direct))

        # in N minutes/hours/days
        in_match = re.fullmatch(r"in\s+(\d+)\s*(minute|minutes|hour|hours|day|days)", lowered)
        if in_match:
            amount = int(in_match.group(1))
            unit = in_match.group(2)
            delta = timedelta(minutes=amount)
            if "hour" in unit:
                delta = timedelta(hours=amount)
            elif "day" in unit:
                delta = timedelta(days=amount)
            due = now_local + delta
            return TaskTimeParseResponse(
                accepted=True,
                reason="relative_with_timezone_fallback" if timezone_fallback else "relative",
                dueAt=self._format_utc(due.astimezone(timezone.utc)),
            )

        # today/tomorrow [time]
        tt_match = re.fullmatch(r"(today|tomorrow)(?:\s+(.+))?", lowered)
        if tt_match:
            base = now_local.date()
            if tt_match.group(1) == "tomorrow":
                base = base + timedelta(days=1)
            hour, minute = self._parse_time_component(tt_match.group(2))
            due_local = datetime(
                base.year,
                base.month,
                base.day,
                hour,
                minute,
                tzinfo=tz,
            )
            return TaskTimeParseResponse(
                accepted=True,
                reason="day_phrase_with_timezone_fallback" if timezone_fallback else "day_phrase",
                dueAt=self._format_utc(due_local.astimezone(timezone.utc)),
            )

        # next weekday [time]
        nw_match = re.fullmatch(
            r"next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+(.+))?",
            lowered,
        )
        if nw_match:
            weekdays = {
                "monday": 0,
                "tuesday": 1,
                "wednesday": 2,
                "thursday": 3,
                "friday": 4,
                "saturday": 5,
                "sunday": 6,
            }
            target = weekdays[nw_match.group(1)]
            current = now_local.weekday()
            days_ahead = (target - current + 7) % 7
            if days_ahead == 0:
                days_ahead = 7
            base = now_local.date() + timedelta(days=days_ahead)
            hour, minute = self._parse_time_component(nw_match.group(2))
            due_local = datetime(
                base.year,
                base.month,
                base.day,
                hour,
                minute,
                tzinfo=tz,
            )
            return TaskTimeParseResponse(
                accepted=True,
                reason="next_weekday_with_timezone_fallback" if timezone_fallback else "next_weekday",
                dueAt=self._format_utc(due_local.astimezone(timezone.utc)),
            )

        return TaskTimeParseResponse(accepted=False, reason="unsupported_time_phrase")

    @staticmethod
    def _ics_escape(value: str) -> str:
        return ics_escape(value)

    @staticmethod
    def _ics_dt(value: datetime) -> str:
        return ics_dt(value)

    def export_calendar(self, request: CalendarExportRequest) -> CalendarExportResponse:
        export_dir = Path("data/runtime/exports").resolve()
        export_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        file_name = (request.fileName or f"mindi-calendar-{timestamp}.ics").strip()
        if not file_name.lower().endswith(".ics"):
            file_name = f"{file_name}.ics"
        safe_name = Path(file_name).name
        target = export_dir / safe_name

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//MINDI//Task Calendar//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
        ]

        event_count = 0
        now_utc = datetime.now(timezone.utc)
        for task in self.tasks:
            if task.status == "done" and not request.includeCompleted:
                continue
            due = self._parse_due_at(task.dueAt)
            if due is None:
                continue

            uid = f"{task.id}@mindi.local"
            summary = self._ics_escape(task.title)
            dtstamp = self._ics_dt(now_utc)
            dtstart = self._ics_dt(due)
            dtend = self._ics_dt(due + timedelta(minutes=30))
            status = "COMPLETED" if task.status == "done" else "CONFIRMED"

            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{uid}",
                    f"DTSTAMP:{dtstamp}",
                    f"DTSTART:{dtstart}",
                    f"DTEND:{dtend}",
                    f"SUMMARY:{summary}",
                    f"STATUS:{status}",
                ]
            )
            if task.recurrence == "daily":
                lines.append("RRULE:FREQ=DAILY")
            elif task.recurrence == "weekly":
                lines.append("RRULE:FREQ=WEEKLY")
            if task.reminderMinutesBefore is not None and task.reminderMinutesBefore > 0:
                lines.extend(
                    [
                        "BEGIN:VALARM",
                        f"TRIGGER:-PT{task.reminderMinutesBefore}M",
                        "ACTION:DISPLAY",
                        "DESCRIPTION:Task reminder",
                        "END:VALARM",
                    ]
                )
            lines.append("END:VEVENT")
            event_count += 1

        lines.append("END:VCALENDAR")
        target.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")

        self.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent="calendar_export",
                tier=ActionTier.reversible,
                result="allowed",
                reason=f"events:{event_count}",
                createdAt=now_iso(),
            ),
        )

        return CalendarExportResponse(
            accepted=True,
            reason="exported",
            filePath=str(target),
            eventCount=event_count,
        )

    @staticmethod
    def _ics_unescape(value: str) -> str:
        return ics_unescape(value)

    @staticmethod
    def _unfold_ics_lines(raw_text: str) -> list[str]:
        return unfold_ics_lines(raw_text)

    @staticmethod
    def _parse_ics_property(line: str) -> tuple[str, dict[str, str], str] | None:
        return parse_ics_property(line)

    @staticmethod
    def _parse_ics_datetime(raw: str, tzid: str | None = None) -> datetime | None:
        return parse_ics_datetime(raw, tzid)

    @staticmethod
    def _parse_ics_trigger_minutes(raw: str) -> int | None:
        return parse_ics_trigger_minutes(raw)

    def _find_task_conflict(self, title: str, due_at: str, external_id: str | None) -> TaskItem | None:
        if external_id:
            for task in self.tasks:
                if (task.externalId or "").strip() == external_id:
                    return task
        normalized_title = " ".join(title.split()).lower()
        for task in self.tasks:
            if (task.dueAt or "") != due_at:
                continue
            if " ".join(task.title.split()).lower() == normalized_title:
                return task
        return None

    def import_calendar(self, request: CalendarImportRequest) -> CalendarImportResponse:
        source = Path(request.filePath).resolve()
        if not source.exists() or not source.is_file():
            return CalendarImportResponse(
                accepted=False,
                reason="file_not_found",
                importedCount=0,
                createdCount=0,
                updatedCount=0,
                skippedCount=0,
            )
        if source.suffix.lower() != ".ics":
            return CalendarImportResponse(
                accepted=False,
                reason="unsupported_file_type",
                importedCount=0,
                createdCount=0,
                updatedCount=0,
                skippedCount=0,
            )
        if not self._is_path_allowed(source):
            return CalendarImportResponse(
                accepted=False,
                reason="folder_not_allowed",
                importedCount=0,
                createdCount=0,
                updatedCount=0,
                skippedCount=0,
            )

        raw_text = source.read_text(encoding="utf-8", errors="ignore")
        lines = self._unfold_ics_lines(raw_text)
        created_count = 0
        updated_count = 0
        skipped_count = 0
        current: dict[str, str] = {}
        current_dtstart_tzid: str | None = None
        current_exdates: list[tuple[str, str | None]] = []
        current_reminder_minutes: int | None = None
        in_event = False
        in_alarm = False

        def flush_event() -> None:
            nonlocal created_count, updated_count, skipped_count
            nonlocal current, current_dtstart_tzid, current_exdates, current_reminder_minutes
            title_raw = current.get("SUMMARY", "").strip()
            uid_raw = current.get("UID", "").strip()
            dtstart_raw = current.get("DTSTART", "").strip()
            if not title_raw or not dtstart_raw:
                skipped_count += 1
                current = {}
                current_dtstart_tzid = None
                current_exdates = []
                current_reminder_minutes = None
                return
            due = self._parse_ics_datetime(dtstart_raw, tzid=current_dtstart_tzid)
            if due is None:
                skipped_count += 1
                current = {}
                current_dtstart_tzid = None
                current_exdates = []
                current_reminder_minutes = None
                return
            recurrence: str | None = None
            rrule = current.get("RRULE", "").upper()
            if "FREQ=DAILY" in rrule:
                recurrence = "daily"
            elif "FREQ=WEEKLY" in rrule:
                recurrence = "weekly"

            excluded = False
            for exdate_value, exdate_tzid in current_exdates:
                for token in [part.strip() for part in exdate_value.split(",") if part.strip()]:
                    exdate = self._parse_ics_datetime(token, tzid=exdate_tzid)
                    if exdate is not None and exdate == due:
                        excluded = True
                        break
                if excluded:
                    break
            if excluded:
                skipped_count += 1
                current = {}
                current_dtstart_tzid = None
                current_exdates = []
                current_reminder_minutes = None
                return

            title = self._ics_unescape(title_raw)
            external_id = self._ics_unescape(uid_raw) if uid_raw else None
            due_at = self._format_utc(due)
            conflict = self._find_task_conflict(
                title=title,
                due_at=due_at,
                external_id=external_id,
            )
            if conflict is not None:
                conflict.externalId = external_id or conflict.externalId
                conflict.title = title
                conflict.dueAt = due_at
                conflict.nextRunAt = due_at
                conflict.recurrence = recurrence
                conflict.reminderMinutesBefore = current_reminder_minutes
                conflict.source = "assistant"
                updated_count += 1
            else:
                task = TaskItem(
                    id=str(uuid4()),
                    externalId=external_id,
                    title=title,
                    dueAt=due_at,
                    recurrence=recurrence,
                    reminderMinutesBefore=current_reminder_minutes,
                    nextRunAt=due_at,
                    status="todo",
                    source="assistant",
                )
                self.tasks.insert(0, task)
                created_count += 1
            current = {}
            current_dtstart_tzid = None
            current_exdates = []
            current_reminder_minutes = None

        for raw_line in lines:
            line = raw_line.strip()
            if line == "BEGIN:VEVENT":
                in_event = True
                in_alarm = False
                current = {}
                current_dtstart_tzid = None
                current_exdates = []
                current_reminder_minutes = None
                continue
            if line == "END:VEVENT":
                if in_event:
                    flush_event()
                in_event = False
                in_alarm = False
                current = {}
                current_dtstart_tzid = None
                current_exdates = []
                current_reminder_minutes = None
                continue
            if line == "BEGIN:VALARM":
                in_alarm = True
                continue
            if line == "END:VALARM":
                in_alarm = False
                continue
            if not in_event:
                continue

            parsed = self._parse_ics_property(line)
            if parsed is None:
                continue
            key, params, value = parsed

            if in_alarm:
                if key == "TRIGGER":
                    minutes_before = self._parse_ics_trigger_minutes(value)
                    if minutes_before is not None:
                        current_reminder_minutes = minutes_before
                continue

            current[key] = value
            if key == "DTSTART":
                current_dtstart_tzid = params.get("TZID")
            elif key == "EXDATE":
                current_exdates.append((value, params.get("TZID")))

        imported_count = created_count + updated_count
        if imported_count > 0:
            self.logs.insert(
                0,
                ActionLogItem(
                    id=str(uuid4()),
                    intent="calendar_import",
                    tier=ActionTier.reversible,
                    result="allowed",
                    reason=f"created:{created_count},updated:{updated_count},skipped:{skipped_count}",
                    createdAt=now_iso(),
                ),
            )

        if created_count > 0 or updated_count > 0:
            self._persist_durable_state()

        return CalendarImportResponse(
            accepted=True,
            reason="imported",
            importedCount=imported_count,
            createdCount=created_count,
            updatedCount=updated_count,
            skippedCount=skipped_count,
        )

    def scheduler_scan_once(self) -> SchedulerStatus:
        now_utc = datetime.now(timezone.utc)
        created_alerts = 0
        new_alerts: list[AlertItem] = []
        tasks_mutated = False
        self.scheduler_last_error = None

        for task in self.tasks:
            if task.status == "done":
                continue
            due = self._parse_due_at(task.dueAt)
            if due is None:
                continue

            marker = f"{task.id}:{task.dueAt}"
            if due <= now_utc and self.scheduler_alerted_due.get(task.id) != marker:
                overdue_seconds = (now_utc - due).total_seconds()
                severity = "critical" if overdue_seconds >= 3600 else "warning"
                detail = (
                    f"Task '{task.title}' reached due time ({task.dueAt})."
                    if overdue_seconds < 60
                    else f"Task '{task.title}' is overdue ({task.dueAt})."
                )
                alert = AlertItem(
                    id=str(uuid4()),
                    severity=severity,
                    title=f"Task Due: {task.title}",
                    detail=detail,
                    createdAt=now_iso(),
                )
                self.alerts.insert(0, alert)
                new_alerts.append(alert)
                self.scheduler_alerted_due[task.id] = marker
                if task.recurrence in {"daily", "weekly"}:
                    next_due = self._compute_next_run(
                        due=due,
                        recurrence=task.recurrence,
                        now_utc=now_utc,
                    )
                    task.nextRunAt = self._format_utc(next_due)
                    task.dueAt = task.nextRunAt
                    tasks_mutated = True
                created_alerts += 1

        if tasks_mutated:
            self._persist_durable_state()
        self.alerts = self.alerts[:100]
        if new_alerts:
            self._proactive_svc.enqueue_alert_nudges(new_alerts)
        self.scheduler_last_scan = now_iso()
        self.scheduler_alerts_last_run = created_alerts
        self.scheduler_alerts_total += created_alerts
        return self.scheduler_status()

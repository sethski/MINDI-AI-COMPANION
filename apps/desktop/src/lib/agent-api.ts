import { isTauriRuntime, getAgentToken } from "./tauri-window";

import type {
  AiRuntimeConfigUpdateRequest,
  AiRuntimeSmokeRequest,
  AiRuntimeSmokeResponse,
  AiRuntimeStatusResponse,
  AsrTranscribeRequest,
  AsrTranscribeResponse,
  AddPermissionGrantRequest,
  AppControlRequest,
  AppControlResponse,
  AlertActionRequest,
  AlertActionResponse,
  AlertFeedResponse,
  AssistantRequest,
  AssistantResponse,
  CreateMemoryNoteRequest,
  DocumentImportResponse,
  DocumentSearchResponse,
  CreateTaskRequest,
  TaskStatusUpdateRequest,
  TaskUpdateRequest,
  FileOrganizeRequest,
  FileOrganizeResponse,
  HubSnapshot,
  AutoIndexStatus,
  SchedulerStatus,
  MemoryNote,
  MemoryGraphResponse,
  LauncherRequest,
  LauncherResponse,
  MemorySearchResponse,
  OcrImportResponse,
  PerceptionAnalyzeRequest,
  PerceptionAnalyzeResponse,
  PerceptionPermissionStatus,
  IntelligenceLearningApplyRequest,
  IntelligenceLearningApplyResponse,
  IntelligenceLearningRunResponse,
  IntelligenceLearningSourceRequest,
  IntelligenceLearningSourceResponse,
  IntelligenceLearningStatus,
  IntelligenceAdaptationExportResponse,
  IntelligenceAdaptationStatus,
  IntelligenceEvalRunRequest,
  IntelligenceEvalRunResponse,
  IntelligenceTuningApplyResponse,
  IntelligenceTuningStageRequest,
  IntelligenceTuningStatus,
  IntelligenceStyleStatus,
  IntelligenceStyleUpdateRequest,
  PrivacyStatus,
  PrivacyUpdateRequest,
  PerceptionSnapshot,
  PerceptionSnapshotSearchResponse,
  PermissionGrant,
  TaskItem,
  TaskNextRunRequest,
  TaskNextRunResponse,
  TaskTimeParseRequest,
  TaskTimeParseResponse,
  SecurityEvent,
  SecurityRecoveryRequest,
  SecurityRecoveryResponse,
  SecurityScanResponse,
  AutomationChainRequest,
  AutomationChainResponse,
  WebScrapeRequest,
  WebScrapeResponse,
  CalendarExportRequest,
  CalendarExportResponse,
  CalendarImportRequest,
  CalendarImportResponse,
  DatasetPrepareRequest,
  DatasetPrepareResponse,
  ChatHistoryResponse,
  ProactiveNudge,
  ProactiveStatus,
} from "@mindi/shared";

const AGENT_URL = "http://127.0.0.1:8765";
const ASSISTANT_TIMEOUT_MS = 240_000;

let _agentToken: string | null | undefined;

async function resolveToken(): Promise<string | null> {
  if (_agentToken !== undefined) return _agentToken;
  _agentToken = isTauriRuntime() ? await getAgentToken() : null;
  return _agentToken;
}

const _RETRY_DELAYS_MS = [300, 900, 2700] as const;
const _CIRCUIT_THRESHOLD = 3;
const _CIRCUIT_OPEN_MS = 30_000;
const _circuit = { failures: 0, openUntil: 0 };

function _sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function _incrementCircuit(): void {
  _circuit.failures++;
  _circuit.openUntil = Date.now() + _CIRCUIT_OPEN_MS;
}

async function agentFetch<T>(path: string, init?: RequestInit): Promise<T> {
  if (_circuit.failures >= _CIRCUIT_THRESHOLD && Date.now() < _circuit.openUntil) {
    throw new Error("agent_circuit_open");
  }

  const token = await resolveToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined ?? {}),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let attempt = 0;

  while (true) {
    let response: Response;
    try {
      response = await fetch(`${AGENT_URL}${path}`, { ...init, headers });
    } catch {
      if (attempt < _RETRY_DELAYS_MS.length) {
        await _sleep(_RETRY_DELAYS_MS[attempt]);
        attempt++;
        continue;
      }
      _incrementCircuit();
      throw new Error("agent_unreachable");
    }

    if (response.ok) {
      _circuit.failures = 0;
      return (await response.json()) as T;
    }

    if (response.status === 503 && attempt < _RETRY_DELAYS_MS.length) {
      await _sleep(_RETRY_DELAYS_MS[attempt]);
      attempt++;
      continue;
    }

    _incrementCircuit();
    let message = `Agent request failed: ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string; reason?: string };
      if (body.detail) message = `Agent error: ${String(body.detail)}`;
      else if (body.reason) message = `Agent error: ${String(body.reason)}`;
    } catch { /* ignore body parse failure */ }
    throw new Error(message);
  }
}

export async function fetchHubSnapshot(): Promise<HubSnapshot> {
  return agentFetch<HubSnapshot>("/hub/snapshot");
}

export async function sendAssistantRequest(
  payload: AssistantRequest,
): Promise<AssistantResponse> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), ASSISTANT_TIMEOUT_MS);
  try {
    return await agentFetch<AssistantResponse>("/assistant/respond", {
      method: "POST",
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
  } finally {
    window.clearTimeout(timer);
  }
}

export interface AssistantStreamEvent {
  token?: string;
  done?: boolean;
  reply?: string;
  status?: string;
  provider?: string;
  model?: string;
  degraded?: boolean;
  fallbackReason?: string;
  error?: string;
  suggestedActions?: string[];
}

export async function streamAssistantRequest(
  payload: AssistantRequest,
  onEvent: (event: AssistantStreamEvent) => void,
  signal?: AbortSignal,
): Promise<AssistantStreamEvent | null> {
  const token = await resolveToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const response = await fetch(`${AGENT_URL}/assistant/respond/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`stream_failed:${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalEvent: AssistantStreamEvent | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) {
        continue;
      }
      const raw = trimmed.slice(5).trim();
      if (!raw) {
        continue;
      }
      try {
        const event = JSON.parse(raw) as AssistantStreamEvent;
        onEvent(event);
        if (event.done) {
          finalEvent = event;
        }
        if (event.error) {
          finalEvent = event;
          break;
        }
      } catch {
        // Ignore malformed SSE chunks.
      }
    }
    if (finalEvent?.error) {
      break;
    }
  }

  return finalEvent;
}

export async function getAiRuntimeStatus(): Promise<AiRuntimeStatusResponse> {
  return agentFetch<AiRuntimeStatusResponse>("/ops/ai/status");
}

export async function updateAiRuntimeConfig(
  payload: AiRuntimeConfigUpdateRequest,
): Promise<AiRuntimeStatusResponse> {
  return agentFetch<AiRuntimeStatusResponse>("/ops/ai/config", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export interface TtsSynthesizeRequest {
  text: string;
}

export interface TtsSynthesizeResponse {
  accepted: boolean;
  reason: string;
  audioDataUrl?: string | null;
  provider?: string | null;
  model?: string | null;
  degraded?: boolean;
  latencyMs?: number | null;
}

export async function synthesizeTts(
  payload: TtsSynthesizeRequest,
): Promise<TtsSynthesizeResponse> {
  return agentFetch<TtsSynthesizeResponse>("/ops/tts/synthesize", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function transcribeAsr(
  payload: AsrTranscribeRequest,
): Promise<AsrTranscribeResponse> {
  return agentFetch<AsrTranscribeResponse>("/ops/asr/transcribe", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function transcribeMicBlob(sourceValue: string): Promise<AsrTranscribeResponse> {
  return transcribeAsr({
    sourceType: "mic",
    sourceValue,
  });
}

export async function transcribeWakeBlob(sourceValue: string): Promise<AsrTranscribeResponse> {
  return transcribeAsr({
    sourceType: "mic",
    sourceValue,
    languageHint: "English",
  });
}

export async function setOrbListeningState(listening: boolean): Promise<void> {
  await agentFetch<{ accepted: boolean }>("/ops/orb/listening", {
    method: "POST",
    body: JSON.stringify({ listening }),
  });
}

export async function runAiSmoke(
  payload: AiRuntimeSmokeRequest,
): Promise<AiRuntimeSmokeResponse> {
  return agentFetch<AiRuntimeSmokeResponse>("/ops/ai/smoke", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function prepareDataset(
  payload: DatasetPrepareRequest,
): Promise<DatasetPrepareResponse> {
  return agentFetch<DatasetPrepareResponse>("/ops/intelligence/dataset/prepare", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createTask(payload: CreateTaskRequest): Promise<TaskItem> {
  return agentFetch<TaskItem>("/tasks", {
    method: "POST",
    body: JSON.stringify({ ...payload, idempotencyKey: crypto.randomUUID() }),
  });
}

export async function updateTaskStatus(
  taskId: string,
  payload: TaskStatusUpdateRequest,
): Promise<TaskItem> {
  return agentFetch<TaskItem>(`/tasks/${encodeURIComponent(taskId)}/status`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function updateTask(
  taskId: string,
  payload: TaskUpdateRequest,
): Promise<TaskItem> {
  return agentFetch<TaskItem>(`/tasks/${encodeURIComponent(taskId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteTask(taskId: string): Promise<{ accepted: boolean; deletedId: string }> {
  return agentFetch<{ accepted: boolean; deletedId: string }>(
    `/tasks/${encodeURIComponent(taskId)}`,
    {
      method: "DELETE",
    },
  );
}

export async function listPermissionGrants(): Promise<PermissionGrant[]> {
  return agentFetch<PermissionGrant[]>("/control/permissions");
}

export async function addPermissionGrant(
  payload: AddPermissionGrantRequest,
): Promise<PermissionGrant> {
  return agentFetch<PermissionGrant>("/control/permissions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fileOrganize(
  payload: FileOrganizeRequest,
): Promise<FileOrganizeResponse> {
  return agentFetch<FileOrganizeResponse>("/control/file-organize", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchAllowedApps(): Promise<{ apps: string[] }> {
  return agentFetch<{ apps: string[] }>("/control/apps/allowlist");
}

export async function appControlAction(
  payload: AppControlRequest,
): Promise<AppControlResponse> {
  return agentFetch<AppControlResponse>("/control/apps/action", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listMemoryNotes(limit = 50): Promise<MemoryNote[]> {
  return agentFetch<MemoryNote[]>(`/memory/notes?limit=${limit}`);
}

export async function createMemoryNote(
  payload: CreateMemoryNoteRequest,
): Promise<MemoryNote> {
  return agentFetch<MemoryNote>("/memory/notes", {
    method: "POST",
    body: JSON.stringify({ ...payload, idempotencyKey: crypto.randomUUID() }),
  });
}

export async function searchMemory(query: string, limit = 50): Promise<MemorySearchResponse> {
  const encoded = encodeURIComponent(query);
  return agentFetch<MemorySearchResponse>(`/memory/search?query=${encoded}&limit=${limit}`);
}

export async function importDocument(path: string): Promise<DocumentImportResponse> {
  return agentFetch<DocumentImportResponse>("/memory/documents/import", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export async function searchDocuments(
  query: string,
  limit = 20,
): Promise<DocumentSearchResponse> {
  const encoded = encodeURIComponent(query);
  return agentFetch<DocumentSearchResponse>(
    `/memory/documents/search?query=${encoded}&limit=${limit}`,
  );
}

export async function importOcrDocument(path: string): Promise<OcrImportResponse> {
  return agentFetch<OcrImportResponse>("/memory/ocr/import", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export async function analyzeScreenPerception(
  payload: PerceptionAnalyzeRequest,
): Promise<PerceptionAnalyzeResponse> {
  return agentFetch<PerceptionAnalyzeResponse>("/perception/screen/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getPerceptionPermissionStatus(): Promise<PerceptionPermissionStatus> {
  return agentFetch<PerceptionPermissionStatus>("/perception/permissions");
}

export async function listPerceptionSnapshots(limit = 20): Promise<PerceptionSnapshot[]> {
  return agentFetch<PerceptionSnapshot[]>(`/memory/perception?limit=${limit}`);
}

export async function searchPerceptionSnapshots(
  query: string,
  limit = 20,
): Promise<PerceptionSnapshotSearchResponse> {
  const encoded = encodeURIComponent(query);
  return agentFetch<PerceptionSnapshotSearchResponse>(
    `/memory/perception/search?query=${encoded}&limit=${limit}`,
  );
}

export async function getAutoIndexStatus(): Promise<AutoIndexStatus> {
  return agentFetch<AutoIndexStatus>("/memory/auto-index/status");
}

export async function scanAutoIndexNow(): Promise<AutoIndexStatus> {
  return agentFetch<AutoIndexStatus>("/memory/auto-index/scan", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function fetchMemoryGraph(): Promise<MemoryGraphResponse> {
  return agentFetch<MemoryGraphResponse>("/memory/graph");
}

export async function fetchChatHistory(limit = 100): Promise<ChatHistoryResponse> {
  return agentFetch<ChatHistoryResponse>(`/chat/history?limit=${limit}`);
}

export async function clearChatHistory(): Promise<{ deleted: number }> {
  return agentFetch<{ deleted: number }>("/chat/history", { method: "DELETE" });
}

export async function getProactiveStatus(): Promise<ProactiveStatus> {
  return agentFetch<ProactiveStatus>("/ops/proactive/status");
}

export async function postProactiveOrbActivity(idle: boolean): Promise<ProactiveStatus> {
  return agentFetch<ProactiveStatus>("/ops/proactive/orb-activity", {
    method: "POST",
    body: JSON.stringify({ idle }),
  });
}

export async function pullProactiveNudges(limit = 3): Promise<ProactiveNudge[]> {
  return agentFetch<ProactiveNudge[]>(`/ops/proactive/nudges?limit=${limit}`);
}

export async function runProactiveBriefing(): Promise<ProactiveNudge> {
  return agentFetch<ProactiveNudge>("/ops/proactive/briefing", { method: "POST", body: "{}" });
}

export async function openLauncher(
  payload: LauncherRequest,
): Promise<LauncherResponse> {
  return agentFetch<LauncherResponse>("/control/launcher", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getSchedulerStatus(): Promise<SchedulerStatus> {
  return agentFetch<SchedulerStatus>("/ops/scheduler/status");
}

export async function runSchedulerScanNow(): Promise<SchedulerStatus> {
  return agentFetch<SchedulerStatus>("/ops/scheduler/scan", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function getSchedulerNextRun(
  payload: TaskNextRunRequest,
): Promise<TaskNextRunResponse> {
  return agentFetch<TaskNextRunResponse>("/ops/scheduler/next-run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function parseTaskTime(
  payload: TaskTimeParseRequest,
): Promise<TaskTimeParseResponse> {
  return agentFetch<TaskTimeParseResponse>("/ops/scheduler/parse-time", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function scrapeWeb(
  payload: WebScrapeRequest,
): Promise<WebScrapeResponse> {
  return agentFetch<WebScrapeResponse>("/ops/web/scrape", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listSecurityEvents(
  status: "open" | "resolved" | "all" = "open",
  limit = 25,
): Promise<SecurityEvent[]> {
  return agentFetch<SecurityEvent[]>(`/ops/security/events?status=${status}&limit=${limit}`);
}

export async function runSecurityScan(): Promise<SecurityScanResponse> {
  return agentFetch<SecurityScanResponse>("/ops/security/scan", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function runSecurityRecovery(
  payload: SecurityRecoveryRequest,
): Promise<SecurityRecoveryResponse> {
  return agentFetch<SecurityRecoveryResponse>("/ops/security/recover", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function runAutomationChain(
  payload: AutomationChainRequest,
): Promise<AutomationChainResponse> {
  return agentFetch<AutomationChainResponse>("/ops/automation/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getAlertFeed(limit = 25): Promise<AlertFeedResponse> {
  return agentFetch<AlertFeedResponse>(`/ops/alerts/feed?limit=${limit}`);
}

export async function runAlertAction(
  payload: AlertActionRequest,
): Promise<AlertActionResponse> {
  return agentFetch<AlertActionResponse>("/ops/alerts/action", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getPrivacyStatus(): Promise<PrivacyStatus> {
  return agentFetch<PrivacyStatus>("/ops/privacy/status");
}

export async function updatePrivacyStatus(
  payload: PrivacyUpdateRequest,
): Promise<PrivacyStatus> {
  return agentFetch<PrivacyStatus>("/ops/privacy/update", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getIntelligenceStyleStatus(): Promise<IntelligenceStyleStatus> {
  return agentFetch<IntelligenceStyleStatus>("/ops/intelligence/style");
}

export async function getIntelligenceTuningStatus(): Promise<IntelligenceTuningStatus> {
  return agentFetch<IntelligenceTuningStatus>("/ops/intelligence/tuning");
}

export async function updateIntelligenceStyleStatus(
  payload: IntelligenceStyleUpdateRequest,
): Promise<IntelligenceStyleStatus> {
  return agentFetch<IntelligenceStyleStatus>("/ops/intelligence/style", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function stageIntelligenceTuning(
  payload: IntelligenceTuningStageRequest,
): Promise<IntelligenceTuningStatus> {
  return agentFetch<IntelligenceTuningStatus>("/ops/intelligence/tuning/stage", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function discardIntelligenceTuning(): Promise<IntelligenceTuningStatus> {
  return agentFetch<IntelligenceTuningStatus>("/ops/intelligence/tuning/pending", {
    method: "DELETE",
  });
}

export async function runIntelligenceEval(
  payload: IntelligenceEvalRunRequest = {},
): Promise<IntelligenceEvalRunResponse> {
  return agentFetch<IntelligenceEvalRunResponse>("/ops/intelligence/eval/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listIntelligenceEvalHistory(limit = 20): Promise<IntelligenceEvalRunResponse[]> {
  return agentFetch<IntelligenceEvalRunResponse[]>(
    `/ops/intelligence/eval/history?limit=${limit}`,
  );
}

export async function getIntelligenceAdaptationStatus(): Promise<IntelligenceAdaptationStatus> {
  return agentFetch<IntelligenceAdaptationStatus>("/ops/intelligence/adaptation/status");
}

export async function exportIntelligenceAdaptation(): Promise<IntelligenceAdaptationExportResponse> {
  return agentFetch<IntelligenceAdaptationExportResponse>("/ops/intelligence/adaptation/export", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function applyIntelligenceTuning(): Promise<IntelligenceTuningApplyResponse> {
  return agentFetch<IntelligenceTuningApplyResponse>("/ops/intelligence/tuning/apply", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function getIntelligenceLearningStatus(): Promise<IntelligenceLearningStatus> {
  return agentFetch<IntelligenceLearningStatus>("/ops/intelligence/learning/status");
}

export async function updateIntelligenceLearningSource(
  payload: IntelligenceLearningSourceRequest,
): Promise<IntelligenceLearningSourceResponse> {
  return agentFetch<IntelligenceLearningSourceResponse>("/ops/intelligence/learning/source", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function runIntelligenceLearning(): Promise<IntelligenceLearningRunResponse> {
  return agentFetch<IntelligenceLearningRunResponse>("/ops/intelligence/learning/run", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function applyIntelligenceLearning(
  payload: IntelligenceLearningApplyRequest,
): Promise<IntelligenceLearningApplyResponse> {
  return agentFetch<IntelligenceLearningApplyResponse>("/ops/intelligence/learning/apply", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function exportCalendar(
  payload: CalendarExportRequest,
): Promise<CalendarExportResponse> {
  return agentFetch<CalendarExportResponse>("/calendar/export", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function importCalendar(
  payload: CalendarImportRequest,
): Promise<CalendarImportResponse> {
  return agentFetch<CalendarImportResponse>("/calendar/import", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

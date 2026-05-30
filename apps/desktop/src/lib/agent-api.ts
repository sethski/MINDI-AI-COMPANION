import type {
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
  MemorySearchResponse,
  OcrImportResponse,
  PerceptionAnalyzeRequest,
  PerceptionAnalyzeResponse,
  PerceptionPermissionStatus,
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
} from "@mindi/shared";

const AGENT_URL = "http://127.0.0.1:8765";

async function agentFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${AGENT_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    throw new Error(`Agent request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function fetchHubSnapshot(): Promise<HubSnapshot> {
  return agentFetch<HubSnapshot>("/hub/snapshot");
}

export async function sendAssistantRequest(
  payload: AssistantRequest,
): Promise<AssistantResponse> {
  return agentFetch<AssistantResponse>("/assistant/respond", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createTask(payload: CreateTaskRequest): Promise<TaskItem> {
  return agentFetch<TaskItem>("/tasks", {
    method: "POST",
    body: JSON.stringify(payload),
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
    body: JSON.stringify(payload),
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

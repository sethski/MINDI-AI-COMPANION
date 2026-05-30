import type {
  AddPermissionGrantRequest,
  AppControlRequest,
  AppControlResponse,
  AssistantRequest,
  AssistantResponse,
  CreateMemoryNoteRequest,
  DocumentImportResponse,
  DocumentSearchResponse,
  CreateTaskRequest,
  FileOrganizeRequest,
  FileOrganizeResponse,
  HubSnapshot,
  AutoIndexStatus,
  SchedulerStatus,
  MemoryNote,
  MemorySearchResponse,
  OcrImportResponse,
  PermissionGrant,
  TaskItem,
  TaskNextRunRequest,
  TaskNextRunResponse,
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

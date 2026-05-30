import type {
  AddPermissionGrantRequest,
  AppControlRequest,
  AppControlResponse,
  AssistantRequest,
  AssistantResponse,
  CreateTaskRequest,
  FileOrganizeRequest,
  FileOrganizeResponse,
  HubSnapshot,
  PermissionGrant,
  TaskItem,
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

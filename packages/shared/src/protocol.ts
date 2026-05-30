export type MindiTabId =
  | "home"
  | "control"
  | "memory"
  | "vision"
  | "ops"
  | "safety"
  | "settings";

export type ActionTier = "read_only" | "reversible" | "risky" | "destructive";

export interface PolicyDecision {
  allowed: boolean;
  tier: ActionTier;
  reason: string;
  requiresUnlock: boolean;
}

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
  timestamp?: string;
}

export interface AssistantRequest {
  text: string;
  mode?: "chat" | "action";
  tab?: MindiTabId;
  conversation?: ChatMessage[];
}

export interface AssistantResponse {
  reply: string;
  decision: PolicyDecision;
  suggestedActions: string[];
  status: string;
}

export interface AgentStatus {
  state: "ready" | "offline" | "busy" | "blocked";
  uptimeSeconds: number;
  activeTask?: string;
  listening: boolean;
  agentVersion: string;
  currentProfile: string;
}

export interface QuickToggle {
  id: string;
  label: string;
  enabled: boolean;
}

export interface AlertItem {
  id: string;
  severity: "info" | "warning" | "critical";
  title: string;
  detail: string;
  createdAt: string;
}

export interface TaskItem {
  id: string;
  title: string;
  status: "todo" | "in_progress" | "done";
  dueAt?: string;
  recurrence?: "daily" | "weekly";
  nextRunAt?: string;
  source: "manual" | "assistant";
}

export interface ActionLogItem {
  id: string;
  intent: string;
  tier: ActionTier;
  result: "allowed" | "blocked";
  reason: string;
  createdAt: string;
}

export interface HubSnapshot {
  status: AgentStatus;
  alerts: AlertItem[];
  tasks: TaskItem[];
  logs: ActionLogItem[];
}

export interface CreateTaskRequest {
  title: string;
  dueAt?: string;
  recurrence?: "daily" | "weekly";
}

export interface TaskNextRunRequest {
  dueAt: string;
  recurrence: "daily" | "weekly";
}

export interface TaskNextRunResponse {
  accepted: boolean;
  reason: string;
  nextRunAt?: string;
}

export interface TaskTimeParseRequest {
  text: string;
  timezone?: string;
}

export interface TaskTimeParseResponse {
  accepted: boolean;
  reason: string;
  dueAt?: string;
}

export interface CalendarExportRequest {
  fileName?: string;
  includeCompleted?: boolean;
}

export interface CalendarExportResponse {
  accepted: boolean;
  reason: string;
  filePath?: string;
  eventCount: number;
}

export interface SyncQueueItem {
  id: string;
  type: "chat" | "action" | "note" | "scrape" | "ocr";
  payload: Record<string, unknown>;
  createdAt: string;
  status: "queued" | "synced" | "failed";
}

export type PermissionScope = "folder" | "app" | "domain" | "action";
export type PermissionDecision = "allow" | "deny";

export interface PermissionGrant {
  id: string;
  scope: PermissionScope;
  subject: string;
  decision: PermissionDecision;
  createdAt: string;
}

export interface AddPermissionGrantRequest {
  scope: PermissionScope;
  subject: string;
  decision: PermissionDecision;
}

export interface FileOrganizeRequest {
  sourceDir: string;
  targetDir: string;
  mode: "preview" | "apply";
}

export interface FileOrganizeItem {
  fileName: string;
  sourcePath: string;
  targetPath: string;
  category: string;
}

export interface FileOrganizeResponse {
  accepted: boolean;
  reason: string;
  movedCount: number;
  items: FileOrganizeItem[];
}

export interface AppControlRequest {
  action: "open" | "focus" | "close";
  appId: string;
  confirm?: boolean;
}

export interface AppControlResponse {
  accepted: boolean;
  reason: string;
  tier: ActionTier;
  requiresConfirmation: boolean;
}

export interface MemoryNote {
  id: string;
  title: string;
  content: string;
  tags: string[];
  createdAt: string;
  updatedAt: string;
}

export interface CreateMemoryNoteRequest {
  title: string;
  content: string;
  tags?: string[];
}

export interface MemorySearchResponse {
  query: string;
  items: MemoryNote[];
}

export interface DocumentImportRequest {
  path: string;
}

export interface MemoryDocument {
  id: string;
  sourcePath: string;
  title: string;
  importedAt: string;
  chunkCount: number;
}

export interface MemoryDocumentChunk {
  id: string;
  documentId: string;
  sourcePath: string;
  title: string;
  text: string;
  chunkIndex: number;
  score: number;
}

export interface DocumentImportResponse {
  accepted: boolean;
  reason: string;
  document?: MemoryDocument;
}

export interface DocumentSearchResponse {
  query: string;
  items: MemoryDocumentChunk[];
}

export interface OcrImportRequest {
  path: string;
}

export interface OcrImportResponse {
  accepted: boolean;
  reason: string;
  document?: MemoryDocument;
}

export interface AutoIndexStatus {
  running: boolean;
  watchedPaths: string[];
  lastScanAt?: string;
  indexedTotal: number;
  indexedLastRun: number;
  lastError?: string;
}

export interface SchedulerStatus {
  running: boolean;
  lastScanAt?: string;
  alertsTotal: number;
  alertsLastRun: number;
  trackedTasks: number;
  lastError?: string;
}

export const TAB_ORDER: MindiTabId[] = [
  "home",
  "control",
  "memory",
  "vision",
  "ops",
  "safety",
  "settings",
];

export const QUICK_TOGGLES: QuickToggle[] = [
  { id: "readOnly", label: "Read-only", enabled: true },
  { id: "screen", label: "Screen capture", enabled: false },
  { id: "mic", label: "Mic", enabled: true },
  { id: "webcam", label: "Webcam", enabled: false },
  { id: "automation", label: "Automation", enabled: false },
];


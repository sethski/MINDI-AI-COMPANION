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
  provider?: string;
  model?: string;
  degraded?: boolean;
  fallbackReason?: string;
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
  externalId?: string;
  title: string;
  status: "todo" | "in_progress" | "done";
  dueAt?: string;
  recurrence?: "daily" | "weekly";
  reminderMinutesBefore?: number;
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

export interface TaskStatusUpdateRequest {
  status: "todo" | "in_progress" | "done";
}

export interface TaskUpdateRequest {
  title?: string;
  dueAt?: string | null;
  recurrence?: "daily" | "weekly" | null;
  status?: "todo" | "in_progress" | "done";
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

export interface CalendarImportRequest {
  filePath: string;
}

export interface CalendarImportResponse {
  accepted: boolean;
  reason: string;
  importedCount: number;
  createdCount: number;
  updatedCount: number;
  skippedCount: number;
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
  ocrBackend?: string;
  ocrModel?: string;
  degraded?: boolean;
  fallbackReason?: string;
}

export interface PerceptionAnalyzeRequest {
  path?: string;
  imageDataUrl?: string;
  includeOcr?: boolean;
  maxBlocks?: number;
}

export interface PerceptionUiBlock {
  x: number;
  y: number;
  width: number;
  height: number;
  kind: "text_region";
  confidence: number;
  textSnippet?: string;
}

export interface PerceptionAnalyzeResponse {
  accepted: boolean;
  reason: string;
  snapshotId?: string;
  storageRedacted: boolean;
  redactionCount: number;
  path?: string;
  imageWidth?: number;
  imageHeight?: number;
  ocrMode?: string;
  ocrError?: string;
  ocrBackend?: string;
  ocrModel?: string;
  degraded?: boolean;
  fallbackReason?: string;
  text?: string;
  textLength: number;
  blocks: PerceptionUiBlock[];
}

export interface AiRuntimeFeatureStatus {
  enabled: boolean;
  ready: boolean;
  experimental: boolean;
  pathConfigured: boolean;
  provider: string;
  model: string;
  lastError?: string;
  lastLatencyMs?: number;
  lastFailureReason?: string;
}

export interface AiRuntimeServiceStatus {
  service: string;
  reachable: boolean;
  url: string;
  offlineMode: boolean;
  lastError?: string;
}

export interface AiRuntimeConfig {
  llmModelPath: string;
  llmLanguagePackPath: string;
  asrModelPath: string;
  ocrModelPath: string;
  ocrPythonExecutable: string;
  llmCommand: string;
  llmContextSize: number;
  llmMaxTokens: number;
  llmTemperature: number;
  llmThreads: number;
  llmProvider: string;
  asrProvider: string;
  ocrProvider: string;
  llmModel: string;
  asrModel: string;
  ocrModel: string;
  asrLanguageHint?: string;
  asrReturnTimestamps: boolean;
  asrMaxTokens: number;
  offlineMode: boolean;
  experimentalAsr: boolean;
  experimentalOcr: boolean;
}

export interface AiRuntimeStatusResponse {
  accepted: boolean;
  runtime: AiRuntimeServiceStatus;
  features: {
    llm: AiRuntimeFeatureStatus;
    asr: AiRuntimeFeatureStatus;
    ocr: AiRuntimeFeatureStatus;
  };
  config: AiRuntimeConfig;
}

export interface AiRuntimeConfigUpdateRequest {
  llmModelPath?: string;
  llmLanguagePackPath?: string;
  asrModelPath?: string;
  ocrModelPath?: string;
  ocrPythonExecutable?: string;
  llmCommand?: string;
  llmContextSize?: number;
  llmMaxTokens?: number;
  llmTemperature?: number;
  llmThreads?: number;
  llmProvider?: string;
  asrProvider?: string;
  ocrProvider?: string;
  llmModel?: string;
  asrModel?: string;
  ocrModel?: string;
  asrLanguageHint?: string;
  asrReturnTimestamps?: boolean;
  asrMaxTokens?: number;
  offlineMode?: boolean;
  experimentalAsr?: boolean;
  experimentalOcr?: boolean;
}

export interface AsrSegment {
  startMs: number;
  endMs: number;
  text: string;
}

export interface AsrTranscribeRequest {
  sourceType: "file" | "mic";
  sourceValue: string;
  languageHint?: string;
  returnTimestamps?: boolean;
}

export interface AsrTranscribeResponse {
  accepted: boolean;
  reason: string;
  text?: string;
  segments: AsrSegment[];
  provider?: string;
  model?: string;
  degraded: boolean;
  fallbackReason?: string;
}

export interface AiSmokeProbeResult {
  attempted: boolean;
  accepted: boolean;
  reason: string;
  provider?: string;
  model?: string;
  latencyMs?: number;
  degraded: boolean;
  fallbackReason?: string;
  textPreview?: string;
  segmentCount?: number;
}

export interface AiRuntimeSmokeRequest {
  includeLlm?: boolean;
  includeAsr?: boolean;
  includeOcr?: boolean;
  llmPrompt?: string;
  languageMode?: "english" | "taglish" | "tagalog";
  asrFilePath?: string;
  asrLanguageHint?: string;
  ocrImagePath?: string;
}

export interface AiRuntimeSmokeResponse {
  accepted: boolean;
  reason: string;
  startedAt: string;
  finishedAt: string;
  probes: {
    llm: AiSmokeProbeResult;
    asr: AiSmokeProbeResult;
    ocr: AiSmokeProbeResult;
  };
}

export interface DatasetPrepareRequest {
  datasetPath: string;
  outputDir?: string;
}

export interface DatasetPrepareResponse {
  accepted: boolean;
  reason: string;
  datasetPath: string;
  outputDir: string;
  rawSamples: number;
  trainSamples: number;
  valSamples: number;
  languagePackPath?: string;
  trainJsonlPath?: string;
  valJsonlPath?: string;
  configPath?: string;
  manifestPath?: string;
  validationPassed: boolean;
  validationIssues: string[];
  languagePackLoaded: boolean;
  languagePackLoadReason?: string;
}

export interface PerceptionSnapshot {
  id: string;
  sourcePath?: string;
  reason: string;
  ocrMode?: string;
  text?: string;
  textLength: number;
  blockCount: number;
  imageWidth?: number;
  imageHeight?: number;
  createdAt: string;
}

export interface PerceptionSnapshotSearchResponse {
  query: string;
  items: PerceptionSnapshot[];
}

export interface PerceptionPermissionStatus {
  screenSubject: string;
  cameraSubject: string;
  screenAllowed: boolean;
  cameraAllowed: boolean;
  screenDecision: "allow" | "deny" | "unset";
  cameraDecision: "allow" | "deny" | "unset";
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

export interface WebScrapeRequest {
  url: string;
  maxChars?: number;
  storeAsNote?: boolean;
}

export interface WebScrapeResponse {
  accepted: boolean;
  reason: string;
  url: string;
  storageRedacted: boolean;
  redactionCount: number;
  title?: string;
  text?: string;
  textLength: number;
  links: string[];
  storedNoteId?: string;
}

export interface SecurityEvent {
  id: string;
  severity: "info" | "warning" | "critical";
  title: string;
  detail: string;
  source: "process_scan" | "defender_service" | "manual";
  status: "open" | "resolved";
  processName?: string;
  pid?: number;
  recoveryActions: string[];
  createdAt: string;
  resolvedAt?: string;
}

export interface SecurityScanResponse {
  accepted: boolean;
  reason: string;
  scannedProcessCount: number;
  newAlerts: number;
  events: SecurityEvent[];
}

export interface SecurityRecoveryRequest {
  eventId: string;
  action: "dismiss" | "deny_app" | "kill_process";
  target?: string;
  confirm?: boolean;
}

export interface SecurityRecoveryResponse {
  accepted: boolean;
  reason: string;
  event?: SecurityEvent;
}

export interface AutomationChainStep {
  kind: "web_scrape" | "create_task" | "create_note" | "security_scan";
  title?: string;
  url?: string;
  text?: string;
  dueAt?: string;
  recurrence?: "daily" | "weekly";
  storeAsNote?: boolean;
}

export interface AutomationChainRequest {
  name: string;
  continueOnFailure?: boolean;
  steps: AutomationChainStep[];
}

export interface AutomationChainStepResult {
  index: number;
  kind: string;
  accepted: boolean;
  reason: string;
  startedAt: string;
  finishedAt: string;
  recoveryHint?: string;
  detail?: string;
}

export interface AutomationChainResponse {
  accepted: boolean;
  reason: string;
  name: string;
  totalSteps: number;
  completedSteps: number;
  failedStepIndex?: number;
  steps: AutomationChainStepResult[];
  recoverySummary?: string;
}

export interface AlertFeedResponse {
  accepted: boolean;
  reason: string;
  total: number;
  critical: number;
  warning: number;
  info: number;
  items: AlertItem[];
}

export interface AlertActionRequest {
  alertId: string;
  action: "dismiss" | "create_recovery_task" | "export_report";
}

export interface AlertActionResponse {
  accepted: boolean;
  reason: string;
  createdTaskId?: string;
  reportPath?: string;
}

export interface PrivacyStatus {
  redactionEnabled: boolean;
  safeStorageDefault: boolean;
  sensitivePatternCount: number;
}

export interface PrivacyUpdateRequest {
  redactionEnabled: boolean;
}

export interface IntelligenceStyleStatus {
  languageMode: "english" | "taglish" | "tagalog";
  slangEnabled: boolean;
  slangTerms: string[];
}

export interface IntelligenceStyleUpdateRequest {
  languageMode?: "english" | "taglish" | "tagalog";
  slangEnabled?: boolean;
  addSlangTerms?: string[];
  resetSlangTerms?: boolean;
}

export interface IntelligenceTuningConfig {
  preset: "safe" | "balanced" | "companion";
  responseVerbosity: "brief" | "balanced" | "detailed";
  customRiskyTerms: string[];
}

export interface IntelligenceTuningStatus {
  active: IntelligenceTuningConfig;
  pending?: IntelligenceTuningConfig;
  pendingVersion?: string;
  lastActiveEvalScore?: number;
  lastPendingEvalScore?: number;
  lastPendingEvalVersion?: string;
  minApplyScore: number;
  canApplyPending: boolean;
}

export interface IntelligenceTuningStageRequest {
  preset?: "safe" | "balanced" | "companion";
  responseVerbosity?: "brief" | "balanced" | "detailed";
  addCustomRiskyTerms?: string[];
  resetCustomRiskyTerms?: boolean;
}

export interface IntelligenceEvalRunRequest {
  scope?: "active" | "pending" | "learning";
  terms?: string[];
}

export interface IntelligenceEvalCaseResult {
  id: string;
  accepted: boolean;
  score: number;
  expected: string;
  observed: string;
}

export interface IntelligenceEvalRunResponse {
  accepted: boolean;
  reason: string;
  runId: string;
  createdAt: string;
  scope: "active" | "pending" | "learning";
  gatePassed: boolean;
  totalCases: number;
  passedCases: number;
  score: number;
  candidateVersion?: string;
  evaluatedTerms: string[];
  cases: IntelligenceEvalCaseResult[];
}

export interface IntelligenceTuningApplyResponse {
  accepted: boolean;
  reason: string;
  status: IntelligenceTuningStatus;
}

export interface IntelligenceLearningSourceRequest {
  noteId: string;
  approved?: boolean;
}

export interface IntelligenceLearningSourceSummary {
  noteId: string;
  title: string;
  tags: string[];
  approvedAt: string;
}

export interface IntelligenceLearningCandidate {
  term: string;
  sourceNoteId: string;
  sourceTitle: string;
  evidence: string;
}

export interface IntelligenceLearningStatus {
  approvedSources: IntelligenceLearningSourceSummary[];
  candidates: IntelligenceLearningCandidate[];
  candidateVersion?: string;
  lastRunAt?: string;
  lastEvalScore?: number;
  lastEvalVersion?: string;
  lastAppliedAt?: string;
  minApplyScore: number;
  canApplyCandidates: boolean;
}

export interface IntelligenceLearningSourceResponse {
  accepted: boolean;
  reason: string;
  status: IntelligenceLearningStatus;
}

export interface IntelligenceLearningRunResponse {
  accepted: boolean;
  reason: string;
  scannedSources: number;
  candidateCount: number;
  candidates: IntelligenceLearningCandidate[];
  status: IntelligenceLearningStatus;
}

export interface IntelligenceLearningApplyRequest {
  terms?: string[];
  enableSlang?: boolean;
}

export interface IntelligenceLearningApplyResponse {
  accepted: boolean;
  reason: string;
  appliedTerms: string[];
  style: IntelligenceStyleStatus;
  status: IntelligenceLearningStatus;
}

export interface IntelligenceAdaptationStatus {
  justified: boolean;
  recommendedMethod: "none" | "prompt_only" | "lora";
  reason: string;
  totalEvalRuns: number;
  passedActiveRuns: number;
  passedPendingRuns: number;
  passedLearningRuns: number;
  latestActiveScore?: number;
  latestPendingScore?: number;
  latestLearningScore?: number;
  approvedSourceCount: number;
  appliedSlangCount: number;
  customRiskyTermCount: number;
  exportReady: boolean;
  lastExportAt?: string;
  lastExportPath?: string;
}

export interface IntelligenceAdaptationExportResponse {
  accepted: boolean;
  reason: string;
  method: "none" | "prompt_only" | "lora";
  exportPath?: string;
  exampleCount: number;
  status: IntelligenceAdaptationStatus;
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


import { useEffect, useMemo, useState } from "react";
import {
  QUICK_TOGGLES,
  TAB_ORDER,
  type AlertFeedResponse,
  type AutoIndexStatus,
  type AutomationChainResponse,
  type IntelligenceEvalRunResponse,
  type IntelligenceLearningStatus,
  type IntelligenceTuningStatus,
  type IntelligenceStyleStatus,
  type AssistantResponse,
  type FileOrganizeResponse,
  type HubSnapshot,
  type MemoryDocumentChunk,
  type MemoryNote,
  type MindiTabId,
  type PerceptionPermissionStatus,
  type PerceptionAnalyzeResponse,
  type PerceptionSnapshot,
  type PrivacyStatus,
  type PermissionGrant,
  type QuickToggle,
  type SchedulerStatus,
  type SecurityEvent,
  type SecurityScanResponse,
  type SyncQueueItem,
  type WebScrapeResponse,
} from "@mindi/shared";
import {
  addPermissionGrant,
  appControlAction,
  createMemoryNote,
  createTask,
  deleteTask,
  discardIntelligenceTuning,
  updateTaskStatus,
  updateTask,
  fetchAllowedApps,
  getAlertFeed,
  getAutoIndexStatus,
  fetchHubSnapshot,
  fileOrganize,
  importOcrDocument,
  importDocument,
  listPermissionGrants,
  listMemoryNotes,
  scanAutoIndexNow,
  searchDocuments,
  searchMemory,
  sendAssistantRequest,
  getSchedulerStatus,
  getSchedulerNextRun,
  parseTaskTime,
  listSecurityEvents,
  runAutomationChain,
  runAlertAction,
  runSecurityRecovery,
  runSecurityScan,
  runSchedulerScanNow,
  scrapeWeb,
  getPrivacyStatus,
  getIntelligenceLearningStatus,
  getIntelligenceStyleStatus,
  getIntelligenceTuningStatus,
  listIntelligenceEvalHistory,
  runIntelligenceLearning,
  runIntelligenceEval,
  updateIntelligenceLearningSource,
  applyIntelligenceTuning,
  applyIntelligenceLearning,
  stageIntelligenceTuning,
  updatePrivacyStatus,
  updateIntelligenceStyleStatus,
  exportCalendar,
  importCalendar,
  analyzeScreenPerception,
  getPerceptionPermissionStatus,
  listPerceptionSnapshots,
  searchPerceptionSnapshots,
} from "./lib/agent-api";
import {
  enqueueSyncItem,
  loadSyncQueue,
  loadToggleState,
  saveSyncQueue,
  saveToggleState,
} from "./lib/local-state";

const EMPTY_SNAPSHOT: HubSnapshot = {
  status: {
    state: "offline",
    uptimeSeconds: 0,
    listening: false,
    agentVersion: "0.0.0",
    currentProfile: "safe",
  },
  alerts: [],
  tasks: [],
  logs: [],
};

const PERCEPTION_SCREEN_SUBJECT = "perception.screen.capture";
const PERCEPTION_CAMERA_SUBJECT = "perception.camera.capture";

function formatTab(tab: MindiTabId): string {
  return tab[0].toUpperCase() + tab.slice(1);
}

function formatIsoTime(value: string | undefined): string {
  if (!value) {
    return "n/a";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

export default function App() {
  const [tab, setTab] = useState<MindiTabId>("home");
  const [snapshot, setSnapshot] = useState<HubSnapshot>(EMPTY_SNAPSHOT);
  const [permissions, setPermissions] = useState<PermissionGrant[]>([]);
  const [toggles, setToggles] = useState<QuickToggle[]>(() =>
    loadToggleState(QUICK_TOGGLES),
  );
  const [message, setMessage] = useState("");
  const [assistant, setAssistant] = useState<AssistantResponse | null>(null);
  const [syncDepth, setSyncDepth] = useState(loadSyncQueue().length);
  const [networkOnline, setNetworkOnline] = useState<boolean>(navigator.onLine);
  const [sourceDir, setSourceDir] = useState("data/inbox");
  const [targetDir, setTargetDir] = useState("data/sorted");
  const [organizeResult, setOrganizeResult] = useState<FileOrganizeResponse | null>(null);
  const [newAllowFolder, setNewAllowFolder] = useState("data");
  const [allowedApps, setAllowedApps] = useState<string[]>([]);
  const [appId, setAppId] = useState("notepad.exe");
  const [newAllowApp, setNewAllowApp] = useState("notepad.exe");
  const [newAllowDomain, setNewAllowDomain] = useState("example.com");
  const [closeConfirm, setCloseConfirm] = useState(false);
  const [appResult, setAppResult] = useState<string>("No app action run yet.");
  const [memoryQuery, setMemoryQuery] = useState("");
  const [memoryTitle, setMemoryTitle] = useState("");
  const [memoryContent, setMemoryContent] = useState("");
  const [memoryNotes, setMemoryNotes] = useState<MemoryNote[]>([]);
  const [documentQuery, setDocumentQuery] = useState("");
  const [documentImportPath, setDocumentImportPath] = useState("data/inbox");
  const [documentChunks, setDocumentChunks] = useState<MemoryDocumentChunk[]>([]);
  const [ocrImportPath, setOcrImportPath] = useState("data/inbox");
  const [autoIndexStatus, setAutoIndexStatus] = useState<AutoIndexStatus | null>(null);
  const [schedulerStatus, setSchedulerStatus] = useState<SchedulerStatus | null>(null);
  const [securityEvents, setSecurityEvents] = useState<SecurityEvent[]>([]);
  const [securityScanResult, setSecurityScanResult] = useState<SecurityScanResponse | null>(null);
  const [securityStatus, setSecurityStatus] = useState("No security scan yet.");
  const [alertFeed, setAlertFeed] = useState<AlertFeedResponse | null>(null);
  const [alertStatus, setAlertStatus] = useState("No alert action yet.");
  const [privacyStatus, setPrivacyStatus] = useState<PrivacyStatus | null>(null);
  const [privacyUiEnabled, setPrivacyUiEnabled] = useState(true);
  const [intelligenceStyle, setIntelligenceStyle] = useState<IntelligenceStyleStatus | null>(null);
  const [intelligenceLanguageMode, setIntelligenceLanguageMode] = useState<"english" | "taglish" | "tagalog">(
    "english",
  );
  const [intelligenceSlangEnabled, setIntelligenceSlangEnabled] = useState(false);
  const [intelligenceNewSlang, setIntelligenceNewSlang] = useState("solid");
  const [intelligenceLearning, setIntelligenceLearning] = useState<IntelligenceLearningStatus | null>(null);
  const [intelligenceLearningNoteId, setIntelligenceLearningNoteId] = useState("");
  const [intelligenceTuning, setIntelligenceTuning] = useState<IntelligenceTuningStatus | null>(null);
  const [intelligencePreset, setIntelligencePreset] = useState<"safe" | "balanced" | "companion">("safe");
  const [intelligenceVerbosity, setIntelligenceVerbosity] = useState<"brief" | "balanced" | "detailed">(
    "balanced",
  );
  const [intelligenceRiskyTerm, setIntelligenceRiskyTerm] = useState("notepad");
  const [intelligenceEvalResult, setIntelligenceEvalResult] = useState<IntelligenceEvalRunResponse | null>(null);
  const [intelligenceEvalHistory, setIntelligenceEvalHistory] = useState<IntelligenceEvalRunResponse[]>([]);
  const [intelligenceStatus, setIntelligenceStatus] = useState("No intelligence run yet.");
  const [opsScrapeUrl, setOpsScrapeUrl] = useState("https://example.com");
  const [opsScrapeStoreAsNote, setOpsScrapeStoreAsNote] = useState(true);
  const [opsScrapeResult, setOpsScrapeResult] = useState<WebScrapeResponse | null>(null);
  const [opsChainName, setOpsChainName] = useState("ops-daily-brief");
  const [opsChainTaskTitle, setOpsChainTaskTitle] = useState("Review latest security findings");
  const [opsChainNoteTitle, setOpsChainNoteTitle] = useState("Ops brief note");
  const [opsChainResult, setOpsChainResult] = useState<AutomationChainResponse | null>(null);
  const [opsStatus, setOpsStatus] = useState("No ops run yet.");
  const [memoryStatus, setMemoryStatus] = useState("No memory action yet.");
  const [perceptionStatus, setPerceptionStatus] = useState("No perception run yet.");
  const [perceptionResult, setPerceptionResult] = useState<PerceptionAnalyzeResponse | null>(null);
  const [perceptionPermission, setPerceptionPermission] = useState<PerceptionPermissionStatus | null>(null);
  const [perceptionSnapshots, setPerceptionSnapshots] = useState<PerceptionSnapshot[]>([]);
  const [perceptionSnapshotQuery, setPerceptionSnapshotQuery] = useState("");
  const [perceptionSnapshotStatus, setPerceptionSnapshotStatus] = useState("No snapshot query run yet.");
  const [perceptionSelectedSnapshotId, setPerceptionSelectedSnapshotId] = useState<string | null>(null);
  const [perceptionCapturePreview, setPerceptionCapturePreview] = useState<string | null>(null);
  const [perceptionIncludeOcr, setPerceptionIncludeOcr] = useState(true);
  const [perceptionBusy, setPerceptionBusy] = useState(false);
  const [syncReplayBusy, setSyncReplayBusy] = useState(false);
  const [syncReplayRetryToken, setSyncReplayRetryToken] = useState(0);
  const [syncReplayDelayMs, setSyncReplayDelayMs] = useState(2000);

  useEffect(() => {
    saveToggleState(toggles);
  }, [toggles]);

  useEffect(() => {
    const onOnline = () => setNetworkOnline(true);
    const onOffline = () => setNetworkOnline(false);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);

  useEffect(() => {
    let active = true;
    Promise.all([
      fetchHubSnapshot(),
      listPermissionGrants(),
      fetchAllowedApps(),
      listMemoryNotes(20),
      getAutoIndexStatus(),
      getSchedulerStatus(),
      getPerceptionPermissionStatus(),
      listPerceptionSnapshots(12),
      listSecurityEvents("open", 12),
      getAlertFeed(12),
      getPrivacyStatus(),
      getIntelligenceStyleStatus(),
      getIntelligenceLearningStatus(),
      getIntelligenceTuningStatus(),
      listIntelligenceEvalHistory(8),
    ])
      .then(
        ([
          hub,
          grantList,
          appAllowlist,
          notes,
          indexStatus,
          scheduleStatus,
          perceptionPermissionStatus,
          snapshotItems,
          securityItems,
          alertFeedInitial,
          privacyInitial,
          intelligenceStyleInitial,
          intelligenceLearningInitial,
          intelligenceTuningInitial,
          intelligenceEvalHistoryInitial,
        ]) => {
        if (!active) {
          return;
        }
        setSnapshot(hub);
        setPermissions(grantList);
        setAllowedApps(appAllowlist.apps);
        setMemoryNotes(notes);
        setAutoIndexStatus(indexStatus);
        setSchedulerStatus(scheduleStatus);
        setPerceptionPermission(perceptionPermissionStatus);
        setPerceptionSnapshots(snapshotItems);
        setSecurityEvents(securityItems);
        setSecurityStatus(`Loaded ${securityItems.length} open security events.`);
        setAlertFeed(alertFeedInitial);
        setAlertStatus(`Loaded ${alertFeedInitial.items.length} prioritized alerts.`);
        setPrivacyStatus(privacyInitial);
        setPrivacyUiEnabled(privacyInitial.redactionEnabled);
        setIntelligenceStyle(intelligenceStyleInitial);
        setIntelligenceLanguageMode(intelligenceStyleInitial.languageMode);
        setIntelligenceSlangEnabled(intelligenceStyleInitial.slangEnabled);
        setIntelligenceLearning(intelligenceLearningInitial);
        setIntelligenceLearningNoteId((notes[0] && notes[0].id) || "");
        setIntelligenceTuning(intelligenceTuningInitial);
        setIntelligencePreset((intelligenceTuningInitial.pending ?? intelligenceTuningInitial.active).preset);
        setIntelligenceVerbosity(
          (intelligenceTuningInitial.pending ?? intelligenceTuningInitial.active).responseVerbosity,
        );
        setIntelligenceEvalHistory(intelligenceEvalHistoryInitial);
        setIntelligenceStatus(`Loaded ${intelligenceEvalHistoryInitial.length} eval history items.`);
        if (snapshotItems.length > 0) {
          setPerceptionSelectedSnapshotId(snapshotItems[0].id);
          setPerceptionSnapshotStatus(`Loaded ${snapshotItems.length} recent snapshots.`);
        }
        },
      )
      .catch(() => {
        if (active) {
          setSnapshot((current) => ({
            ...current,
            status: {
              ...current.status,
              state: "offline",
            },
          }));
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function replaySyncItem(item: SyncQueueItem): Promise<boolean> {
    const payload = item.payload as Record<string, unknown>;

    if (item.type === "chat") {
      const text = typeof payload.text === "string" ? payload.text.trim() : "";
      if (!text) {
        return false;
      }
      const replayTab =
        typeof payload.tab === "string" && TAB_ORDER.includes(payload.tab as MindiTabId)
          ? (payload.tab as MindiTabId)
          : undefined;
      await sendAssistantRequest({
        text,
        mode: "chat",
        tab: replayTab,
      });
      return true;
    }

    if (item.type === "note") {
      const title = typeof payload.title === "string" ? payload.title.trim() : "";
      const content = typeof payload.content === "string" ? payload.content.trim() : "";
      if (!title || !content) {
        return false;
      }
      await createMemoryNote({ title, content, tags: [] });
      return true;
    }

    if (item.type === "ocr") {
      const path = typeof payload.path === "string" ? payload.path.trim() : "";
      if (!path) {
        return false;
      }
      await importOcrDocument(path);
      return true;
    }

    if (item.type === "action") {
      const action = typeof payload.action === "string" ? payload.action : "";
      if (action === "create_task") {
        const title = typeof payload.title === "string" ? payload.title.trim() : "";
        if (!title) {
          return false;
        }
        await createTask({
          title,
          dueAt: typeof payload.dueAt === "string" ? payload.dueAt : undefined,
          recurrence:
            payload.recurrence === "daily" || payload.recurrence === "weekly"
              ? payload.recurrence
              : undefined,
        });
        return true;
      }
      if (action === "update_task_status") {
        const taskId = typeof payload.taskId === "string" ? payload.taskId : "";
        const status = payload.status;
        if (
          !taskId ||
          (status !== "todo" && status !== "in_progress" && status !== "done")
        ) {
          return false;
        }
        await updateTaskStatus(taskId, { status });
        return true;
      }
      if (action === "update_task") {
        const taskId = typeof payload.taskId === "string" ? payload.taskId : "";
        if (!taskId) {
          return false;
        }
        const recurrence =
          payload.recurrence === "daily" || payload.recurrence === "weekly"
            ? payload.recurrence
            : payload.recurrence === null
              ? null
              : undefined;
        const status =
          payload.status === "todo" || payload.status === "in_progress" || payload.status === "done"
            ? payload.status
            : undefined;
        await updateTask(taskId, {
          title: typeof payload.title === "string" ? payload.title : undefined,
          dueAt:
            typeof payload.dueAt === "string"
              ? payload.dueAt
              : payload.dueAt === null
                ? null
                : undefined,
          recurrence,
          status,
        });
        return true;
      }
      if (action === "delete_task") {
        const taskId = typeof payload.taskId === "string" ? payload.taskId : "";
        if (!taskId) {
          return false;
        }
        await deleteTask(taskId);
        return true;
      }
      if (action === "add_permission") {
        const scope = payload.scope;
        const subject = typeof payload.subject === "string" ? payload.subject : "";
        if (
          !subject ||
          (scope !== "folder" && scope !== "app" && scope !== "domain" && scope !== "action")
        ) {
          return false;
        }
        await addPermissionGrant({
          scope,
          subject,
          decision: "allow",
        });
        return true;
      }
      if (action === "file_organize") {
        const mode = payload.mode;
        const sourceDir = typeof payload.sourceDir === "string" ? payload.sourceDir : "";
        const targetDir = typeof payload.targetDir === "string" ? payload.targetDir : "";
        if (!sourceDir || !targetDir || (mode !== "preview" && mode !== "apply")) {
          return false;
        }
        await fileOrganize({ sourceDir, targetDir, mode });
        return true;
      }
      if (action === "app_control") {
        const command = payload.command;
        const appId = typeof payload.appId === "string" ? payload.appId : "";
        if (!appId || (command !== "open" && command !== "focus" && command !== "close")) {
          return false;
        }
        await appControlAction({ action: command, appId, confirm: command === "close" });
        return true;
      }
      if (action === "document_import") {
        const path = typeof payload.path === "string" ? payload.path.trim() : "";
        if (!path) {
          return false;
        }
        await importDocument(path);
        return true;
      }
      if (action === "web_scrape") {
        const url = typeof payload.url === "string" ? payload.url.trim() : "";
        if (!url) {
          return false;
        }
        await scrapeWeb({
          url,
          maxChars: typeof payload.maxChars === "number" ? payload.maxChars : 3500,
          storeAsNote: Boolean(payload.storeAsNote),
        });
        return true;
      }
      if (action === "security_scan") {
        await runSecurityScan();
        return true;
      }
      if (action === "security_recover") {
        const eventId = typeof payload.eventId === "string" ? payload.eventId : "";
        const recoveryAction = payload.recoveryAction;
        if (
          !eventId ||
          (recoveryAction !== "dismiss" &&
            recoveryAction !== "deny_app" &&
            recoveryAction !== "kill_process")
        ) {
          return false;
        }
        await runSecurityRecovery({
          eventId,
          action: recoveryAction,
          target: typeof payload.target === "string" ? payload.target : undefined,
          confirm: Boolean(payload.confirm),
        });
        return true;
      }
      if (action === "automation_chain") {
        const name = typeof payload.name === "string" ? payload.name : "ops-chain";
        const scrapeUrl = typeof payload.scrapeUrl === "string" ? payload.scrapeUrl : "";
        const taskTitle = typeof payload.taskTitle === "string" ? payload.taskTitle : "";
        const noteTitle = typeof payload.noteTitle === "string" ? payload.noteTitle : "";
        if (!scrapeUrl || !taskTitle || !noteTitle) {
          return false;
        }
        await runAutomationChain({
          name,
          continueOnFailure: false,
          steps: [
            { kind: "web_scrape", url: scrapeUrl, storeAsNote: true },
            { kind: "security_scan" },
            { kind: "create_task", title: taskTitle },
            { kind: "create_note", title: noteTitle, text: `Automation chain completed for ${name}.` },
          ],
        });
        return true;
      }
      if (action === "alert_action") {
        const alertId = typeof payload.alertId === "string" ? payload.alertId : "";
        const alertAction = payload.alertAction;
        if (
          !alertId ||
          (alertAction !== "dismiss" &&
            alertAction !== "create_recovery_task" &&
            alertAction !== "export_report")
        ) {
          return false;
        }
        await runAlertAction({
          alertId,
          action: alertAction,
        });
        return true;
      }
      if (action === "privacy_update") {
        const enabled = Boolean(payload.redactionEnabled);
        await updatePrivacyStatus({ redactionEnabled: enabled });
        return true;
      }
      if (action === "intelligence_style_update") {
        const languageMode = payload.languageMode;
        if (languageMode !== "english" && languageMode !== "taglish" && languageMode !== "tagalog") {
          return false;
        }
        await updateIntelligenceStyleStatus({
          languageMode,
          slangEnabled: Boolean(payload.slangEnabled),
          addSlangTerms:
            typeof payload.addSlangTerm === "string" && payload.addSlangTerm.trim()
              ? [payload.addSlangTerm.trim()]
              : [],
        });
        return true;
      }
    }

    return false;
  }

  useEffect(() => {
    if (!networkOnline || syncReplayBusy || syncDepth === 0) {
      return;
    }
    let active = true;
    let retryTimer: number | null = null;
    setSyncReplayBusy(true);

    async function replayQueue(): Promise<void> {
      const queue = loadSyncQueue();
      if (queue.length === 0) {
        if (active) {
          setSyncDepth(0);
          setSyncReplayBusy(false);
        }
        return;
      }

      const remaining: SyncQueueItem[] = [];
      let replayedAny = false;
      for (let index = 0; index < queue.length; index += 1) {
        const item = queue[index];
        try {
          const ok = await replaySyncItem(item);
          if (ok) {
            replayedAny = true;
          } else {
            remaining.push({ ...item, status: "failed" });
          }
        } catch {
          remaining.push({ ...item, status: "failed" });
          if (!navigator.onLine) {
            remaining.push(...queue.slice(index + 1));
            break;
          }
        }
      }

      if (!active) {
        return;
      }
      saveSyncQueue(remaining);
      setSyncDepth(remaining.length);
      setSyncReplayBusy(false);
      if (remaining.length > 0) {
        setSyncReplayDelayMs((current) => Math.min(current * 2, 30000));
        retryTimer = window.setTimeout(() => {
          setSyncReplayRetryToken((value) => value + 1);
        }, syncReplayDelayMs);
      } else {
        setSyncReplayDelayMs(2000);
      }

      if (replayedAny) {
        try {
          const hub = await fetchHubSnapshot();
          if (active) {
            setSnapshot(hub);
          }
        } catch {
          // No-op, queue already retained for failed items.
        }
      }
    }

    void replayQueue();
    return () => {
      active = false;
      if (retryTimer !== null) {
        window.clearTimeout(retryTimer);
      }
    };
  }, [networkOnline, syncDepth, syncReplayRetryToken]);

  const topStatus = useMemo(() => {
    if (!networkOnline) {
      return "offline";
    }
    return snapshot.status.state;
  }, [networkOnline, snapshot.status.state]);

  async function handleSend() {
    const text = message.trim();
    if (!text) {
      return;
    }

    setMessage("");
    try {
      const response = await sendAssistantRequest({
        text,
        mode: "chat",
        tab,
      });
      setAssistant(response);
    } catch {
      enqueueSyncItem({ type: "chat", payload: { text, tab } });
      setSyncDepth(loadSyncQueue().length);
      setAssistant({
        reply: "Queued offline. I will sync this request when the local agent is available.",
        decision: {
          allowed: true,
          tier: "read_only",
          reason: "offline_queue",
          requiresUnlock: false,
        },
        suggestedActions: ["Open local agent", "Retry chat"],
        status: "queued",
      });
    }
  }

  async function addTask() {
    const title = prompt("Task title");
    if (!title) {
      return;
    }
    const dueAtRaw = prompt(
      "Due time (optional): ISO or natural text like 'tomorrow 9am', 'next monday 14:00', 'in 2 hours'",
    ) ?? "";
    const dueAtText = dueAtRaw.trim();
    let dueAt: string | undefined;
    if (dueAtText) {
      try {
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
        const parsed = await parseTaskTime({ text: dueAtText, timezone });
        if (!parsed.accepted || !parsed.dueAt) {
          setAssistant({
            reply: `Could not parse due time: ${parsed.reason}.`,
            decision: {
              allowed: false,
              tier: "read_only",
              reason: "invalid_due_time",
              requiresUnlock: false,
            },
            suggestedActions: ["Use ISO time", "Try 'tomorrow 9am'"],
            status: "blocked",
          });
          return;
        }
        dueAt = parsed.dueAt;
      } catch {
        setAssistant({
          reply: "Due-time parser unavailable while offline.",
          decision: {
            allowed: false,
            tier: "read_only",
            reason: "parse_service_unavailable",
            requiresUnlock: false,
          },
          suggestedActions: ["Run local agent", "Use ISO time"],
          status: "blocked",
        });
        return;
      }
    }
    const recurrenceRaw =
      (prompt("Recurrence (optional): none | daily | weekly", "none") ?? "none").trim().toLowerCase();
    const recurrence =
      recurrenceRaw === "daily" || recurrenceRaw === "weekly"
        ? (recurrenceRaw as "daily" | "weekly")
        : undefined;
    try {
      const newTask = await createTask({ title, dueAt, recurrence });
      setSnapshot((current) => ({ ...current, tasks: [newTask, ...current.tasks] }));
      if (dueAt && recurrence) {
        const preview = await getSchedulerNextRun({ dueAt, recurrence });
        if (preview.accepted && preview.nextRunAt) {
          setAssistant({
            reply: `Recurring task set. Next run after due is ${preview.nextRunAt}.`,
            decision: {
              allowed: true,
              tier: "reversible",
              reason: "scheduler_preview",
              requiresUnlock: false,
            },
            suggestedActions: ["Run scheduler scan", "View tasks"],
            status: "ready",
          });
        }
      }
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: { action: "create_task", title, dueAt, recurrence },
      });
      setSyncDepth(loadSyncQueue().length);
    }
  }

  async function runTaskStatusChange(taskId: string, status: "todo" | "in_progress" | "done") {
    try {
      const updated = await updateTaskStatus(taskId, { status });
      setSnapshot((current) => ({
        ...current,
        tasks: current.tasks.map((task) => (task.id === updated.id ? updated : task)),
      }));
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: { action: "update_task_status", taskId, status },
      });
      setSyncDepth(loadSyncQueue().length);
    }
  }

  async function runTaskEdit(taskId: string) {
    const current = snapshot.tasks.find((task) => task.id === taskId);
    if (!current) {
      return;
    }
    const titleInput = prompt("Task title", current.title);
    if (titleInput === null) {
      return;
    }
    const title = titleInput.trim();
    if (!title) {
      return;
    }

    const dueInput = prompt(
      "Due time (optional): ISO or natural text. Leave empty to clear.",
      current.dueAt ?? "",
    );
    if (dueInput === null) {
      return;
    }
    let dueAt: string | null | undefined;
    const dueText = dueInput.trim();
    if (!dueText) {
      dueAt = null;
    } else {
      try {
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
        const parsed = await parseTaskTime({ text: dueText, timezone });
        if (!parsed.accepted || !parsed.dueAt) {
          setAssistant({
            reply: `Could not parse due time: ${parsed.reason}.`,
            decision: {
              allowed: false,
              tier: "read_only",
              reason: "invalid_due_time",
              requiresUnlock: false,
            },
            suggestedActions: ["Use ISO time", "Try 'tomorrow 9am'"],
            status: "blocked",
          });
          return;
        }
        dueAt = parsed.dueAt;
      } catch {
        setAssistant({
          reply: "Due-time parser unavailable while offline.",
          decision: {
            allowed: false,
            tier: "read_only",
            reason: "parse_service_unavailable",
            requiresUnlock: false,
          },
          suggestedActions: ["Run local agent", "Use ISO time"],
          status: "blocked",
        });
        return;
      }
    }

    const recurrenceInput = prompt(
      "Recurrence: none | daily | weekly",
      current.recurrence ?? "none",
    );
    if (recurrenceInput === null) {
      return;
    }
    const recurrenceText = recurrenceInput.trim().toLowerCase();
    let recurrence: "daily" | "weekly" | null = null;
    if (recurrenceText === "daily" || recurrenceText === "weekly") {
      recurrence = recurrenceText;
    } else if (recurrenceText !== "none" && recurrenceText !== "") {
      return;
    }

    try {
      const updated = await updateTask(taskId, { title, dueAt, recurrence });
      setSnapshot((currentSnapshot) => ({
        ...currentSnapshot,
        tasks: currentSnapshot.tasks.map((task) => (task.id === updated.id ? updated : task)),
      }));
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: { action: "update_task", taskId, title, dueAt, recurrence },
      });
      setSyncDepth(loadSyncQueue().length);
    }
  }

  async function runTaskDelete(taskId: string) {
    const allowed = confirm("Delete this task?");
    if (!allowed) {
      return;
    }
    try {
      await deleteTask(taskId);
      setSnapshot((current) => ({
        ...current,
        tasks: current.tasks.filter((task) => task.id !== taskId),
      }));
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: { action: "delete_task", taskId },
      });
      setSyncDepth(loadSyncQueue().length);
    }
  }

  async function addFolderAllowGrant() {
    const subject = newAllowFolder.trim();
    if (!subject) {
      return;
    }
    try {
      const created = await addPermissionGrant({
        scope: "folder",
        subject,
        decision: "allow",
      });
      setPermissions((current) => [created, ...current]);
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: { action: "add_permission", scope: "folder", subject },
      });
      setSyncDepth(loadSyncQueue().length);
    }
  }

  async function addAppAllowGrant() {
    const subject = newAllowApp.trim();
    if (!subject) {
      return;
    }
    try {
      const created = await addPermissionGrant({
        scope: "app",
        subject,
        decision: "allow",
      });
      setPermissions((current) => [created, ...current]);
      setAllowedApps((current) =>
        current.some((app) => app.toLowerCase() === subject.toLowerCase())
          ? current
          : [subject, ...current],
      );
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: { action: "add_permission", scope: "app", subject },
      });
      setSyncDepth(loadSyncQueue().length);
    }
  }

  async function addDomainAllowGrant() {
    const subject = newAllowDomain.trim();
    if (!subject) {
      return;
    }
    try {
      const created = await addPermissionGrant({
        scope: "domain",
        subject,
        decision: "allow",
      });
      setPermissions((current) => [created, ...current]);
      setOpsStatus(`Allowed domain: ${subject}`);
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: { action: "add_permission", scope: "domain", subject },
      });
      setSyncDepth(loadSyncQueue().length);
      setOpsStatus("Domain allow grant queued for sync.");
    }
  }

  async function addPerceptionActionAllowGrant(subject: string) {
    const normalized = subject.trim();
    if (!normalized) {
      return;
    }
    try {
      const created = await addPermissionGrant({
        scope: "action",
        subject: normalized,
        decision: "allow",
      });
      setPermissions((current) => [created, ...current]);
      const status = await getPerceptionPermissionStatus();
      setPerceptionPermission(status);
      setPerceptionStatus(`Permission granted: ${normalized}`);
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: { action: "add_permission", scope: "action", subject: normalized },
      });
      setSyncDepth(loadSyncQueue().length);
      setPerceptionStatus("Permission grant queued for sync.");
    }
  }

  async function refreshPerceptionSnapshots() {
    try {
      const items = await listPerceptionSnapshots(12);
      setPerceptionSnapshots(items);
      if (items.length > 0 && !items.some((item) => item.id === perceptionSelectedSnapshotId)) {
        setPerceptionSelectedSnapshotId(items[0].id);
      }
      setPerceptionSnapshotStatus(`Loaded ${items.length} recent snapshots.`);
    } catch {
      setPerceptionSnapshotStatus("Snapshot reload failed while offline.");
    }
  }

  async function runPerceptionSnapshotSearch() {
    const query = perceptionSnapshotQuery.trim();
    if (!query) {
      await refreshPerceptionSnapshots();
      return;
    }
    try {
      const response = await searchPerceptionSnapshots(query, 12);
      setPerceptionSnapshots(response.items);
      if (response.items.length > 0) {
        setPerceptionSelectedSnapshotId(response.items[0].id);
      }
      setPerceptionSnapshotStatus(`Search hits: ${response.items.length}`);
    } catch {
      setPerceptionSnapshotStatus("Snapshot search failed while offline.");
    }
  }

  async function runOrganize(mode: "preview" | "apply") {
    try {
      const result = await fileOrganize({ sourceDir, targetDir, mode });
      setOrganizeResult(result);
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: { action: "file_organize", mode, sourceDir, targetDir },
      });
      setSyncDepth(loadSyncQueue().length);
    }
  }

  async function runAppAction(action: "open" | "focus" | "close") {
    const target = appId.trim();
    if (!target) {
      return;
    }
    try {
      const response = await appControlAction({
        action,
        appId: target,
        confirm: action === "close" ? closeConfirm : true,
      });
      setAppResult(
        `${action}: accepted=${String(response.accepted)} tier=${response.tier} reason=${response.reason}`,
      );
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: { action: "app_control", command: action, appId: target },
      });
      setSyncDepth(loadSyncQueue().length);
      setAppResult(`${action}: queued for later sync`);
    }
  }

  async function addMemoryNote() {
    const title = memoryTitle.trim();
    const content = memoryContent.trim();
    if (!title || !content) {
      return;
    }

    try {
      const note = await createMemoryNote({
        title,
        content,
        tags: [],
      });
      setMemoryNotes((current) => [note, ...current]);
      setIntelligenceLearningNoteId(note.id);
      setMemoryTitle("");
      setMemoryContent("");
      setMemoryStatus("Note stored locally.");
    } catch {
      enqueueSyncItem({
        type: "note",
        payload: { title, content },
      });
      setSyncDepth(loadSyncQueue().length);
      setMemoryStatus("Agent unavailable. Note queued for sync.");
    }
  }

  async function runMemorySearch() {
    try {
      const response = await searchMemory(memoryQuery);
      setMemoryNotes(response.items);
      setMemoryStatus(`Loaded ${response.items.length} notes.`);
    } catch {
      setMemoryStatus("Search failed while offline.");
    }
  }

  async function runDocumentImport() {
    const path = documentImportPath.trim();
    if (!path) {
      return;
    }
    try {
      const response = await importDocument(path);
      if (response.accepted) {
        setMemoryStatus(
          `Document indexed: ${response.document?.title} (${response.document?.chunkCount} chunks)`,
        );
      } else {
        setMemoryStatus(`Document import blocked: ${response.reason}`);
      }
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: { action: "document_import", path },
      });
      setSyncDepth(loadSyncQueue().length);
      setMemoryStatus("Document import queued for sync.");
    }
  }

  async function runDocumentSearch() {
    try {
      const response = await searchDocuments(documentQuery);
      setDocumentChunks(response.items);
      setMemoryStatus(`Document hits: ${response.items.length}`);
    } catch {
      setMemoryStatus("Document search failed while offline.");
    }
  }

  async function runOcrImport() {
    const path = ocrImportPath.trim();
    if (!path) {
      return;
    }
    try {
      const response = await importOcrDocument(path);
      if (response.accepted) {
        setMemoryStatus(
          `OCR indexed: ${response.document?.title} (${response.document?.chunkCount} chunks)`,
        );
      } else {
        setMemoryStatus(`OCR import blocked: ${response.reason}`);
      }
    } catch {
      enqueueSyncItem({
        type: "ocr",
        payload: { path },
      });
      setSyncDepth(loadSyncQueue().length);
      setMemoryStatus("OCR import queued for sync.");
    }
  }

  async function runAutoIndexScanNow() {
    try {
      const status = await scanAutoIndexNow();
      setAutoIndexStatus(status);
      setMemoryStatus(`Auto-index run complete. Indexed ${status.indexedLastRun} files.`);
    } catch {
      setMemoryStatus("Auto-index scan failed.");
    }
  }

  async function runTaskSchedulerScanNow() {
    try {
      const status = await runSchedulerScanNow();
      setSchedulerStatus(status);
    } catch {
      // Keep UI steady when scheduler endpoint is unreachable.
    }
  }

  async function runCalendarExport() {
    try {
      const result = await exportCalendar({
        fileName: "mindi-tasks.ics",
        includeCompleted: false,
      });
      if (result.accepted) {
        setAssistant({
          reply: `Calendar exported: ${result.filePath} (${result.eventCount} events).`,
          decision: {
            allowed: true,
            tier: "reversible",
            reason: "calendar_exported",
            requiresUnlock: false,
          },
          suggestedActions: ["Open exported file", "Share calendar"],
          status: "ready",
        });
      } else {
        setAssistant({
          reply: `Calendar export failed: ${result.reason}`,
          decision: {
            allowed: false,
            tier: "read_only",
            reason: "calendar_export_failed",
            requiresUnlock: false,
          },
          suggestedActions: ["Retry export"],
          status: "blocked",
        });
      }
    } catch {
      setAssistant({
        reply: "Calendar export unavailable while offline.",
        decision: {
          allowed: false,
          tier: "read_only",
          reason: "calendar_export_unavailable",
          requiresUnlock: false,
        },
        suggestedActions: ["Run local agent", "Retry export"],
        status: "blocked",
      });
    }
  }

  async function runCalendarImport() {
    const filePath = prompt(
      "Calendar file path (.ics)",
      "data/runtime/exports/mindi-tasks.ics",
    );
    if (!filePath) {
      return;
    }
    try {
      const result = await importCalendar({ filePath: filePath.trim() });
      if (result.accepted) {
        setAssistant({
          reply: `Calendar imported: ${result.importedCount} events converted to tasks.`,
          decision: {
            allowed: true,
            tier: "reversible",
            reason: "calendar_imported",
            requiresUnlock: false,
          },
          suggestedActions: ["View tasks", "Run scheduler scan"],
          status: "ready",
        });
      } else {
        setAssistant({
          reply: `Calendar import failed: ${result.reason}`,
          decision: {
            allowed: false,
            tier: "read_only",
            reason: "calendar_import_failed",
            requiresUnlock: false,
          },
          suggestedActions: ["Retry import"],
          status: "blocked",
        });
      }
    } catch {
      setAssistant({
        reply: "Calendar import unavailable while offline.",
        decision: {
          allowed: false,
          tier: "read_only",
          reason: "calendar_import_unavailable",
          requiresUnlock: false,
        },
        suggestedActions: ["Run local agent", "Retry import"],
        status: "blocked",
      });
    }
  }

  async function runCaptureAndAnalyzeScreen() {
    if (perceptionBusy) {
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
      setPerceptionStatus("Screen capture is not available in this runtime.");
      return;
    }

    try {
      const status = await getPerceptionPermissionStatus();
      setPerceptionPermission(status);
      if (!status.screenAllowed) {
        const reason =
          status.screenDecision === "deny"
            ? "screen permission denied by safety policy."
            : "screen permission required. Allow it in Vision.";
        setPerceptionStatus(`Perception blocked: ${reason}`);
        return;
      }
    } catch {
      setPerceptionStatus("Unable to verify screen permission status.");
      return;
    }

    let stream: MediaStream | null = null;
    setPerceptionBusy(true);
    setPerceptionStatus("Waiting for screen selection...");

    try {
      stream = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: false,
      });
      const video = document.createElement("video");
      video.srcObject = stream;

      await new Promise<void>((resolve, reject) => {
        const cleanup = () => {
          video.onloadedmetadata = null;
          video.onerror = null;
        };
        video.onloadedmetadata = () => {
          cleanup();
          resolve();
        };
        video.onerror = () => {
          cleanup();
          reject(new Error("capture_metadata_failed"));
        };
      });

      await video.play();
      const width = Math.max(1, video.videoWidth || 1);
      const height = Math.max(1, video.videoHeight || 1);

      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d");
      if (!context) {
        throw new Error("capture_canvas_unavailable");
      }
      context.drawImage(video, 0, 0, width, height);
      const imageDataUrl = canvas.toDataURL("image/png");
      setPerceptionCapturePreview(imageDataUrl);

      const response = await analyzeScreenPerception({
        imageDataUrl,
        includeOcr: perceptionIncludeOcr,
        maxBlocks: 25,
      });
      setPerceptionResult(response);
      if (response.accepted) {
        setPerceptionStatus(
          `Perception ok: ${response.blocks.length} blocks, textLength=${response.textLength}, snapshot=${response.snapshotId ?? "n/a"}, redacted=${String(response.storageRedacted)} (${response.redactionCount}).`,
        );
        await refreshPerceptionSnapshots();
        if (response.snapshotId) {
          setPerceptionSelectedSnapshotId(response.snapshotId);
        }
      } else {
        setPerceptionStatus(`Perception failed: ${response.reason}`);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "capture_failed";
      setPerceptionStatus(`Screen capture failed: ${message}`);
    } finally {
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
      }
      setPerceptionBusy(false);
    }
  }

  async function runOpsWebScrape() {
    const url = opsScrapeUrl.trim();
    if (!url) {
      return;
    }
    try {
      const response = await scrapeWeb({
        url,
        maxChars: 3500,
        storeAsNote: opsScrapeStoreAsNote,
      });
      setOpsScrapeResult(response);
      if (response.accepted) {
        setOpsStatus(
          `Scrape ok: textLength=${response.textLength}, links=${response.links.length}, storedNote=${response.storedNoteId ?? "none"}, redacted=${String(response.storageRedacted)} (${response.redactionCount}).`,
        );
      } else if (response.reason === "domain_not_allowed") {
        setOpsStatus("Scrape blocked by domain policy. Add domain allow in Control or Ops.");
      } else {
        setOpsStatus(`Scrape failed: ${response.reason}`);
      }
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: { action: "web_scrape", url, maxChars: 3500, storeAsNote: opsScrapeStoreAsNote },
      });
      setSyncDepth(loadSyncQueue().length);
      setOpsStatus("Scrape job queued for sync.");
    }
  }

  async function refreshSecurityEvents() {
    try {
      const items = await listSecurityEvents("open", 12);
      setSecurityEvents(items);
      setSecurityStatus(`Loaded ${items.length} open security events.`);
    } catch {
      setSecurityStatus("Security events unavailable while offline.");
    }
  }

  async function refreshAlertFeed() {
    try {
      const response = await getAlertFeed(12);
      setAlertFeed(response);
      setAlertStatus(
        `alerts=${response.total} (critical=${response.critical}, warning=${response.warning}, info=${response.info})`,
      );
    } catch {
      setAlertStatus("Alert feed unavailable while offline.");
    }
  }

  async function refreshPrivacyStatus() {
    try {
      const status = await getPrivacyStatus();
      setPrivacyStatus(status);
      setPrivacyUiEnabled(status.redactionEnabled);
    } catch {
      setOpsStatus("Privacy status unavailable while offline.");
    }
  }

  async function runPrivacyUpdate(redactionEnabled: boolean) {
    try {
      const status = await updatePrivacyStatus({ redactionEnabled });
      setPrivacyStatus(status);
      setPrivacyUiEnabled(status.redactionEnabled);
      setOpsStatus(`Privacy updated: redaction=${String(status.redactionEnabled)}.`);
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: { action: "privacy_update", redactionEnabled },
      });
      setSyncDepth(loadSyncQueue().length);
      setOpsStatus("Privacy update queued for sync.");
    }
  }

  async function refreshIntelligenceState() {
    try {
      const [style, learning, tuning, history] = await Promise.all([
        getIntelligenceStyleStatus(),
        getIntelligenceLearningStatus(),
        getIntelligenceTuningStatus(),
        listIntelligenceEvalHistory(8),
      ]);
      setIntelligenceStyle(style);
      setIntelligenceLanguageMode(style.languageMode);
      setIntelligenceSlangEnabled(style.slangEnabled);
      setIntelligenceLearning(learning);
      setIntelligenceTuning(tuning);
      setIntelligencePreset((tuning.pending ?? tuning.active).preset);
      setIntelligenceVerbosity((tuning.pending ?? tuning.active).responseVerbosity);
      setIntelligenceEvalHistory(history);
      setIntelligenceStatus(`Intelligence loaded: ${history.length} eval runs.`);
    } catch {
      setIntelligenceStatus("Intelligence status unavailable while offline.");
    }
  }

  async function runIntelligenceStyleUpdate() {
    const slangTerm = intelligenceNewSlang.trim();
    try {
      const style = await updateIntelligenceStyleStatus({
        languageMode: intelligenceLanguageMode,
        slangEnabled: intelligenceSlangEnabled,
        addSlangTerms: slangTerm ? [slangTerm] : [],
      });
      setIntelligenceStyle(style);
      setIntelligenceLanguageMode(style.languageMode);
      setIntelligenceSlangEnabled(style.slangEnabled);
      setIntelligenceStatus("Intelligence style updated.");
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: {
          action: "intelligence_style_update",
          languageMode: intelligenceLanguageMode,
          slangEnabled: intelligenceSlangEnabled,
          addSlangTerm: slangTerm,
        },
      });
      setSyncDepth(loadSyncQueue().length);
      setIntelligenceStatus("Intelligence style update queued for sync.");
    }
  }

  async function runIntelligenceLearningSourceUpdate(approved: boolean) {
    const noteId = intelligenceLearningNoteId.trim();
    if (!noteId) {
      setIntelligenceStatus("Choose a note before updating learning approval.");
      return;
    }
    try {
      const response = await updateIntelligenceLearningSource({ noteId, approved });
      setIntelligenceLearning(response.status);
      setIntelligenceStatus(
        response.accepted
          ? approved
            ? "Learning source approved."
            : "Learning source removed."
          : `Learning source blocked: ${response.reason}.`,
      );
    } catch {
      setIntelligenceStatus("Learning source update failed.");
    }
  }

  async function runIntelligenceLearningNow() {
    try {
      const response = await runIntelligenceLearning();
      setIntelligenceLearning(response.status);
      setIntelligenceStatus(
        response.accepted
          ? `Learning run: sources=${response.scannedSources}, candidates=${response.candidateCount}.`
          : "No approved learning sources.",
      );
    } catch {
      setIntelligenceStatus("Learning run failed.");
    }
  }

  async function runIntelligenceLearningEvalNow() {
    try {
      const terms = intelligenceLearning?.candidates.map((item) => item.term) ?? [];
      const result = await runIntelligenceEval({ scope: "learning", terms });
      setIntelligenceEvalResult(result);
      const [learning, history] = await Promise.all([
        getIntelligenceLearningStatus(),
        listIntelligenceEvalHistory(8),
      ]);
      setIntelligenceLearning(learning);
      setIntelligenceEvalHistory(history);
      setIntelligenceStatus(
        result.accepted
          ? `Learning eval: score=${result.score.toFixed(2)} gate=${String(result.gatePassed)}.`
          : `Learning eval blocked: ${result.reason}.`,
      );
    } catch {
      setIntelligenceStatus("Learning eval failed.");
    }
  }

  async function runIntelligenceLearningApplyNow() {
    try {
      const terms = intelligenceLearning?.candidates.map((item) => item.term) ?? [];
      const response = await applyIntelligenceLearning({ terms, enableSlang: true });
      setIntelligenceLearning(response.status);
      setIntelligenceStyle(response.style);
      setIntelligenceLanguageMode(response.style.languageMode);
      setIntelligenceSlangEnabled(response.style.slangEnabled);
      setIntelligenceStatus(
        response.accepted
          ? `Learned slang applied: ${response.appliedTerms.join(", ")}.`
          : `Learning apply blocked: ${response.reason}.`,
      );
    } catch {
      setIntelligenceStatus("Learning apply failed.");
    }
  }

  async function runIntelligenceEvalNow() {
    try {
      const result = await runIntelligenceEval({ scope: "active" });
      setIntelligenceEvalResult(result);
      const history = await listIntelligenceEvalHistory(8);
      setIntelligenceEvalHistory(history);
      setIntelligenceStatus(
        `Eval complete: score=${result.score.toFixed(2)} (${result.passedCases}/${result.totalCases}).`,
      );
    } catch {
      setIntelligenceStatus("Eval run failed.");
    }
  }

  async function runIntelligenceTuningStage() {
    const riskyTerm = intelligenceRiskyTerm.trim();
    try {
      const tuning = await stageIntelligenceTuning({
        preset: intelligencePreset,
        responseVerbosity: intelligenceVerbosity,
        addCustomRiskyTerms: riskyTerm ? [riskyTerm] : [],
      });
      setIntelligenceTuning(tuning);
      setIntelligencePreset((tuning.pending ?? tuning.active).preset);
      setIntelligenceVerbosity((tuning.pending ?? tuning.active).responseVerbosity);
      setIntelligenceStatus(`Pending tuning staged: ${tuning.pendingVersion ?? "unknown"}.`);
    } catch {
      setIntelligenceStatus("Pending tuning stage failed.");
    }
  }

  async function runIntelligencePendingEval() {
    try {
      const result = await runIntelligenceEval({ scope: "pending" });
      setIntelligenceEvalResult(result);
      const [tuning, history] = await Promise.all([
        getIntelligenceTuningStatus(),
        listIntelligenceEvalHistory(8),
      ]);
      setIntelligenceTuning(tuning);
      setIntelligencePreset((tuning.pending ?? tuning.active).preset);
      setIntelligenceVerbosity((tuning.pending ?? tuning.active).responseVerbosity);
      setIntelligenceEvalHistory(history);
      setIntelligenceStatus(
        result.accepted
          ? `Pending eval: score=${result.score.toFixed(2)} gate=${String(result.gatePassed)}.`
          : "No pending tuning candidate to evaluate.",
      );
    } catch {
      setIntelligenceStatus("Pending eval failed.");
    }
  }

  async function runIntelligenceTuningApplyNow() {
    try {
      const response = await applyIntelligenceTuning();
      setIntelligenceTuning(response.status);
      setIntelligencePreset((response.status.pending ?? response.status.active).preset);
      setIntelligenceVerbosity((response.status.pending ?? response.status.active).responseVerbosity);
      setIntelligenceStatus(
        response.accepted ? "Pending tuning applied." : `Apply blocked: ${response.reason}.`,
      );
    } catch {
      setIntelligenceStatus("Apply tuning failed.");
    }
  }

  async function runIntelligenceTuningDiscardNow() {
    try {
      const tuning = await discardIntelligenceTuning();
      setIntelligenceTuning(tuning);
      setIntelligencePreset((tuning.pending ?? tuning.active).preset);
      setIntelligenceVerbosity((tuning.pending ?? tuning.active).responseVerbosity);
      setIntelligenceStatus("Pending tuning discarded.");
    } catch {
      setIntelligenceStatus("Discard pending tuning failed.");
    }
  }

  async function runOpsSecurityScan() {
    try {
      const result = await runSecurityScan();
      setSecurityScanResult(result);
      await refreshSecurityEvents();
      await refreshAlertFeed();
      setSecurityStatus(
        `Scan complete: processes=${result.scannedProcessCount}, newAlerts=${result.newAlerts}.`,
      );
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: { action: "security_scan" },
      });
      setSyncDepth(loadSyncQueue().length);
      setSecurityStatus("Security scan queued for sync.");
    }
  }

  async function runOpsSecurityRecoveryAction(
    eventId: string,
    action: "dismiss" | "deny_app" | "kill_process",
    target?: string,
  ) {
    const confirm = action === "kill_process";
    if (confirm) {
      const allowed = window.confirm(`Kill process "${target || "unknown"}"?`);
      if (!allowed) {
        return;
      }
    }
    try {
      const result = await runSecurityRecovery({
        eventId,
        action,
        target,
        confirm,
      });
      if (result.accepted) {
        setSecurityStatus(`Recovery action applied: ${action}.`);
      } else {
        setSecurityStatus(`Recovery action failed: ${result.reason}`);
      }
      await refreshSecurityEvents();
      if (action === "deny_app") {
        const updatedPermissions = await listPermissionGrants();
        setPermissions(updatedPermissions);
      }
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: { action: "security_recover", eventId, recoveryAction: action, target, confirm },
      });
      setSyncDepth(loadSyncQueue().length);
      setSecurityStatus("Recovery action queued for sync.");
    }
  }

  async function runOpsAlertAction(
    alertId: string,
    action: "dismiss" | "create_recovery_task" | "export_report",
  ) {
    try {
      const response = await runAlertAction({ alertId, action });
      if (response.accepted) {
        if (action === "create_recovery_task") {
          setAlertStatus(`Recovery task created: ${response.createdTaskId ?? "unknown"}`);
        } else if (action === "export_report") {
          setAlertStatus(`Alert report exported: ${response.reportPath ?? "unknown"}`);
        } else {
          setAlertStatus("Alert dismissed.");
        }
        await refreshAlertFeed();
        if (action === "create_recovery_task") {
          const hub = await fetchHubSnapshot();
          setSnapshot(hub);
        }
      } else {
        setAlertStatus(`Alert action failed: ${response.reason}`);
      }
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: { action: "alert_action", alertId, alertAction: action },
      });
      setSyncDepth(loadSyncQueue().length);
      setAlertStatus("Alert action queued for sync.");
    }
  }

  async function runOpsAutomationChain() {
    const name = opsChainName.trim();
    const scrapeUrl = opsScrapeUrl.trim();
    const taskTitle = opsChainTaskTitle.trim();
    const noteTitle = opsChainNoteTitle.trim();
    if (!name || !scrapeUrl || !taskTitle || !noteTitle) {
      setOpsStatus("Automation chain requires name, URL, task title, and note title.");
      return;
    }
    try {
      const response = await runAutomationChain({
        name,
        continueOnFailure: false,
        steps: [
          { kind: "web_scrape", url: scrapeUrl, storeAsNote: true },
          { kind: "security_scan" },
          { kind: "create_task", title: taskTitle },
          {
            kind: "create_note",
            title: noteTitle,
            text: `Chain ${name} finished. Source URL: ${scrapeUrl}`,
          },
        ],
      });
      setOpsChainResult(response);
      if (response.accepted) {
        setOpsStatus(`Automation chain completed (${response.completedSteps}/${response.totalSteps} steps).`);
      } else {
        setOpsStatus(
          `Automation chain failed at step ${response.failedStepIndex ?? "?"}: ${response.recoverySummary ?? response.reason}`,
        );
      }
      if (response.steps.some((step) => step.kind === "security_scan")) {
        await refreshSecurityEvents();
        await refreshAlertFeed();
      }
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: { action: "automation_chain", name, scrapeUrl, taskTitle, noteTitle },
      });
      setSyncDepth(loadSyncQueue().length);
      setOpsStatus("Automation chain queued for sync.");
    }
  }

  const perceptionAverageConfidence = useMemo(() => {
    if (!perceptionResult || perceptionResult.blocks.length === 0) {
      return 0;
    }
    const total = perceptionResult.blocks.reduce((sum, block) => sum + block.confidence, 0);
    return total / perceptionResult.blocks.length;
  }, [perceptionResult]);

  const perceptionCoveragePercent = useMemo(() => {
    if (!perceptionResult?.imageWidth || !perceptionResult.imageHeight || perceptionResult.blocks.length === 0) {
      return 0;
    }
    const imageArea = perceptionResult.imageWidth * perceptionResult.imageHeight;
    if (imageArea <= 0) {
      return 0;
    }
    const blockArea = perceptionResult.blocks.reduce(
      (sum, block) => sum + Math.max(1, block.width) * Math.max(1, block.height),
      0,
    );
    return Math.min(100, (blockArea / imageArea) * 100);
  }, [perceptionResult]);

  const selectedPerceptionSnapshot = useMemo(
    () => perceptionSnapshots.find((item) => item.id === perceptionSelectedSnapshotId) ?? null,
    [perceptionSnapshots, perceptionSelectedSnapshotId],
  );

  return (
    <div className="frame">
      <header className="topbar">
        <div className="brand">MINDI</div>
        <div className={`badge state-${topStatus}`}>{topStatus}</div>
        <div className="meta">
          profile: {snapshot.status.currentProfile} | queued: {syncDepth}
        </div>
      </header>

      <nav className="tabs">
        {TAB_ORDER.map((item) => (
          <button
            type="button"
            key={item}
            className={item === tab ? "tab active" : "tab"}
            onClick={() => setTab(item)}
          >
            {formatTab(item)}
          </button>
        ))}
      </nav>

      {tab === "memory" ? (
        <section className="hub">
          <div className="card">
            <h3>Create Memory Note</h3>
            <div className="stack">
              <input
                value={memoryTitle}
                onChange={(e) => setMemoryTitle(e.target.value)}
                placeholder="Note title"
              />
              <textarea
                value={memoryContent}
                onChange={(e) => setMemoryContent(e.target.value)}
                placeholder="Note content"
                rows={6}
              />
              <button type="button" onClick={() => void addMemoryNote()}>
                Save Note
              </button>
            </div>
            <p className="assistant-reply">{memoryStatus}</p>
          </div>

          <div className="card">
            <h3>Search Memory</h3>
            <div className="stack">
              <input
                value={memoryQuery}
                onChange={(e) => setMemoryQuery(e.target.value)}
                placeholder="Search notes by title/content"
              />
              <button type="button" onClick={() => void runMemorySearch()}>
                Search
              </button>
            </div>
            <ul>
              {memoryNotes.slice(0, 10).map((note) => (
                <li key={note.id}>
                  <strong>{note.title}</strong>: {note.content.slice(0, 80)}
                </li>
              ))}
              {memoryNotes.length === 0 && <li>No notes yet.</li>}
            </ul>
          </div>

          <div className="card">
            <h3>Document Ingestion</h3>
            <div className="stack">
              <input
                value={documentImportPath}
                onChange={(e) => setDocumentImportPath(e.target.value)}
                placeholder="Document path to import"
              />
              <button type="button" onClick={() => void runDocumentImport()}>
                Import Document
              </button>
              <input
                value={ocrImportPath}
                onChange={(e) => setOcrImportPath(e.target.value)}
                placeholder="Image/PDF path for OCR import"
              />
              <button type="button" onClick={() => void runOcrImport()}>
                OCR Import
              </button>
              <input
                value={documentQuery}
                onChange={(e) => setDocumentQuery(e.target.value)}
                placeholder="Search imported documents"
              />
              <button type="button" onClick={() => void runDocumentSearch()}>
                Search Documents
              </button>
              <button type="button" onClick={() => void runAutoIndexScanNow()}>
                Run Auto-Index Scan
              </button>
            </div>
            <p className="assistant-reply">
              auto-index:{" "}
              {autoIndexStatus
                ? `running=${String(autoIndexStatus.running)} indexedTotal=${autoIndexStatus.indexedTotal}`
                : "status unavailable"}
            </p>
            <ul>
              {documentChunks.slice(0, 6).map((chunk) => (
                <li key={chunk.id}>
                  <strong>{chunk.title}</strong> ({chunk.score.toFixed(1)}): {chunk.text.slice(0, 90)}
                </li>
              ))}
              {documentChunks.length === 0 && <li>No document chunks yet.</li>}
            </ul>
          </div>
        </section>
      ) : tab === "control" ? (
        <section className="hub">
          <div className="card">
            <h3>File Organize</h3>
            <div className="stack">
              <label>
                Source folder
                <input value={sourceDir} onChange={(e) => setSourceDir(e.target.value)} />
              </label>
              <label>
                Target folder
                <input value={targetDir} onChange={(e) => setTargetDir(e.target.value)} />
              </label>
              <div className="row left">
                <button type="button" onClick={() => void runOrganize("preview")}>
                  Preview
                </button>
                <button type="button" onClick={() => void runOrganize("apply")}>
                  Apply
                </button>
              </div>
            </div>
            <p className="assistant-reply">
              {organizeResult
                ? `${organizeResult.reason} | accepted=${String(organizeResult.accepted)} | moved=${organizeResult.movedCount}`
                : "No organize run yet."}
            </p>
            <ul>
              {organizeResult?.items.slice(0, 6).map((item) => (
                <li key={`${item.sourcePath}-${item.targetPath}`}>
                  {item.fileName} {"->"} {item.category}
                </li>
              ))}
            </ul>
          </div>

          <div className="card">
            <h3>App Control</h3>
            <div className="stack">
              <input
                value={appId}
                onChange={(e) => setAppId(e.target.value)}
                placeholder="App id (example: notepad.exe)"
              />
              <div className="row left">
                <button type="button" onClick={() => void runAppAction("open")}>
                  Open
                </button>
                <button type="button" onClick={() => void runAppAction("focus")}>
                  Focus
                </button>
                <button type="button" onClick={() => void runAppAction("close")}>
                  Close
                </button>
              </div>
              <label>
                <input
                  type="checkbox"
                  checked={closeConfirm}
                  onChange={(e) => setCloseConfirm(e.target.checked)}
                />
                Confirm close action
              </label>
            </div>
            <p className="assistant-reply">{appResult}</p>
            <h4>Allowed Apps</h4>
            <ul>
              {allowedApps.slice(0, 8).map((app) => (
                <li key={app}>{app}</li>
              ))}
            </ul>
          </div>

          <div className="card">
            <h3>Folder + App Allowlist</h3>
            <div className="stack">
              <input
                value={newAllowFolder}
                onChange={(e) => setNewAllowFolder(e.target.value)}
                placeholder="Path to allow"
              />
              <button type="button" onClick={() => void addFolderAllowGrant()}>
                Add folder allow
              </button>
              <input
                value={newAllowApp}
                onChange={(e) => setNewAllowApp(e.target.value)}
                placeholder="App to allow (example: calc.exe)"
              />
              <button type="button" onClick={() => void addAppAllowGrant()}>
                Add app allow
              </button>
              <input
                value={newAllowDomain}
                onChange={(e) => setNewAllowDomain(e.target.value)}
                placeholder="Domain to allow (example.com or *.example.com)"
              />
              <button type="button" onClick={() => void addDomainAllowGrant()}>
                Add domain allow
              </button>
            </div>
            <ul>
              {permissions.slice(0, 8).map((grant) => (
                <li key={grant.id}>
                  [{grant.decision}] {grant.scope}: {grant.subject}
                </li>
              ))}
            </ul>
          </div>

          <div className="card">
            <h3>Safety Notes</h3>
            <p>Only allowlisted folders can be organized.</p>
            <p>Risky actions remain blocked by policy gate.</p>
            <p>All control runs append audit logs.</p>
          </div>
        </section>
      ) : tab === "vision" ? (
        <section className="hub">
          <div className="card">
            <h3>Screen Perception</h3>
            <div className="stack">
              <button type="button" onClick={() => void runCaptureAndAnalyzeScreen()} disabled={perceptionBusy}>
                {perceptionBusy ? "Capturing..." : "Capture Screen + Analyze"}
              </button>
              <label>
                <input
                  type="checkbox"
                  checked={perceptionIncludeOcr}
                  onChange={(event) => setPerceptionIncludeOcr(event.target.checked)}
                />
                Include OCR text extraction
              </label>
              <p>
                screen permission:{" "}
                {perceptionPermission
                  ? `${perceptionPermission.screenDecision} (${String(perceptionPermission.screenAllowed)})`
                  : "unknown"}
              </p>
              <p>
                camera permission:{" "}
                {perceptionPermission
                  ? `${perceptionPermission.cameraDecision} (${String(perceptionPermission.cameraAllowed)})`
                  : "unknown"}
              </p>
              <button
                type="button"
                onClick={() => void addPerceptionActionAllowGrant(PERCEPTION_SCREEN_SUBJECT)}
              >
                Allow Screen Perception
              </button>
              <button
                type="button"
                onClick={() => void addPerceptionActionAllowGrant(PERCEPTION_CAMERA_SUBJECT)}
              >
                Allow Camera Perception
              </button>
            </div>
            <p className="assistant-reply">{perceptionStatus}</p>
            {perceptionCapturePreview ? (
              <img
                src={perceptionCapturePreview}
                alt="Latest screen capture preview"
                style={{ width: "100%", borderRadius: 8, border: "1px solid #333" }}
              />
            ) : null}
          </div>
          <div className="card">
            <h3>Perception Result</h3>
            <p>
              {perceptionResult
                ? `accepted=${String(perceptionResult.accepted)} reason=${perceptionResult.reason}`
                : "No result yet."}
            </p>
            {perceptionResult ? (
              <div className="metric-grid">
                <p>snapshot: {perceptionResult.snapshotId ?? "n/a"}</p>
                <p>
                  image: {perceptionResult.imageWidth ?? 0} x {perceptionResult.imageHeight ?? 0}
                </p>
                <p>blocks: {perceptionResult.blocks.length}</p>
                <p>textLength: {perceptionResult.textLength}</p>
                <p>avg confidence: {perceptionAverageConfidence.toFixed(2)}</p>
                <p>coverage: {perceptionCoveragePercent.toFixed(1)}%</p>
                <p>ocr mode: {perceptionResult.ocrMode ?? "n/a"}</p>
                <p>ocr error: {perceptionResult.ocrError ?? "none"}</p>
              </div>
            ) : null}
            {perceptionResult?.text ? (
              <p className="assistant-reply">{perceptionResult.text.slice(0, 400)}</p>
            ) : null}
            <ul>
              {(perceptionResult?.blocks ?? []).slice(0, 10).map((block, index) => (
                <li key={`${block.x}-${block.y}-${index}`}>
                  [{block.kind}] x={block.x} y={block.y} w={block.width} h={block.height} c=
                  {block.confidence.toFixed(2)}
                  <div className="confidence-track">
                    <div
                      className="confidence-fill"
                      style={{ width: `${Math.max(2, Math.min(100, block.confidence * 100))}%` }}
                    />
                  </div>
                </li>
              ))}
              {perceptionResult && perceptionResult.blocks.length === 0 ? <li>No blocks detected.</li> : null}
            </ul>
          </div>
          <div className="card">
            <h3>Snapshot Memory</h3>
            <div className="stack">
              <div className="chatbox">
                <input
                  value={perceptionSnapshotQuery}
                  onChange={(event) => setPerceptionSnapshotQuery(event.target.value)}
                  placeholder="Search OCR text/reason/path"
                />
                <button type="button" onClick={() => void runPerceptionSnapshotSearch()}>
                  Search
                </button>
              </div>
              <button type="button" onClick={() => void refreshPerceptionSnapshots()}>
                Refresh
              </button>
            </div>
            <p className="assistant-reply">{perceptionSnapshotStatus}</p>
            <ul className="snapshot-list">
              {perceptionSnapshots.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className={item.id === perceptionSelectedSnapshotId ? "tab active" : "tab"}
                    onClick={() => setPerceptionSelectedSnapshotId(item.id)}
                  >
                    {formatIsoTime(item.createdAt)} | b={item.blockCount} | t={item.textLength}
                  </button>
                </li>
              ))}
              {perceptionSnapshots.length === 0 ? <li>No snapshots yet.</li> : null}
            </ul>
            {selectedPerceptionSnapshot ? (
              <div className="metric-grid">
                <p>id: {selectedPerceptionSnapshot.id}</p>
                <p>time: {formatIsoTime(selectedPerceptionSnapshot.createdAt)}</p>
                <p>reason: {selectedPerceptionSnapshot.reason}</p>
                <p>ocr mode: {selectedPerceptionSnapshot.ocrMode ?? "n/a"}</p>
                <p>source: {selectedPerceptionSnapshot.sourcePath ?? "inline_capture"}</p>
                <p>
                  image: {selectedPerceptionSnapshot.imageWidth ?? 0} x {selectedPerceptionSnapshot.imageHeight ?? 0}
                </p>
                <p>blocks: {selectedPerceptionSnapshot.blockCount}</p>
                <p>textLength: {selectedPerceptionSnapshot.textLength}</p>
              </div>
            ) : null}
            {selectedPerceptionSnapshot?.text ? (
              <p className="assistant-reply">{selectedPerceptionSnapshot.text.slice(0, 300)}</p>
            ) : null}
          </div>
        </section>
      ) : tab === "ops" ? (
        <section className="hub">
          <div className="card">
            <h3>Web Scrape Job</h3>
            <div className="stack">
              <input
                value={opsScrapeUrl}
                onChange={(event) => setOpsScrapeUrl(event.target.value)}
                placeholder="https://example.com/article"
              />
              <label>
                <input
                  type="checkbox"
                  checked={opsScrapeStoreAsNote}
                  onChange={(event) => setOpsScrapeStoreAsNote(event.target.checked)}
                />
                Store scraped text as memory note
              </label>
              <button type="button" onClick={() => void runOpsWebScrape()}>
                Run Web Scrape
              </button>
            </div>
            <p className="assistant-reply">{opsStatus}</p>
          </div>

          <div className="card">
            <h3>Automation Chain</h3>
            <div className="stack">
              <input
                value={opsChainName}
                onChange={(event) => setOpsChainName(event.target.value)}
                placeholder="Chain name"
              />
              <input
                value={opsChainTaskTitle}
                onChange={(event) => setOpsChainTaskTitle(event.target.value)}
                placeholder="Task title for chain"
              />
              <input
                value={opsChainNoteTitle}
                onChange={(event) => setOpsChainNoteTitle(event.target.value)}
                placeholder="Note title for chain"
              />
              <button type="button" onClick={() => void runOpsAutomationChain()}>
                Run Automation Chain
              </button>
            </div>
            <p>
              {opsChainResult
                ? `accepted=${String(opsChainResult.accepted)} completed=${opsChainResult.completedSteps}/${opsChainResult.totalSteps}`
                : "No chain result yet."}
            </p>
            {opsChainResult?.recoverySummary ? (
              <p className="assistant-reply">{opsChainResult.recoverySummary}</p>
            ) : null}
            <ul>
              {(opsChainResult?.steps ?? []).map((step) => (
                <li key={`${step.kind}-${step.index}`}>
                  #{step.index + 1} {step.kind}: {step.reason}
                  {step.detail ? ` | ${step.detail}` : ""}
                  {step.recoveryHint ? ` | recovery: ${step.recoveryHint}` : ""}
                </li>
              ))}
              {opsChainResult && opsChainResult.steps.length === 0 ? <li>No steps returned.</li> : null}
            </ul>
          </div>

          <div className="card">
            <h3>Scrape Result</h3>
            <p>
              {opsScrapeResult
                ? `accepted=${String(opsScrapeResult.accepted)} reason=${opsScrapeResult.reason}`
                : "No result yet."}
            </p>
            {opsScrapeResult?.title ? <p>title: {opsScrapeResult.title}</p> : null}
            {opsScrapeResult?.text ? (
              <p className="assistant-reply">{opsScrapeResult.text.slice(0, 500)}</p>
            ) : null}
            <ul>
              {(opsScrapeResult?.links ?? []).slice(0, 8).map((link) => (
                <li key={link}>{link}</li>
              ))}
              {opsScrapeResult && opsScrapeResult.links.length === 0 ? <li>No links extracted.</li> : null}
            </ul>
          </div>

          <div className="card">
            <h3>Security Monitoring</h3>
            <div className="stack">
              <button type="button" onClick={() => void runOpsSecurityScan()}>
                Run Security Scan
              </button>
              <button type="button" onClick={() => void refreshSecurityEvents()}>
                Refresh Events
              </button>
            </div>
            <p className="assistant-reply">{securityStatus}</p>
            {securityScanResult ? (
              <p>
                last scan: processes={securityScanResult.scannedProcessCount}, newAlerts=
                {securityScanResult.newAlerts}
              </p>
            ) : null}
            <ul>
              {securityEvents.slice(0, 8).map((event) => (
                <li key={event.id}>
                  [{event.severity}] {event.title}
                  {event.processName ? ` (${event.processName})` : ""}
                  <div className="row left">
                    <button
                      type="button"
                      onClick={() => void runOpsSecurityRecoveryAction(event.id, "dismiss")}
                    >
                      Dismiss
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        void runOpsSecurityRecoveryAction(event.id, "deny_app", event.processName)
                      }
                    >
                      Deny App
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        void runOpsSecurityRecoveryAction(event.id, "kill_process", event.processName)
                      }
                    >
                      Kill Process
                    </button>
                  </div>
                </li>
              ))}
              {securityEvents.length === 0 ? <li>No open security events.</li> : null}
            </ul>
          </div>

          <div className="card">
            <h3>Alert Recovery Flow</h3>
            <div className="stack">
              <button type="button" onClick={() => void refreshAlertFeed()}>
                Refresh Alert Feed
              </button>
            </div>
            <p className="assistant-reply">{alertStatus}</p>
            {alertFeed ? (
              <p>
                total={alertFeed.total} critical={alertFeed.critical} warning={alertFeed.warning} info={alertFeed.info}
              </p>
            ) : null}
            <ul>
              {(alertFeed?.items ?? []).slice(0, 8).map((alert) => (
                <li key={alert.id}>
                  [{alert.severity}] {alert.title}
                  <div className="row left">
                    <button type="button" onClick={() => void runOpsAlertAction(alert.id, "dismiss")}>
                      Dismiss
                    </button>
                    <button
                      type="button"
                      onClick={() => void runOpsAlertAction(alert.id, "create_recovery_task")}
                    >
                      Recovery Task
                    </button>
                    <button type="button" onClick={() => void runOpsAlertAction(alert.id, "export_report")}>
                      Export Report
                    </button>
                  </div>
                </li>
              ))}
              {alertFeed && alertFeed.items.length === 0 ? <li>No alerts in feed.</li> : null}
            </ul>
          </div>

          <div className="card">
            <h3>Offline Privacy</h3>
            <p>
              redaction:{" "}
              {privacyStatus
                ? `${String(privacyStatus.redactionEnabled)} (patterns=${privacyStatus.sensitivePatternCount})`
                : "unknown"}
            </p>
            <p>safe storage default: {privacyStatus ? String(privacyStatus.safeStorageDefault) : "unknown"}</p>
            <label>
              <input
                type="checkbox"
                checked={privacyUiEnabled}
                onChange={(event) => setPrivacyUiEnabled(event.target.checked)}
              />
              Enable sensitive-text redaction for stored perception/scrape artifacts
            </label>
            <div className="row left">
              <button type="button" onClick={() => void runPrivacyUpdate(privacyUiEnabled)}>
                Apply Privacy Setting
              </button>
              <button type="button" onClick={() => void refreshPrivacyStatus()}>
                Refresh Privacy Status
              </button>
            </div>
          </div>

          <div className="card">
            <h3>Intelligence Loop</h3>
            <p>
              style: {intelligenceStyle ? intelligenceStyle.languageMode : "unknown"} | slang=
              {intelligenceStyle ? String(intelligenceStyle.slangEnabled) : "unknown"}
            </p>
            <p>
              active tuning:{" "}
              {intelligenceTuning
                ? `${intelligenceTuning.active.preset}/${intelligenceTuning.active.responseVerbosity}`
                : "unknown"}
            </p>
            <p>
              pending tuning:{" "}
              {intelligenceTuning?.pending
                ? `${intelligenceTuning.pending.preset}/${intelligenceTuning.pending.responseVerbosity}`
                : "none"}
            </p>
            <div className="stack">
              <label>
                Language mode
                <select
                  value={intelligenceLanguageMode}
                  onChange={(event) =>
                    setIntelligenceLanguageMode(event.target.value as "english" | "taglish" | "tagalog")
                  }
                >
                  <option value="english">English</option>
                  <option value="taglish">Taglish</option>
                  <option value="tagalog">Tagalog</option>
                </select>
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={intelligenceSlangEnabled}
                  onChange={(event) => setIntelligenceSlangEnabled(event.target.checked)}
                />
                Enable slang style layer
              </label>
              <input
                value={intelligenceNewSlang}
                onChange={(event) => setIntelligenceNewSlang(event.target.value)}
                placeholder="Add slang term"
              />
              <label>
                Learning source note
                <select
                  value={intelligenceLearningNoteId}
                  onChange={(event) => setIntelligenceLearningNoteId(event.target.value)}
                >
                  <option value="">Select a recent note</option>
                  {memoryNotes.slice(0, 12).map((note) => (
                    <option key={note.id} value={note.id}>
                      {note.title}
                    </option>
                  ))}
                </select>
              </label>
              <div className="row left">
                <button type="button" onClick={() => void runIntelligenceLearningSourceUpdate(true)}>
                  Approve Source
                </button>
                <button type="button" onClick={() => void runIntelligenceLearningSourceUpdate(false)}>
                  Remove Source
                </button>
                <button type="button" onClick={() => void runIntelligenceLearningNow()}>
                  Run Learning
                </button>
                <button
                  type="button"
                  onClick={() => void runIntelligenceLearningEvalNow()}
                  disabled={!intelligenceLearning || intelligenceLearning.candidates.length === 0}
                >
                  Eval Learned Slang
                </button>
                <button
                  type="button"
                  onClick={() => void runIntelligenceLearningApplyNow()}
                  disabled={
                    !intelligenceLearning ||
                    intelligenceLearning.candidates.length === 0 ||
                    !intelligenceLearning.canApplyCandidates
                  }
                >
                  Apply Learned Slang
                </button>
              </div>
              <p>
                learning sources: {intelligenceLearning ? intelligenceLearning.approvedSources.length : 0} | candidates:{" "}
                {intelligenceLearning ? intelligenceLearning.candidates.length : 0}
              </p>
              <p>
                learning gate:{" "}
                {intelligenceLearning
                  ? `${String(intelligenceLearning.canApplyCandidates)} (min=${intelligenceLearning.minApplyScore.toFixed(2)})`
                  : "unknown"}
              </p>
              <ul>
                {(intelligenceLearning?.approvedSources ?? []).slice(0, 4).map((item) => (
                  <li key={item.noteId}>
                    approved: {item.title} ({formatIsoTime(item.approvedAt)})
                  </li>
                ))}
                {intelligenceLearning && intelligenceLearning.approvedSources.length === 0 ? (
                  <li>No approved learning sources.</li>
                ) : null}
              </ul>
              <ul>
                {(intelligenceLearning?.candidates ?? []).slice(0, 6).map((item) => (
                  <li key={`${item.sourceNoteId}:${item.term}`}>
                    {item.term} from {item.sourceTitle}: {item.evidence}
                  </li>
                ))}
                {intelligenceLearning && intelligenceLearning.candidates.length === 0 ? (
                  <li>No learning candidates. Use approved style notes with explicit markers like `slang: astig`.</li>
                ) : null}
              </ul>
              <label>
                Preset
                <select
                  value={intelligencePreset}
                  onChange={(event) =>
                    setIntelligencePreset(event.target.value as "safe" | "balanced" | "companion")
                  }
                >
                  <option value="safe">Safe</option>
                  <option value="balanced">Balanced</option>
                  <option value="companion">Companion</option>
                </select>
              </label>
              <label>
                Response verbosity
                <select
                  value={intelligenceVerbosity}
                  onChange={(event) =>
                    setIntelligenceVerbosity(event.target.value as "brief" | "balanced" | "detailed")
                  }
                >
                  <option value="brief">Brief</option>
                  <option value="balanced">Balanced</option>
                  <option value="detailed">Detailed</option>
                </select>
              </label>
              <input
                value={intelligenceRiskyTerm}
                onChange={(event) => setIntelligenceRiskyTerm(event.target.value)}
                placeholder="Add custom risky term"
              />
              <div className="row left">
                <button type="button" onClick={() => void runIntelligenceStyleUpdate()}>
                  Apply Style
                </button>
                <button type="button" onClick={() => void runIntelligenceEvalNow()}>
                  Run Eval
                </button>
                <button type="button" onClick={() => void refreshIntelligenceState()}>
                  Refresh
                </button>
              </div>
              <div className="row left">
                <button type="button" onClick={() => void runIntelligenceTuningStage()}>
                  Stage Candidate
                </button>
                <button type="button" onClick={() => void runIntelligencePendingEval()}>
                  Eval Pending
                </button>
                <button
                  type="button"
                  onClick={() => void runIntelligenceTuningApplyNow()}
                  disabled={!intelligenceTuning?.canApplyPending}
                >
                  Apply Pending
                </button>
                <button type="button" onClick={() => void runIntelligenceTuningDiscardNow()}>
                  Discard Pending
                </button>
              </div>
            </div>
            <p className="assistant-reply">{intelligenceStatus}</p>
            <p>
              gate:{" "}
              {intelligenceTuning
                ? `${String(intelligenceTuning.canApplyPending)} (min=${intelligenceTuning.minApplyScore.toFixed(2)})`
                : "unknown"}
            </p>
            {intelligenceEvalResult ? (
              <p>
                latest {intelligenceEvalResult.scope} score={intelligenceEvalResult.score.toFixed(2)} gate=
                {String(intelligenceEvalResult.gatePassed)} (
                {intelligenceEvalResult.passedCases}/{intelligenceEvalResult.totalCases})
              </p>
            ) : null}
            <ul>
              {(intelligenceEvalResult?.cases ?? []).map((item) => (
                <li key={item.id}>
                  {item.id}: {item.accepted ? "pass" : "fail"} ({item.observed})
                </li>
              ))}
              {intelligenceEvalResult && intelligenceEvalResult.cases.length === 0 ? (
                <li>No eval case results.</li>
              ) : null}
            </ul>
            <h4>Eval History</h4>
            <ul>
              {intelligenceEvalHistory.map((item) => (
                <li key={item.runId}>
                  {formatIsoTime(item.createdAt)} | {item.scope} | score={item.score.toFixed(2)} | gate=
                  {String(item.gatePassed)} | passed={item.passedCases}/{item.totalCases}
                </li>
              ))}
              {intelligenceEvalHistory.length === 0 ? <li>No eval history yet.</li> : null}
            </ul>
          </div>

          <div className="card">
            <h3>Domain Policy</h3>
            <div className="stack">
              <input
                value={newAllowDomain}
                onChange={(event) => setNewAllowDomain(event.target.value)}
                placeholder="example.com or *.example.com"
              />
              <button type="button" onClick={() => void addDomainAllowGrant()}>
                Add domain allow
              </button>
            </div>
            <ul>
              {permissions
                .filter((item) => item.scope === "domain")
                .slice(0, 8)
                .map((grant) => (
                  <li key={grant.id}>
                    [{grant.decision}] {grant.subject}
                  </li>
                ))}
              {permissions.filter((item) => item.scope === "domain").length === 0 ? (
                <li>No domain grants yet.</li>
              ) : null}
            </ul>
          </div>
        </section>
      ) : (
        <section className="hub">
          <div className="card">
            <h3>Urgent Tasks & Alerts</h3>
            <div className="row">
              <button type="button" onClick={addTask}>
                + Task
              </button>
            </div>
            <ul>
              {snapshot.tasks.slice(0, 4).map((task) => (
                <li key={task.id}>
                  [{task.status}] {task.title}
                  {task.dueAt ? ` (due ${task.dueAt})` : ""}
                  {task.recurrence ? ` [${task.recurrence}]` : ""}
                  {" "}
                  <button
                    type="button"
                    onClick={() => void runTaskStatusChange(task.id, "in_progress")}
                    disabled={task.status === "in_progress"}
                  >
                    Start
                  </button>
                  {" "}
                  <button
                    type="button"
                    onClick={() => void runTaskStatusChange(task.id, "done")}
                    disabled={task.status === "done"}
                  >
                    Done
                  </button>
                  {" "}
                  <button
                    type="button"
                    onClick={() => void runTaskStatusChange(task.id, "todo")}
                    disabled={task.status === "todo"}
                  >
                    Reopen
                  </button>
                  {" "}
                  <button type="button" onClick={() => void runTaskEdit(task.id)}>
                    Edit
                  </button>
                  {" "}
                  <button type="button" onClick={() => void runTaskDelete(task.id)}>
                    Delete
                  </button>
                </li>
              ))}
              {snapshot.tasks.length === 0 && <li>No tasks yet.</li>}
            </ul>
            <ul>
              {snapshot.alerts.slice(0, 3).map((alert) => (
                <li key={alert.id}>
                  [{alert.severity}] {alert.title}
                </li>
              ))}
              {snapshot.alerts.length === 0 && <li>No active alerts.</li>}
            </ul>
          </div>

          <div className="card">
            <h3>Conversation</h3>
            <div className="chatbox">
              <input
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                placeholder="Ask MINDI..."
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    void handleSend();
                  }
                }}
              />
              <button type="button" onClick={() => void handleSend()}>
                Send
              </button>
            </div>
            <p className="assistant-reply">
              {assistant?.reply ?? "No assistant response yet. Send a prompt to start."}
            </p>
          </div>

          <div className="card">
            <h3>Status & Quick Controls</h3>
            <p>Agent: {snapshot.status.agentVersion}</p>
            <p>Listening: {snapshot.status.listening ? "on" : "off"}</p>
            <p>
              scheduler:{" "}
              {schedulerStatus
                ? `running=${String(schedulerStatus.running)} alerts=${schedulerStatus.alertsTotal}`
                : "unavailable"}
            </p>
            <button type="button" onClick={() => void runTaskSchedulerScanNow()}>
              Run Scheduler Scan
            </button>
            <button type="button" onClick={() => void runCalendarExport()}>
              Export Calendar (.ics)
            </button>
            <button type="button" onClick={() => void runCalendarImport()}>
              Import Calendar (.ics)
            </button>
            <div className="toggles">
              {toggles.map((toggle) => (
                <label key={toggle.id}>
                  <input
                    type="checkbox"
                    checked={toggle.enabled}
                    onChange={(event) =>
                      setToggles((current) =>
                        current.map((item) =>
                          item.id === toggle.id
                            ? { ...item, enabled: event.target.checked }
                            : item,
                        ),
                      )
                    }
                  />
                  {toggle.label}
                </label>
              ))}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

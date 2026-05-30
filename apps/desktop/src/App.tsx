import { useEffect, useMemo, useState } from "react";
import {
  QUICK_TOGGLES,
  TAB_ORDER,
  type AutoIndexStatus,
  type AssistantResponse,
  type FileOrganizeResponse,
  type HubSnapshot,
  type MemoryDocumentChunk,
  type MemoryNote,
  type MindiTabId,
  type PerceptionPermissionStatus,
  type PerceptionAnalyzeResponse,
  type PermissionGrant,
  type QuickToggle,
  type SchedulerStatus,
  type SyncQueueItem,
} from "@mindi/shared";
import {
  addPermissionGrant,
  appControlAction,
  createMemoryNote,
  createTask,
  deleteTask,
  updateTaskStatus,
  updateTask,
  fetchAllowedApps,
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
  runSchedulerScanNow,
  exportCalendar,
  importCalendar,
  analyzeScreenPerception,
  getPerceptionPermissionStatus,
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
  const [memoryStatus, setMemoryStatus] = useState("No memory action yet.");
  const [perceptionStatus, setPerceptionStatus] = useState("No perception run yet.");
  const [perceptionResult, setPerceptionResult] = useState<PerceptionAnalyzeResponse | null>(null);
  const [perceptionPermission, setPerceptionPermission] = useState<PerceptionPermissionStatus | null>(null);
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
    ])
      .then(([hub, grantList, appAllowlist, notes, indexStatus, scheduleStatus, perceptionPermissionStatus]) => {
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
      })
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
          `Perception ok: ${response.blocks.length} blocks, textLength=${response.textLength}, snapshot=${response.snapshotId ?? "n/a"}.`,
        );
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
            {perceptionResult?.text ? (
              <p className="assistant-reply">{perceptionResult.text.slice(0, 400)}</p>
            ) : null}
            <ul>
              {(perceptionResult?.blocks ?? []).slice(0, 10).map((block, index) => (
                <li key={`${block.x}-${block.y}-${index}`}>
                  [{block.kind}] x={block.x} y={block.y} w={block.width} h={block.height} c=
                  {block.confidence.toFixed(2)}
                </li>
              ))}
              {perceptionResult && perceptionResult.blocks.length === 0 ? <li>No blocks detected.</li> : null}
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

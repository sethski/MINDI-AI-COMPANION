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
  type PermissionGrant,
  type QuickToggle,
  type SchedulerStatus,
} from "@mindi/shared";
import {
  addPermissionGrant,
  appControlAction,
  createMemoryNote,
  createTask,
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
} from "./lib/agent-api";
import { enqueueSyncItem, loadSyncQueue, loadToggleState, saveToggleState } from "./lib/local-state";

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
    ])
      .then(([hub, grantList, appAllowlist, notes, indexStatus, scheduleStatus]) => {
        if (!active) {
          return;
        }
        setSnapshot(hub);
        setPermissions(grantList);
        setAllowedApps(appAllowlist.apps);
        setMemoryNotes(notes);
        setAutoIndexStatus(indexStatus);
        setSchedulerStatus(scheduleStatus);
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

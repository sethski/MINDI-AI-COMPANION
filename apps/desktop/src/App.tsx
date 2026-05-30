import { useEffect, useMemo, useState } from "react";
import {
  QUICK_TOGGLES,
  TAB_ORDER,
  type AssistantResponse,
  type FileOrganizeResponse,
  type HubSnapshot,
  type MindiTabId,
  type PermissionGrant,
  type QuickToggle,
} from "@mindi/shared";
import {
  addPermissionGrant,
  appControlAction,
  createTask,
  fetchAllowedApps,
  fetchHubSnapshot,
  fileOrganize,
  listPermissionGrants,
  sendAssistantRequest,
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
    Promise.all([fetchHubSnapshot(), listPermissionGrants(), fetchAllowedApps()])
      .then(([hub, grantList, appAllowlist]) => {
        if (!active) {
          return;
        }
        setSnapshot(hub);
        setPermissions(grantList);
        setAllowedApps(appAllowlist.apps);
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
    try {
      const newTask = await createTask({ title });
      setSnapshot((current) => ({ ...current, tasks: [newTask, ...current.tasks] }));
    } catch {
      enqueueSyncItem({
        type: "action",
        payload: { action: "create_task", title },
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

      {tab === "control" ? (
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

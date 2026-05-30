import { useEffect, useMemo, useState } from "react";
import {
  QUICK_TOGGLES,
  TAB_ORDER,
  type AssistantResponse,
  type HubSnapshot,
  type MindiTabId,
  type QuickToggle,
} from "@mindi/shared";
import { createTask, fetchHubSnapshot, sendAssistantRequest } from "./lib/agent-api";
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
  const [toggles, setToggles] = useState<QuickToggle[]>(() =>
    loadToggleState(QUICK_TOGGLES),
  );
  const [message, setMessage] = useState("");
  const [assistant, setAssistant] = useState<AssistantResponse | null>(null);
  const [syncDepth, setSyncDepth] = useState(loadSyncQueue().length);
  const [networkOnline, setNetworkOnline] = useState<boolean>(navigator.onLine);

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
    fetchHubSnapshot()
      .then((data) => {
        if (active) {
          setSnapshot(data);
        }
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
    </div>
  );
}

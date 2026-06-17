import { invoke } from "@tauri-apps/api/core";

import { emit } from "@tauri-apps/api/event";

import { isTauriRuntime } from "./tauri-window";



const AGENT_LOG_URL = "http://127.0.0.1:8765/ops/debug/session-log";

const INGEST_URL = "http://127.0.0.1:7917/ingest/3c5996e2-44eb-48a9-8416-3cd194097893";

const SESSION_ID = "ddb680";



export function debugSessionLog(payload: Record<string, unknown>): void {
  if (!import.meta.env.DEV) return;

  const line = JSON.stringify({

    sessionId: SESSION_ID,

    timestamp: Date.now(),

    ...payload,

  });

  fetch(AGENT_LOG_URL, {

    method: "POST",

    headers: { "Content-Type": "application/json" },

    body: line,

  }).catch(() => {});

  if (typeof navigator.sendBeacon === "function") {

    navigator.sendBeacon(INGEST_URL, new Blob([line], { type: "application/json" }));

  } else {

    fetch(INGEST_URL, {

      method: "POST",

      headers: { "Content-Type": "application/json", "X-Debug-Session-Id": SESSION_ID },

      body: line,

    }).catch(() => {});

  }

  try {

    const key = "debug-ddb680";

    const prior = localStorage.getItem(key) ?? "";

    const next = `${prior}${line}\n`.slice(-32000);

    localStorage.setItem(key, next);

  } catch {

    // Ignore storage failures in restricted contexts.

  }

  if (isTauriRuntime()) {
    void invoke("debug_session_log", { line }).catch((error) => {
      fetch(AGENT_LOG_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: SESSION_ID,
          timestamp: Date.now(),
          runId: "post-remote-fix",
          hypothesisId: "IPC",
          location: "debug-session-log.ts:invoke",
          message: "tauri invoke debug_session_log failed",
          data: { error: error instanceof Error ? error.message : String(error) },
        }),
      }).catch(() => {});
    });

    void emit("debug-log", line).catch((error) => {
      fetch(AGENT_LOG_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: SESSION_ID,
          timestamp: Date.now(),
          runId: "post-remote-fix",
          hypothesisId: "IPC",
          location: "debug-session-log.ts:emit",
          message: "tauri emit debug-log failed",
          data: { error: error instanceof Error ? error.message : String(error) },
        }),
      }).catch(() => {});
    });
  }

}



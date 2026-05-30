import { invoke } from "@tauri-apps/api/core";
import { emit } from "@tauri-apps/api/event";
import { isTauriRuntime } from "./tauri-window";

const INGEST_URL = "http://127.0.0.1:7917/ingest/3c5996e2-44eb-48a9-8416-3cd194097893";
const SESSION_ID = "4cfb89";

export function debugSessionLog(payload: Record<string, unknown>): void {
  const line = JSON.stringify({
    sessionId: SESSION_ID,
    timestamp: Date.now(),
    ...payload,
  });
  fetch(INGEST_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Debug-Session-Id": SESSION_ID },
    body: line,
  }).catch(() => {});
  if (isTauriRuntime()) {
    void invoke("debug_session_log", { line }).catch(() => {});
    void emit("debug-log", line).catch(() => {});
  }
}

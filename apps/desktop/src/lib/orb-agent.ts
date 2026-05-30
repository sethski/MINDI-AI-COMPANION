import { QUICK_TOGGLES } from "@mindi/shared";
import { setOrbListeningState } from "./agent-api";
import { loadToggleState } from "./local-state";

export function isMicEnabled(): boolean {
  const toggles = loadToggleState(QUICK_TOGGLES);
  return toggles.find((item) => item.id === "mic")?.enabled ?? true;
}

export function listenMicToggle(onChange: (enabled: boolean) => void): () => void {
  const handler = () => onChange(isMicEnabled());
  window.addEventListener("storage", handler);
  window.addEventListener("mindi-toggles-changed", handler);
  return () => {
    window.removeEventListener("storage", handler);
    window.removeEventListener("mindi-toggles-changed", handler);
  };
}

export async function setOrbListening(listening: boolean): Promise<void> {
  try {
    await setOrbListeningState(listening);
  } catch {
    // Agent may be offline; orb still works locally.
  }
}

export async function checkAgentOnline(): Promise<boolean> {
  try {
    const response = await fetch("http://127.0.0.1:8765/health", { method: "GET" });
    return response.ok;
  } catch {
    return false;
  }
}

interface AiStatusPayload {
  features?: {
    asr?: {
      ready?: boolean;
    };
  };
}

export async function checkAsrReady(): Promise<boolean> {
  try {
    const response = await fetch("http://127.0.0.1:8765/ops/ai/status", { method: "GET" });
    if (!response.ok) {
      return false;
    }
    const payload = (await response.json()) as AiStatusPayload;
    return payload.features?.asr?.ready === true;
  } catch {
    return false;
  }
}

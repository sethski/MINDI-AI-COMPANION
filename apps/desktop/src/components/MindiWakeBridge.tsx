import { emit, listen } from "@tauri-apps/api/event";
import { useEffect, useState } from "react";
import { useWakeWord } from "../hooks/useWakeWord";
import { updateAiRuntimeConfig } from "../lib/agent-api";
import { debugSessionLog } from "../lib/debug-session-log";
import { checkAsrReady, isMicEnabled, listenMicToggle } from "../lib/orb-agent";
import { isTauriRuntime, orbFocus } from "../lib/tauri-window";

export function MindiWakeBridge() {
  const [micEnabled, setMicEnabled] = useState(isMicEnabled);
  const [orbBusy, setOrbBusy] = useState(false);
  const [micPrimed, setMicPrimed] = useState(false);

  useEffect(() => {
    if (!isTauriRuntime()) {
      return;
    }

    // #region agent log
    debugSessionLog({
      runId: "post-fix",
      hypothesisId: "G",
      location: "MindiWakeBridge.tsx:mount",
      message: "wake bridge mounted in main window",
      data: { micEnabled: isMicEnabled() },
    });
    // #endregion

    void fetch("http://127.0.0.1:8765/ops/ai/status")
      .then((response) => (response.ok ? response.json() : null))
      .then((status) => updateAiRuntimeConfig(status?.config ?? {}))
      .then(() => {
      void checkAsrReady().then((ready) => {
        // #region agent log
        debugSessionLog({
          runId: "post-fix",
          hypothesisId: "H",
          location: "MindiWakeBridge.tsx:runtime-sync",
          message: "ai runtime config synced from desktop",
          data: { asrReady: ready },
        });
        // #endregion
      });
    });

    const cleanups: Array<() => void> = [];
    void listen("orb-session-busy", () => {
      setOrbBusy(true);
    }).then((unlisten) => cleanups.push(unlisten));
    void listen("orb-session-idle", () => {
      setOrbBusy(false);
    }).then((unlisten) => cleanups.push(unlisten));
    cleanups.push(listenMicToggle(setMicEnabled));

    const primeMic = (source: "gesture" | "startup") => {
      void navigator.mediaDevices
        .getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
        .then((stream) => {
          for (const track of stream.getTracks()) {
            track.stop();
          }
          setMicPrimed(true);
          // #region agent log
          debugSessionLog({
            runId: "post-fix",
            hypothesisId: "C",
            location: "MindiWakeBridge.tsx:primeMic",
            message: "mic primed for wake listening",
            data: { source },
          });
          // #endregion
        })
        .catch((error) => {
          // #region agent log
          debugSessionLog({
            runId: "post-fix",
            hypothesisId: "C",
            location: "MindiWakeBridge.tsx:primeMic:catch",
            message: "mic prime failed",
            data: {
              source,
              error: error instanceof Error ? error.message : String(error),
            },
          });
          // #endregion
        });
    };

    primeMic("startup");
    const onFirstPointerDown = () => primeMic("gesture");
    window.addEventListener("pointerdown", onFirstPointerDown, { once: true });

    return () => {
      window.removeEventListener("pointerdown", onFirstPointerDown);
      for (const cleanup of cleanups) {
        cleanup();
      }
    };
  }, []);

  // Wake word runs on the orb window in Tauri (single mic), so it stays disabled here.
  useWakeWord({
    enabled: false,
    active: orbBusy,
    onWake: () => {
      void emit("orb-wake");
      void orbFocus();
    },
  });

  return null;
}

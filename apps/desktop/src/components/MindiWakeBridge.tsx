import { emit, listen } from "@tauri-apps/api/event";
import { useEffect, useState } from "react";
import { useWakeWord } from "../hooks/useWakeWord";
import { getAiRuntimeStatus, updateAiRuntimeConfig } from "../lib/agent-api";
import { debugSessionLog } from "../lib/debug-session-log";
import { checkAsrReady, isMicEnabled, listenMicToggle } from "../lib/orb-agent";
import {
  listenScreenHelpHotkey,
  pollProactiveNudges,
  reportOrbIdle,
} from "../lib/proactive-bridge";
import { isTauriRuntime, orbFocus } from "../lib/tauri-window";

export function MindiWakeBridge() {
  const [micEnabled, setMicEnabled] = useState(isMicEnabled);
  const [orbBusy, setOrbBusy] = useState(false);

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

    void getAiRuntimeStatus()
      .then((status) => updateAiRuntimeConfig(status.config ?? {}))
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
      void reportOrbIdle(false);
    }).then((unlisten) => cleanups.push(unlisten));
    void listen("orb-session-idle", () => {
      setOrbBusy(false);
      void reportOrbIdle(true);
    }).then((unlisten) => cleanups.push(unlisten));
    cleanups.push(listenMicToggle(setMicEnabled));

    void reportOrbIdle(true);
    const nudgeInterval = window.setInterval(() => {
      void pollProactiveNudges();
    }, 25000);
    cleanups.push(() => window.clearInterval(nudgeInterval));

    void listenScreenHelpHotkey((reply) => {
      void emit("mindi-screen-help-result", { reply });
    }).then((unlisten) => cleanups.push(unlisten));

    return () => {
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

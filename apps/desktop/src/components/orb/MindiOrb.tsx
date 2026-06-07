import { emit } from "@tauri-apps/api/event";
import { AnimatePresence } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { OrbActive, OrbIdle } from "./OrbIdle";
import { OrbPulse, OrbWaveform } from "./OrbWaveform";
import { useVoiceSession } from "../../hooks/useVoiceSession";
import { useWakeWord } from "../../hooks/useWakeWord";
import {
  checkAgentOnline,
  isMicEnabled,
  listenMicToggle,
  setOrbListening,
} from "../../lib/orb-agent";
import {
  isActivePhase,
  ORB_ACTIVE_SIZE,
  ORB_IDLE_SIZE,
  ORB_MENU_SIZE,
  OrbPhase,
  pickGreeting,
  prefersReducedMotion,
} from "../../lib/orb-state";
import {
  isTauriRuntime,
  listenOrbWake,
  orbClampPosition,
  orbSetSize,
  orbStartDrag,
  quitApp,
  showMainWindow,
  trackOrbDragEnd,
} from "../../lib/tauri-window";

const IDLE_CAPTION = "Say \u201cHey MINDI\u201d or tap the mic. Click to open MINDI.";

const LISTEN_TIMEOUT_MS = 32000;
const WAKE_ANIMATION_MS = 420;

export function MindiOrb() {
  const [phase, setPhase] = useState<OrbPhase>("idle");
  const [caption, setCaption] = useState(IDLE_CAPTION);
  const [offline, setOffline] = useState(false);
  const [micEnabled, setMicEnabled] = useState(isMicEnabled);
  const [idleMenuOpen, setIdleMenuOpen] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0.35);
  const reducedMotion = prefersReducedMotion();
  const phaseRef = useRef<OrbPhase>("idle");
  const idleMenuOpenRef = useRef(false);
  const listenTimeoutRef = useRef<number | null>(null);
  const sessionLockRef = useRef(false);
  const finishListeningRef = useRef<() => Promise<void>>(async () => undefined);
  const beginSessionRef = useRef<() => Promise<void>>(async () => undefined);
  const resetToIdleRef = useRef<() => Promise<void>>(async () => undefined);
  const stopListeningRef = useRef<() => Promise<string>>(async () => "");

  const voice = useVoiceSession({
    onLevel: (level) => setAudioLevel(level),
    onUtteranceComplete: () => {
      if (phaseRef.current !== "listening" || sessionLockRef.current) {
        return;
      }
      if (listenTimeoutRef.current) {
        window.clearTimeout(listenTimeoutRef.current);
        listenTimeoutRef.current = null;
      }
      void finishListeningRef.current();
    },
  });

  const syncWindowSize = useCallback(async (nextPhase: OrbPhase, menuOpen = false) => {
    const size = isActivePhase(nextPhase)
      ? ORB_ACTIVE_SIZE
      : menuOpen
        ? ORB_MENU_SIZE
        : ORB_IDLE_SIZE;
    await orbSetSize(size.width, size.height);
    await orbClampPosition();
  }, []);

  const resetToIdle = useCallback(async () => {
    if (listenTimeoutRef.current) {
      window.clearTimeout(listenTimeoutRef.current);
      listenTimeoutRef.current = null;
    }
    sessionLockRef.current = false;
    phaseRef.current = "idle";
    setIdleMenuOpen(false);
    setPhase("idle");
    setCaption(IDLE_CAPTION);
    await setOrbListening(false);
    await syncWindowSize("idle");
  }, [syncWindowSize]);

  const finishListening = useCallback(async () => {
    if (sessionLockRef.current) {
      return;
    }
    sessionLockRef.current = true;
    setPhase("thinking");
    phaseRef.current = "thinking";
    setCaption("Working on that...");

    let transcript: string;
    try {
      transcript = await voice.stopListening();
    } catch (error) {
      const message =
        error instanceof Error && error.message === "mic_disabled"
          ? "Microphone is off. Enable Mic in the dashboard."
          : "Could not capture audio. Check the mic and try again.";
      setPhase("error");
      phaseRef.current = "error";
      setCaption(message);
      await setOrbListening(false);
      window.setTimeout(() => {
        void resetToIdle();
      }, 3200);
      return;
    }

    // askAssistant resolves with the assistant reply OR a real failure reason
    // string (e.g. model_path_missing, llama_cpp_binary_missing). Surface that
    // text in the caption instead of a generic error.
    const result = await voice.askAssistant(transcript);
    setPhase(result.degraded ? "error" : "speaking");
    phaseRef.current = result.degraded ? "error" : "speaking";
    setCaption(result.reply);

    try {
      await voice.speak(result.reply);
    } catch {
      // TTS is best-effort; the reply (or error) stays on the caption.
    }

    if (result.degraded) {
      await setOrbListening(false);
      // Keep the real error readable longer before returning to idle.
      window.setTimeout(() => {
        void resetToIdle();
      }, 5200);
      return;
    }
    await resetToIdle();
  }, [resetToIdle, voice]);

  useEffect(() => {
    finishListeningRef.current = finishListening;
  }, [finishListening]);

  const beginSession = useCallback(async () => {
    if (phaseRef.current !== "idle" || sessionLockRef.current) {
      return;
    }

    if (!micEnabled) {
      setPhase("error");
      phaseRef.current = "error";
      setCaption("Microphone is off. Enable Mic in the dashboard.");
      window.setTimeout(() => {
        void resetToIdle();
      }, 2400);
      return;
    }

    sessionLockRef.current = false;
    setPhase("waking");
    phaseRef.current = "waking";
    setCaption("...");
    if (isTauriRuntime()) {
      void emit("orb-session-busy");
    }
    await setOrbListening(true);
    await syncWindowSize("waking");

    await new Promise((resolve) => window.setTimeout(resolve, reducedMotion ? 0 : WAKE_ANIMATION_MS));

    const greeting = pickGreeting();
    setPhase("greeting");
    phaseRef.current = "greeting";
    setCaption(greeting);

    try {
      await voice.speak(greeting);
    } catch {
      // Continue even if TTS is unavailable.
    }

    setPhase("listening");
    phaseRef.current = "listening";
    setCaption("Listening...");

    try {
      await voice.startListening();
    } catch {
      setPhase("error");
      phaseRef.current = "error";
      setCaption("Microphone access denied.");
      await setOrbListening(false);
      window.setTimeout(() => {
        void resetToIdle();
      }, 2400);
      return;
    }

    listenTimeoutRef.current = window.setTimeout(() => {
      void finishListening();
    }, LISTEN_TIMEOUT_MS);
  }, [finishListening, micEnabled, reducedMotion, resetToIdle, syncWindowSize, voice]);

  useEffect(() => {
    beginSessionRef.current = beginSession;
  }, [beginSession]);

  useEffect(() => {
    resetToIdleRef.current = resetToIdle;
  }, [resetToIdle]);

  useEffect(() => {
    stopListeningRef.current = voice.stopListening;
  }, [voice.stopListening]);

  useEffect(() => {
    idleMenuOpenRef.current = idleMenuOpen;
  }, [idleMenuOpen]);

  useWakeWord({
    enabled: micEnabled && phase === "idle",
    active: phase !== "idle",
    onWake: () => {
      void beginSession();
    },
  });

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  useEffect(() => {
    void syncWindowSize("idle", idleMenuOpenRef.current);
    void checkAgentOnline().then((online) => setOffline(!online));

    const interval = window.setInterval(() => {
      void checkAgentOnline().then((online) => setOffline(!online));
    }, 15000);

    const cleanups: Array<() => void> = [];
    void listenOrbWake(() => {
      if (isActivePhase(phaseRef.current)) {
        void stopListeningRef.current().finally(() => {
          void resetToIdleRef.current();
        });
        return;
      }
      void beginSessionRef.current();
    }).then((unlisten) => cleanups.push(unlisten));
    void trackOrbDragEnd(() => undefined).then((unlisten) => cleanups.push(unlisten));
    cleanups.push(listenMicToggle(setMicEnabled));

    return () => {
      window.clearInterval(interval);
      for (const cleanup of cleanups) {
        cleanup();
      }
      if (listenTimeoutRef.current) {
        window.clearTimeout(listenTimeoutRef.current);
      }
    };
  }, [syncWindowSize]);

  const handleDragStart = () => {
    setIdleMenuOpen(false);
    void orbStartDrag();
  };

  const handleIdleMenuOpenChange = useCallback((open: boolean) => {
    setIdleMenuOpen(open);
    void syncWindowSize("idle", open);
  }, [syncWindowSize]);

  const handleCancel = () => {
    void voice.stopListening().finally(() => {
      void resetToIdle();
    });
  };

  const active = isActivePhase(phase);

  return (
    <div
      className={`orb-shell ${active ? "orb-shell--active" : "orb-shell--idle"} ${
        idleMenuOpen ? "orb-shell--menu" : ""
      }`}
    >
      <AnimatePresence mode="wait">
        {!active ? (
          <OrbIdle
            key="idle"
            offline={offline}
            micDisabled={!micEnabled}
            onActivate={() => {
              void beginSession();
            }}
            onOpenDashboard={() => {
              handleIdleMenuOpenChange(false);
              void showMainWindow().catch(() => {
                setCaption("Could not open dashboard. Restart MINDI.");
                setPhase("error");
                phaseRef.current = "error";
                window.setTimeout(() => {
                  void resetToIdle();
                }, 2400);
              });
            }}
            onDragStart={handleDragStart}
            onMenuOpenChange={handleIdleMenuOpenChange}
            onQuit={() => {
              void quitApp();
            }}
          />
        ) : (
          <OrbActive
            key="active"
            phase={phase as Exclude<OrbPhase, "idle">}
            caption={caption}
            offline={offline}
            reducedMotion={reducedMotion}
            onDragStart={handleDragStart}
            onCancel={handleCancel}
            pulse={<OrbPulse show={phase === "waking" && !reducedMotion} />}
            waveform={
              <OrbWaveform
                active={(phase === "listening" || phase === "speaking") && !reducedMotion}
                level={audioLevel}
              />
            }
          />
        )}
      </AnimatePresence>
    </div>
  );
}

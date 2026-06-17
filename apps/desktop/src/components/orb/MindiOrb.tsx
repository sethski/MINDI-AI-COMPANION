import { emit } from "@tauri-apps/api/event";
import { listen } from "@tauri-apps/api/event";
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
import { importDocument, importOcrDocument } from "../../lib/agent-api";
import { classifyDroppedPath } from "../../lib/input-bridge";
import type { ProactiveNudge } from "@mindi/shared";
import {
  isActivePhase,
  ORB_ACTIVE_SIZE,
  ORB_IDLE_SIZE,
  ORB_MENU_SIZE,
  OrbPhase,
  prefersReducedMotion,
  stripWakeWord,
} from "../../lib/orb-state";
import { playWakeEarcon } from "../../lib/orb-wakeword";
import { debugSessionLog } from "../../lib/debug-session-log";
import {
  isTauriRuntime,
  listenOrbWake,
  orbClampPosition,
  orbFocus,
  orbSetSize,
  orbStartDrag,
  quitApp,
  showMainWindow,
  trackOrbDragEnd,
} from "../../lib/tauri-window";

const IDLE_CAPTION = "";

const WAKE_ANIMATION_MS = 420;
const MIN_COMMAND_CHARS = 3;

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
  const sessionLockRef = useRef(false);
  const beginSessionRef = useRef<(wakeTranscript?: string) => Promise<void>>(async () => undefined);
  const resetToIdleRef = useRef<() => Promise<void>>(async () => undefined);

  const utteranceCompleteRef = useRef<(() => void) | null>(null);

  const voice = useVoiceSession({
    onLevel: (level) => setAudioLevel(level),
    onPartialTranscript: (text) => {
      if (phaseRef.current === "waking") {
        setCaption(text);
      }
    },
    onUtteranceComplete: () => {
      utteranceCompleteRef.current?.();
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
    sessionLockRef.current = false;
    phaseRef.current = "idle";
    idleMenuOpenRef.current = false;
    setIdleMenuOpen(false);
    setPhase("idle");
    setCaption(IDLE_CAPTION);
    await setOrbListening(false);
    await syncWindowSize("idle");
  }, [syncWindowSize]);

  const speakAlways = useCallback(
    async (text: string) => {
      try {
        await voice.speak(text);
      } catch (error) {
        // #region agent log
        debugSessionLog({
          runId: "post-fix",
          hypothesisId: "H5",
          location: "MindiOrb.tsx:speakAlways",
          message: "Piper TTS failed",
          data: { error: error instanceof Error ? error.message : String(error), textPreview: text.slice(0, 80) },
        });
        // #endregion
        setPhase("error");
        phaseRef.current = "error";
        setCaption("Voice unavailable. Check Piper TTS in settings.");
        await setOrbListening(false);
        window.setTimeout(() => {
          void resetToIdle();
        }, 3200);
        throw error;
      }
    },
    [resetToIdle, voice],
  );

  const runVoiceTurn = useCallback(
    async (options: { command?: string; wakeInvoke?: boolean; continuous?: boolean }) => {
      if (sessionLockRef.current) {
        return;
      }
      sessionLockRef.current = true;
      setPhase("thinking");
      phaseRef.current = "thinking";
      setCaption("");

      let spokeLive = false;
      const result = options.wakeInvoke
        ? await voice.askAssistant("", {
            wakeInvoke: true,
            onToken: (_token, fullText) => {
              setCaption(fullText);
            },
            onSentence: async (sentence) => {
              spokeLive = true;
              setPhase("speaking");
              phaseRef.current = "speaking";
              await speakAlways(sentence);
            },
          })
        : await voice.askAssistant(options.command ?? "", {
            onToken: (_token, fullText) => {
              setCaption(fullText);
            },
            onSentence: async (sentence) => {
              spokeLive = true;
              setPhase("speaking");
              phaseRef.current = "speaking";
              await speakAlways(sentence);
            },
          });

      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "H8",
        location: "MindiOrb.tsx:runVoiceTurn",
        message: "assistant turn complete",
        data: {
          wakeInvoke: Boolean(options.wakeInvoke),
          commandPreview: (options.command ?? "").slice(0, 80),
          degraded: result.degraded,
        },
      });
      // #endregion

      setPhase("speaking");
      phaseRef.current = "speaking";
      setCaption(result.degraded ? result.reply : "");

      try {
        if (!spokeLive) {
          await speakAlways(result.reply);
        }
      } catch {
        return;
      }

      if (result.degraded) {
        setPhase("error");
        phaseRef.current = "error";
        setCaption(result.reply);
        await setOrbListening(false);
        window.setTimeout(() => {
          void resetToIdle();
        }, 1200);
        return;
      }

      if (options.continuous ?? true) {
        sessionLockRef.current = false;
        setPhase("waking");
        phaseRef.current = "waking";
        setCaption("Listening...");
        try {
          await voice.startListening();
          await new Promise<void>((resolve) => {
            utteranceCompleteRef.current = () => {
              utteranceCompleteRef.current = null;
              resolve();
            };
          });
          const heard = await voice.stopListening();
          if (heard.trim().length >= MIN_COMMAND_CHARS) {
            await runVoiceTurn({ command: heard, continuous: true });
            return;
          }
        } catch {
          // Fall through to idle reset.
        }
      }
      await resetToIdle();
    },
    [resetToIdle, speakAlways, voice],
  );

  const handleOrbFileDrop = useCallback(
    async (path: string) => {
      if (sessionLockRef.current || isActivePhase(phaseRef.current)) {
        return;
      }
      const kind = classifyDroppedPath(path);
      const fileName = path.split(/[/\\]/).pop() ?? "file";
      if (kind === "unsupported") {
        setPhase("error");
        phaseRef.current = "error";
        setCaption("Unsupported file type for the orb.");
        window.setTimeout(() => {
          void resetToIdle();
        }, 2400);
        return;
      }

      sessionLockRef.current = true;
      setPhase("thinking");
      phaseRef.current = "thinking";
      setCaption(`Reading ${fileName}...`);
      if (isTauriRuntime()) {
        void emit("orb-session-busy");
      }
      await syncWindowSize("thinking");

      try {
        const result =
          kind === "image" ? await importOcrDocument(path) : await importDocument(path);
        if (!result.accepted) {
          setPhase("error");
          phaseRef.current = "error";
          setCaption(`Could not read ${fileName}.`);
          window.setTimeout(() => {
            void resetToIdle();
          }, 2800);
          return;
        }
        sessionLockRef.current = false;
        await runVoiceTurn({
          command: `Summarize the file "${fileName}" I just added to memory.`,
          continuous: false,
        });
      } catch (error) {
        setPhase("error");
        phaseRef.current = "error";
        setCaption(error instanceof Error ? error.message : "File drop failed.");
        window.setTimeout(() => {
          void resetToIdle();
        }, 2800);
      }
    },
    [resetToIdle, runVoiceTurn, syncWindowSize],
  );

  const beginSession = useCallback(
    async (wakeTranscript = "") => {
      const command = stripWakeWord(wakeTranscript);
      const proactive = command.length < MIN_COMMAND_CHARS;
      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "H3,H4,H7,H8",
        location: "MindiOrb.tsx:beginSession",
        message: "voice session starting",
        data: {
          phase: phaseRef.current,
          sessionLock: sessionLockRef.current,
          micEnabled,
          menuOpen: idleMenuOpenRef.current,
          commandPreview: command.slice(0, 80),
          proactive,
        },
      });
      // #endregion
      if (idleMenuOpenRef.current || phaseRef.current !== "idle" || sessionLockRef.current) {
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
      setCaption("");
      playWakeEarcon();
      if (isTauriRuntime()) {
        void emit("orb-session-busy");
      }
      await setOrbListening(true);
      await syncWindowSize("waking");

      await new Promise((resolve) => window.setTimeout(resolve, reducedMotion ? 0 : WAKE_ANIMATION_MS));

      if (proactive) {
        await runVoiceTurn({ wakeInvoke: true });
        return;
      }
      await runVoiceTurn({ command });
    },
    [micEnabled, reducedMotion, resetToIdle, runVoiceTurn, syncWindowSize],
  );

  useEffect(() => {
    beginSessionRef.current = beginSession;
  }, [beginSession]);

  useEffect(() => {
    resetToIdleRef.current = resetToIdle;
  }, [resetToIdle]);

  const wake = useWakeWord({
    enabled: micEnabled && phase === "idle" && !idleMenuOpen,
    active: phase !== "idle" || idleMenuOpen,
    onWake: (transcript) => {
      if (idleMenuOpenRef.current) {
        return;
      }
      void beginSession(transcript);
    },
  });

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  useEffect(() => {
    // #region agent log
    debugSessionLog({
      runId: "post-fix",
      hypothesisId: "P",
      location: "MindiOrb.tsx:mount",
      message: "orb mounted",
      data: {
        wakeFixVersion: "asr-wake-v11",
        isTauri: isTauriRuntime(),
        href: window.location.href,
        micEnabled: isMicEnabled(),
        hasMediaDevices: Boolean(navigator.mediaDevices),
        hasGetUserMedia: typeof navigator.mediaDevices?.getUserMedia === "function",
        hasSpeechRecognition: Boolean(
          (window as Window & { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition,
        ),
      },
    });
    // #endregion
    void syncWindowSize("idle", idleMenuOpenRef.current);
    void checkAgentOnline().then((online) => setOffline(!online));

    const interval = window.setInterval(() => {
      void checkAgentOnline().then((online) => setOffline(!online));
    }, 15000);

    const cleanups: Array<() => void> = [];
    void listenOrbWake(() => {
      if (isActivePhase(phaseRef.current)) {
        void resetToIdleRef.current();
        return;
      }
      void beginSessionRef.current("");
    }).then((unlisten) => cleanups.push(unlisten));
    void trackOrbDragEnd(() => undefined).then((unlisten) => cleanups.push(unlisten));
    cleanups.push(listenMicToggle(setMicEnabled));
    if (isTauriRuntime()) {
      void (async () => {
        const { getCurrentWebviewWindow } = await import("@tauri-apps/api/webviewWindow");
        const unlisten = await getCurrentWebviewWindow().onDragDropEvent((event) => {
          if (event.payload.type !== "drop") {
            return;
          }
          for (const path of event.payload.paths) {
            void handleOrbFileDrop(path);
          }
        });
        cleanups.push(unlisten);
      })();
      void listen<ProactiveNudge>("mindi-nudge", (event) => {
        if (phaseRef.current !== "idle") {
          return;
        }
        setCaption(event.payload.message);
        window.setTimeout(() => {
          if (phaseRef.current === "idle") {
            setCaption(IDLE_CAPTION);
          }
        }, 9000);
      }).then((unlisten) => cleanups.push(unlisten));
    }

    return () => {
      window.clearInterval(interval);
      for (const cleanup of cleanups) {
        cleanup();
      }
    };
  }, [handleOrbFileDrop, syncWindowSize]);

  const handleIdleMenuOpenChange = useCallback((open: boolean) => {
    // #region agent log
    debugSessionLog({
      runId: "post-fix",
      hypothesisId: "H2,H7",
      location: "MindiOrb.tsx:menuOpenChange",
      message: "idle menu open state changed",
      data: { open, targetSize: open ? ORB_MENU_SIZE : ORB_IDLE_SIZE },
    });
    // #endregion
    idleMenuOpenRef.current = open;
    setIdleMenuOpen(open);
    if (isTauriRuntime()) {
      void emit(open ? "orb-session-busy" : "orb-session-idle");
      if (open) {
        void orbFocus();
      }
    }
    void syncWindowSize("idle", open).catch((error) => {
      // #region agent log
      debugSessionLog({
        runId: "pre-fix",
        hypothesisId: "H2",
        location: "MindiOrb.tsx:syncWindowSize:error",
        message: "orb window resize failed",
        data: { open, error: error instanceof Error ? error.message : String(error) },
      });
      // #endregion
    });
  }, [syncWindowSize]);

  const handleDragStart = () => {
    handleIdleMenuOpenChange(false);
    void orbStartDrag();
  };

  const handleCancel = () => {
    void resetToIdle();
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
            wakeListening={wake.wakeListening && !offline}
            micBlocked={wake.micBlocked}
            nudgeCaption={caption || undefined}
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
                active={(phase === "thinking" || phase === "speaking") && !reducedMotion}
                level={audioLevel}
              />
            }
          />
        )}
      </AnimatePresence>
    </div>
  );
}

import { useCallback, useEffect, useRef, type MutableRefObject } from "react";
import { transcribeMicBlob } from "../lib/agent-api";
import { debugSessionLog } from "../lib/debug-session-log";
import { checkAsrReady, isMicEnabled } from "../lib/orb-agent";
import { isTauriRuntime, orbSaveAudioTemp } from "../lib/tauri-window";

interface SpeechRecognitionAlternativeLike {
  transcript: string;
}

interface SpeechRecognitionResultLike {
  isFinal: boolean;
  length: number;
  [index: number]: SpeechRecognitionAlternativeLike;
}

interface SpeechRecognitionEventLike {
  results: ArrayLike<SpeechRecognitionResultLike>;
}

interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

const WAKE_PATTERN = /\b(?:hey[,]?\s+)?mindi\b/i;
const ASR_WAKE_SLICE_MS = 2000;
const MIN_WAKE_BLOB_BYTES = 1500;

function getSpeechRecognition(): SpeechRecognitionCtor | null {
  const scope = window as Window & {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null;
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = reader.result;
      if (typeof result === "string") {
        resolve(result);
      } else {
        reject(new Error("invalid_blob_encoding"));
      }
    };
    reader.onerror = () => reject(reader.error ?? new Error("blob_read_failed"));
    reader.readAsDataURL(blob);
  });
}

function transcriptMatchesWake(text: string): boolean {
  return WAKE_PATTERN.test(text);
}

function triggerWake(
  lastWakeRef: MutableRefObject<number>,
  onWakeRef: MutableRefObject<() => void>,
  source: string,
  transcript: string,
): void {
  const now = Date.now();
  if (now - lastWakeRef.current < 2500) {
    return;
  }
  lastWakeRef.current = now;
  // #region agent log
  debugSessionLog({
    runId: "post-fix",
    hypothesisId: "D,E",
    location: "useWakeWord.ts:triggerWake",
    message: "wake word matched, invoking onWake",
    data: { source, transcriptTail: transcript.slice(-40) },
  });
  // #endregion
  onWakeRef.current();
}

export interface UseWakeWordOptions {
  enabled: boolean;
  active: boolean;
  onWake: () => void;
}

export function useWakeWord({ enabled, active, onWake }: UseWakeWordOptions) {
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const primeStreamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const scanInFlightRef = useRef(false);
  const asrReadyRef = useRef(false);
  const lastWakeRef = useRef(0);
  const onWakeRef = useRef(onWake);
  const enabledRef = useRef(enabled);
  const activeRef = useRef(active);
  const startRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    onWakeRef.current = onWake;
  }, [onWake]);

  useEffect(() => {
    enabledRef.current = enabled;
    activeRef.current = active;
  }, [active, enabled]);

  useEffect(() => {
    const refreshAsrReady = () => {
      void checkAsrReady().then((ready) => {
        const wasReady = asrReadyRef.current;
        asrReadyRef.current = ready;
        if (ready && !wasReady && enabledRef.current && !activeRef.current && isMicEnabled()) {
          startRef.current();
        }
      });
    };
    refreshAsrReady();
    const interval = window.setInterval(refreshAsrReady, 4000);
    return () => window.clearInterval(interval);
  }, []);

  const stopAsrWake = useCallback(() => {
    recorderRef.current = null;
    if (streamRef.current) {
      for (const track of streamRef.current.getTracks()) {
        track.stop();
      }
      streamRef.current = null;
    }
  }, []);

  const stopSpeechWake = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.onend = null;
      recognitionRef.current.abort();
      recognitionRef.current = null;
    }
    if (primeStreamRef.current) {
      for (const track of primeStreamRef.current.getTracks()) {
        track.stop();
      }
      primeStreamRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    stopSpeechWake();
    stopAsrWake();
  }, [stopAsrWake, stopSpeechWake]);

  const scanWakeChunk = useCallback(async (blob: Blob) => {
    if (!enabledRef.current || activeRef.current || scanInFlightRef.current) {
      return;
    }
    if (blob.size < MIN_WAKE_BLOB_BYTES) {
      return;
    }

    scanInFlightRef.current = true;
    try {
      const dataUrl = await blobToBase64(blob);
      const extension = blob.type.includes("webm") ? "webm" : "wav";
      let sourceValue = dataUrl;
      try {
        sourceValue = await orbSaveAudioTemp(dataUrl, extension);
      } catch {
        // Browser-only fallback keeps data URL payload.
      }

      const asr = await transcribeMicBlob(sourceValue);
      const transcript = asr.text?.trim() ?? "";
      const patternMatch = transcriptMatchesWake(transcript);
      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "A,D",
        location: "useWakeWord.ts:asrScan",
        message: "asr wake scan result",
        data: {
          accepted: asr.accepted,
          reason: "reason" in asr ? String(asr.reason) : undefined,
          transcriptLen: transcript.length,
          transcriptTail: transcript.slice(-40),
          patternMatch,
        },
      });
      // #endregion
      if (patternMatch) {
        triggerWake(lastWakeRef, onWakeRef, "asr", transcript);
      }
    } catch (error) {
      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "C",
        location: "useWakeWord.ts:asrScan:error",
        message: "asr wake scan failed",
        data: { error: error instanceof Error ? error.message : String(error) },
      });
      // #endregion
    } finally {
      scanInFlightRef.current = false;
    }
  }, []);

  const startAsrWake = useCallback(async () => {
    if (!enabledRef.current || activeRef.current || !isMicEnabled()) {
      return;
    }

    stopSpeechWake();
    stopAsrWake();

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      streamRef.current = stream;

      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          void scanWakeChunk(event.data);
        }
      };
      recorder.start(ASR_WAKE_SLICE_MS);
      recorderRef.current = recorder;

      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "A",
        location: "useWakeWord.ts:startAsrWake:ok",
        message: "asr wake listening started",
        data: { sliceMs: ASR_WAKE_SLICE_MS },
      });
      // #endregion
    } catch (error) {
      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "C",
        location: "useWakeWord.ts:startAsrWake:catch",
        message: "asr wake getUserMedia failed",
        data: { error: error instanceof Error ? error.message : String(error) },
      });
      // #endregion
      if (enabledRef.current && !activeRef.current && isMicEnabled()) {
        window.setTimeout(() => {
          void startAsrWake();
        }, 2000);
      }
    }
  }, [scanWakeChunk, stopAsrWake]);

  const startSpeechWake = useCallback(() => {
    if (!enabledRef.current || activeRef.current || !isMicEnabled()) {
      return;
    }

    const Recognition = getSpeechRecognition();
    if (!Recognition) {
      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "A",
        location: "useWakeWord.ts:startSpeechWake:no-api",
        message: "speech recognition api unavailable",
        data: {},
      });
      // #endregion
      return;
    }

    if (recognitionRef.current) {
      return;
    }

    const recognition = new Recognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    recognition.onresult = (event) => {
      let transcript = "";
      for (let index = 0; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result?.[0]?.transcript) {
          transcript += result[0].transcript;
        }
      }
      const patternMatch = transcriptMatchesWake(transcript);
      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "D",
        location: "useWakeWord.ts:onresult",
        message: "speech api wake result",
        data: {
          transcriptLen: transcript.length,
          transcriptTail: transcript.slice(-40),
          patternMatch,
        },
      });
      // #endregion
      if (patternMatch) {
        triggerWake(lastWakeRef, onWakeRef, "speech", transcript);
      }
    };
    recognition.onerror = (event) => {
      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "C",
        location: "useWakeWord.ts:onerror",
        message: "speech api wake error",
        data: { error: event.error },
      });
      // #endregion
      stopSpeechWake();
    };
    recognition.onend = () => {
      recognitionRef.current = null;
      if (enabledRef.current && !activeRef.current && isMicEnabled()) {
        window.setTimeout(() => {
          void startSpeechWakePrimed();
        }, 400);
      }
    };

    try {
      recognition.start();
      recognitionRef.current = recognition;
      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "C",
        location: "useWakeWord.ts:startSpeechWake:ok",
        message: "speech api wake listening started",
        data: {},
      });
      // #endregion
    } catch (error) {
      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "C",
        location: "useWakeWord.ts:startSpeechWake:catch",
        message: "speech api wake start failed",
        data: { error: error instanceof Error ? error.message : String(error) },
      });
      // #endregion
      recognitionRef.current = null;
    }
  }, [stopSpeechWake]);

  const startSpeechWakePrimed = useCallback(async () => {
    if (!enabledRef.current || activeRef.current || !isMicEnabled()) {
      return;
    }

    if (!primeStreamRef.current) {
      try {
        primeStreamRef.current = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true },
        });
        // #region agent log
        debugSessionLog({
          runId: "post-fix",
          hypothesisId: "C",
          location: "useWakeWord.ts:primeMic:ok",
          message: "mic primed for speech wake",
          data: {},
        });
        // #endregion
      } catch (error) {
        // #region agent log
        debugSessionLog({
          runId: "post-fix",
          hypothesisId: "C",
          location: "useWakeWord.ts:primeMic:catch",
          message: "mic prime failed for speech wake",
          data: { error: error instanceof Error ? error.message : String(error) },
        });
        // #endregion
        return;
      }
    }

    startSpeechWake();
  }, [startSpeechWake]);

  const start = useCallback(() => {
    if (!enabled || active || !isMicEnabled()) {
      return;
    }

    void checkAsrReady().then((ready) => {
      asrReadyRef.current = ready;
      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "A,B",
        location: "useWakeWord.ts:start:entry",
        message: "wake start() resolved",
        data: {
          enabled: enabledRef.current,
          active: activeRef.current,
          micEnabled: isMicEnabled(),
          isTauri: isTauriRuntime(),
          asrReady: ready,
          hasRecognition: !!getSpeechRecognition(),
        },
      });
      // #endregion

      if (!enabledRef.current || activeRef.current || !isMicEnabled()) {
        return;
      }

      if (isTauriRuntime() && ready) {
        void startAsrWake();
        return;
      }

      if (getSpeechRecognition()) {
        void startSpeechWakePrimed();
        return;
      }

      // #region agent log
      debugSessionLog({
        runId: "pre-fix",
        hypothesisId: "B",
        location: "useWakeWord.ts:start:no-path",
        message: "wake listening could not start",
        data: { isTauri: isTauriRuntime(), asrReady: ready, hasRecognition: false },
      });
      // #endregion
    });
  }, [active, enabled, startAsrWake, startSpeechWakePrimed]);

  useEffect(() => {
    startRef.current = start;
  }, [start]);

  useEffect(() => {
    if (enabled && !active && isMicEnabled()) {
      start();
    } else {
      stop();
    }
    return stop;
  }, [active, enabled, start, stop]);
}

import { useCallback, useEffect, useRef, useState, type MutableRefObject } from "react";
import { convertBlobToWav } from "../lib/orb-audio";
import { transcribeWakeBlob } from "../lib/agent-api";
import { debugSessionLog } from "../lib/debug-session-log";
import { checkAsrReady, isMicEnabled, requestMicStream } from "../lib/orb-agent";
import { OpenWakeWordDetector } from "../lib/orb-wakeword";
import { transcriptMatchesWake } from "../lib/orb-state";
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

function triggerWake(
  lastWakeRef: MutableRefObject<number>,
  onWakeRef: MutableRefObject<(transcript: string) => void>,
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
  onWakeRef.current(transcript);
}

export interface UseWakeWordOptions {
  enabled: boolean;
  active: boolean;
  onWake: (transcript: string) => void;
}

export interface UseWakeWordState {
  wakeListening: boolean;
  micBlocked: boolean;
}

export function useWakeWord({ enabled, active, onWake }: UseWakeWordOptions): UseWakeWordState {
  const [wakeListening, setWakeListening] = useState(false);
  const [micBlocked, setMicBlocked] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const primeStreamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const scanInFlightRef = useRef(false);
  const pendingWakeChunkRef = useRef<Blob | null>(null);
  const asrReadyRef = useRef(false);
  const asrWakeSuppressedRef = useRef(false);
  const dualWakeRef = useRef(false);
  const lastWakeRef = useRef(0);
  const onWakeRef = useRef<(transcript: string) => void>(onWake);
  const enabledRef = useRef(enabled);
  const activeRef = useRef(active);
  const startRef = useRef<() => void>(() => undefined);
  const startSpeechWakePrimedRef = useRef<() => Promise<void>>(async () => undefined);
  const isWakeListeningRef = useRef(false);
  const sharedMicRef = useRef<MediaStream | null>(null);
  const wakeStartInFlightRef = useRef(false);
  const speechRestartTimerRef = useRef<number | null>(null);
  const owwDetectorRef = useRef<OpenWakeWordDetector | null>(null);

  const releaseWakeMic = useCallback(() => {
    if (sharedMicRef.current) {
      for (const track of sharedMicRef.current.getTracks()) {
        track.stop();
      }
      sharedMicRef.current = null;
    }
    streamRef.current = null;
    primeStreamRef.current = null;
  }, []);

  const acquireWakeMic = useCallback(async (): Promise<MediaStream | null> => {
    const streamEnded =
      sharedMicRef.current?.getTracks().every((track) => track.readyState === "ended") ?? false;
    if (!sharedMicRef.current || streamEnded) {
      try {
        sharedMicRef.current = await requestMicStream();
        streamRef.current = sharedMicRef.current;
        primeStreamRef.current = sharedMicRef.current;
        setMicBlocked(false);
        // #region agent log
        debugSessionLog({
          runId: "post-fix",
          hypothesisId: "W",
          location: "useWakeWord.ts:sharedMic:acquired",
          message: "single shared mic stream acquired",
          data: { isTauri: isTauriRuntime(), dualWake: dualWakeRef.current },
        });
        // #endregion
      } catch (error) {
        setMicBlocked(true);
        // #region agent log
        debugSessionLog({
          runId: "post-remote-fix",
          hypothesisId: "W",
          location: "useWakeWord.ts:sharedMic:catch",
          message: "shared mic acquisition failed",
          data: {
            error: error instanceof Error ? error.message : String(error),
            isTauri: isTauriRuntime(),
          },
        });
        // #endregion
        return null;
      }
    }
    return sharedMicRef.current;
  }, []);

  useEffect(() => {
    onWakeRef.current = onWake;
  }, [onWake]);

  useEffect(() => {
    enabledRef.current = enabled;
    activeRef.current = active;
  }, [active, enabled]);

  const stopAsrWake = useCallback((preserveMic = false) => {
    pendingWakeChunkRef.current = null;
    const recorder = recorderRef.current;
    recorderRef.current = null;
    if (recorder && recorder.state !== "inactive") {
      recorder.onstop = null;
      recorder.stop();
    }
    if (streamRef.current && !preserveMic) {
      if (primeStreamRef.current === streamRef.current) {
        primeStreamRef.current = null;
      }
      if (sharedMicRef.current === streamRef.current) {
        sharedMicRef.current = null;
      }
      for (const track of streamRef.current.getTracks()) {
        track.stop();
      }
      streamRef.current = null;
    }
  }, []);

  useEffect(() => {
    const refreshAsrReady = () => {
      void checkAsrReady().then((ready) => {
        const wasReady = asrReadyRef.current;
        asrReadyRef.current = ready;
        if (!ready && wasReady) {
          stopAsrWake();
        }
        if (
          ready &&
          !wasReady &&
          !getSpeechRecognition() &&
          enabledRef.current &&
          !activeRef.current &&
          isMicEnabled() &&
          !isWakeListeningRef.current
        ) {
          startRef.current();
        }
      });
    };
    refreshAsrReady();
    const interval = window.setInterval(refreshAsrReady, 4000);
    return () => window.clearInterval(interval);
  }, [stopAsrWake]);

  const stopSpeechWake = useCallback((preserveMic = false) => {
    if (speechRestartTimerRef.current) {
      window.clearTimeout(speechRestartTimerRef.current);
      speechRestartTimerRef.current = null;
    }
    if (recognitionRef.current) {
      recognitionRef.current.onend = null;
      recognitionRef.current.abort();
      recognitionRef.current = null;
    }
    if (primeStreamRef.current && !preserveMic) {
      if (sharedMicRef.current === primeStreamRef.current) {
        sharedMicRef.current = null;
      }
      for (const track of primeStreamRef.current.getTracks()) {
        track.stop();
      }
      primeStreamRef.current = null;
      streamRef.current = null;
    }
  }, []);

  const stopOpenWakeWord = useCallback(async () => {
    const detector = owwDetectorRef.current;
    owwDetectorRef.current = null;
    if (detector) {
      await detector.stop();
    }
  }, []);

  const startOpenWakeWord = useCallback(async () => {
    if (!enabledRef.current || activeRef.current || !isMicEnabled()) {
      return;
    }
    const stream = await acquireWakeMic();
    if (!stream) {
      return;
    }
    await stopOpenWakeWord();
    const detector = new OpenWakeWordDetector({
      onWake: () => triggerWake(lastWakeRef, onWakeRef, "openwakeword", "MINDI"),
    });
    owwDetectorRef.current = detector;
    try {
      await detector.start(stream);
      isWakeListeningRef.current = true;
      setWakeListening(true);
      setMicBlocked(false);
    } catch (error) {
      owwDetectorRef.current = null;
      setMicBlocked(true);
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "OWW",
        location: "useWakeWord.ts:startOpenWakeWord",
        message: "openWakeWord start failed",
        data: { error: error instanceof Error ? error.message : String(error) },
      });
    }
  }, [acquireWakeMic, stopOpenWakeWord]);

  const stop = useCallback(() => {
    dualWakeRef.current = false;
    isWakeListeningRef.current = false;
    setWakeListening(false);
    void stopOpenWakeWord();
    stopSpeechWake(false);
    stopAsrWake(false);
    releaseWakeMic();
  }, [releaseWakeMic, stopAsrWake, stopOpenWakeWord, stopSpeechWake]);

  const scanWakeChunk = useCallback(async (blob: Blob) => {
    if (asrWakeSuppressedRef.current) {
      stopAsrWake();
      return;
    }
    if (!enabledRef.current || activeRef.current) {
      return;
    }
    if (blob.size < MIN_WAKE_BLOB_BYTES) {
      return;
    }
    if (scanInFlightRef.current) {
      pendingWakeChunkRef.current = blob;
      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "M",
        location: "useWakeWord.ts:asrScan:queued",
        message: "asr wake chunk queued while scan in flight",
        data: { blobSize: blob.size },
      });
      // #endregion
      return;
    }

    scanInFlightRef.current = true;
    try {
      const wavBlob = await convertBlobToWav(blob);
      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "AB",
        location: "useWakeWord.ts:asrScan:wav",
        message: "converted wake chunk to wav for asr",
        data: { inputBytes: blob.size, wavBytes: wavBlob.size, inputType: blob.type },
      });
      // #endregion
      const dataUrl = await blobToBase64(wavBlob);
      const extension = "wav";
      let sourceValue = dataUrl;
      try {
        sourceValue = await orbSaveAudioTemp(dataUrl, extension);
      } catch {
        // Browser-only fallback keeps data URL payload.
      }

      const asr = await transcribeWakeBlob(sourceValue);
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
      if (
        !patternMatch &&
        "reason" in asr &&
        (String(asr.reason) === "asr_model_not_ready" ||
          String(asr.reason) === "asr_model_load_failed")
      ) {
        asrReadyRef.current = false;
        stopAsrWake();
        // #region agent log
        debugSessionLog({
          runId: "post-fix",
          hypothesisId: "A,M,Y",
          location: "useWakeWord.ts:asrScan:disabled",
          message: "asr wake disabled after model not ready",
          data: {
            speechFallback: Boolean(getSpeechRecognition()) && !isTauriRuntime(),
            isTauri: isTauriRuntime(),
          },
        });
        // #endregion
        if (isTauriRuntime()) {
          setMicBlocked(true);
          if (enabledRef.current && !activeRef.current && isMicEnabled()) {
            window.setTimeout(() => {
              startRef.current();
            }, 5000);
          }
        } else if (getSpeechRecognition() && enabledRef.current && !activeRef.current && isMicEnabled()) {
          asrWakeSuppressedRef.current = true;
          void startSpeechWakePrimedRef.current();
        }
      }
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
      const pending = pendingWakeChunkRef.current;
      pendingWakeChunkRef.current = null;
      if (pending) {
        void scanWakeChunk(pending);
      }
    }
  }, [stopAsrWake]);

  const beginAsrRecorder = useCallback(
    (stream: MediaStream) => {
      if (recorderRef.current?.state === "recording") {
        return;
      }

      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          void scanWakeChunk(event.data);
        }
      };
      recorder.onstop = () => {
        recorderRef.current = null;
        const shouldRestart =
          !asrWakeSuppressedRef.current &&
          asrReadyRef.current &&
          enabledRef.current &&
          !activeRef.current &&
          isMicEnabled() &&
          (isTauriRuntime() || !getSpeechRecognition());
        if (shouldRestart) {
          window.setTimeout(() => {
            if (isTauriRuntime()) {
              void beginAsrRecorderOnSharedMicRef.current();
            } else {
              void startAsrWakeRef.current();
            }
          }, 300);
        }
      };
      recorder.start(ASR_WAKE_SLICE_MS);
      recorderRef.current = recorder;
      isWakeListeningRef.current = true;
      setWakeListening(true);
      setMicBlocked(false);

      // #region agent log
      debugSessionLog({
        runId: "post-remote-fix",
        hypothesisId: "A,C,W",
        location: "useWakeWord.ts:startAsrWake:ok",
        message: "asr wake listening started",
        data: {
          sliceMs: ASR_WAKE_SLICE_MS,
          isTauri: isTauriRuntime(),
          dualWake: dualWakeRef.current,
          sharedMic: Boolean(sharedMicRef.current),
        },
      });
      // #endregion
    },
    [scanWakeChunk],
  );

  const beginAsrRecorderOnSharedMicRef = useRef<() => Promise<void>>(async () => undefined);
  const startAsrWakeRef = useRef<() => Promise<void>>(async () => undefined);

  const beginAsrRecorderOnSharedMic = useCallback(async () => {
    const stream = await acquireWakeMic();
    if (!stream || !enabledRef.current || activeRef.current || !isMicEnabled()) {
      return;
    }
    beginAsrRecorder(stream);
  }, [acquireWakeMic, beginAsrRecorder]);

  const startAsrWake = useCallback(async () => {
    if (
      asrWakeSuppressedRef.current ||
      !enabledRef.current ||
      activeRef.current ||
      !isMicEnabled() ||
      !asrReadyRef.current
    ) {
      return;
    }
    if (getSpeechRecognition() && !dualWakeRef.current) {
      return;
    }
    if (recorderRef.current?.state === "recording") {
      return;
    }

    stopAsrWake(dualWakeRef.current);

    try {
      const stream = dualWakeRef.current ? await acquireWakeMic() : await requestMicStream();
      if (!stream) {
        return;
      }
      if (!dualWakeRef.current) {
        streamRef.current = stream;
      }
      beginAsrRecorder(stream);
      } catch (error) {
        setMicBlocked(true);
        // #region agent log
        debugSessionLog({
          runId: "post-remote-fix",
          hypothesisId: "C",
          location: "useWakeWord.ts:startAsrWake:catch",
          message: "asr wake getUserMedia failed",
          data: {
            error: error instanceof Error ? error.message : String(error),
            isTauri: isTauriRuntime(),
          },
        });
        // #endregion
        if (getSpeechRecognition()) {
          void startSpeechWakePrimedRef.current();
          return;
        }
        if (enabledRef.current && !activeRef.current && isMicEnabled()) {
          window.setTimeout(() => {
            void startAsrWake();
          }, 2000);
        }
      }
  }, [acquireWakeMic, beginAsrRecorder, stopAsrWake]);

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
    const recognitionWithStart = recognition as SpeechRecognitionLike & {
      onstart?: (() => void) | null;
      onaudiostart?: (() => void) | null;
    };
    recognitionWithStart.onstart = () => {
      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "U",
        location: "useWakeWord.ts:onspeechstart",
        message: "speech recognition session started",
        data: {
          dualWake: dualWakeRef.current,
          hasPrimeStream: Boolean(primeStreamRef.current),
          isTauri: isTauriRuntime(),
        },
      });
      // #endregion
    };
    recognition.onresult = (event) => {
      let transcript = "";
      let latestSegment = "";
      for (let index = 0; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result?.[0]?.transcript) {
          const piece = result[0].transcript;
          transcript += piece;
          latestSegment = piece;
        }
      }
      const patternMatch =
        transcriptMatchesWake(transcript) || transcriptMatchesWake(latestSegment);
      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "D",
        location: "useWakeWord.ts:onresult",
        message: "speech api wake result",
        data: {
          transcriptLen: transcript.length,
          transcriptTail: transcript.slice(-40),
          latestSegment: latestSegment.slice(-40),
          transcriptPreview: transcript.length <= 48 ? transcript : undefined,
          patternMatch,
        },
      });
      // #endregion
      if (patternMatch) {
        triggerWake(lastWakeRef, onWakeRef, "speech", transcript || latestSegment);
      }
    };
    recognition.onerror = (event) => {
      // #region agent log
      debugSessionLog({
        runId: "post-remote-fix",
        hypothesisId: "C,D",
        location: "useWakeWord.ts:onerror",
        message: "speech api wake error",
        data: { error: event.error, willRestart: event.error === "no-speech" || event.error === "aborted" },
      });
      // #endregion
      if (event.error === "no-speech" || event.error === "aborted") {
        return;
      }
      stopSpeechWake();
    };
    recognition.onend = () => {
      recognitionRef.current = null;
      if (!enabledRef.current || activeRef.current || !isMicEnabled()) {
        return;
      }
      if (speechRestartTimerRef.current) {
        window.clearTimeout(speechRestartTimerRef.current);
      }
      speechRestartTimerRef.current = window.setTimeout(() => {
        speechRestartTimerRef.current = null;
        if (dualWakeRef.current) {
          startSpeechWakeDirect();
        } else {
          void startSpeechWakePrimedRef.current();
        }
      }, dualWakeRef.current ? 800 : 400);
    };

    try {
      recognition.start();
      recognitionRef.current = recognition;
      isWakeListeningRef.current = true;
      setWakeListening(true);
      // #region agent log
      debugSessionLog({
        runId: "post-remote-fix",
        hypothesisId: "C",
        location: "useWakeWord.ts:startSpeechWake:ok",
        message: "speech api wake listening started",
        data: { isTauri: isTauriRuntime() },
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

    const streamEnded =
      primeStreamRef.current?.getTracks().every((track) => track.readyState === "ended") ?? false;
    if (!primeStreamRef.current || streamEnded) {
      if (streamEnded && primeStreamRef.current) {
        primeStreamRef.current = null;
      }
      try {
        primeStreamRef.current = await requestMicStream();
        setMicBlocked(false);
        // #region agent log
        debugSessionLog({
          runId: "post-fix",
          hypothesisId: "C,N",
          location: "useWakeWord.ts:primeMic:held",
          message: "mic stream held open for speech wake",
          data: { isTauri: isTauriRuntime(), dualWake: dualWakeRef.current },
        });
        // #endregion
      } catch (error) {
        setMicBlocked(true);
        // #region agent log
        debugSessionLog({
          runId: "post-remote-fix",
          hypothesisId: "C",
          location: "useWakeWord.ts:primeMic:catch",
          message: "mic prime failed for speech wake",
          data: {
            error: error instanceof Error ? error.message : String(error),
            isTauri: isTauriRuntime(),
          },
        });
        // #endregion
        return;
      }
    }

    startSpeechWake();
  }, [startSpeechWake]);

  const startSpeechWakeDirect = useCallback(() => {
    // #region agent log
    debugSessionLog({
      runId: "post-fix",
      hypothesisId: "V",
      location: "useWakeWord.ts:startSpeechWake:direct",
      message: "speech wake without getUserMedia prime",
      data: { isTauri: isTauriRuntime(), dualWake: dualWakeRef.current },
    });
    // #endregion
    startSpeechWake();
  }, [startSpeechWake]);

  const startAsrWakeOnly = useCallback(async () => {
    if (wakeStartInFlightRef.current) {
      return;
    }
    wakeStartInFlightRef.current = true;
    try {
      stopSpeechWake(false);
      stopAsrWake(false);
      releaseWakeMic();

      const stream = await acquireWakeMic();
      if (!stream || !enabledRef.current || activeRef.current || !isMicEnabled()) {
        return;
      }

      beginAsrRecorder(stream);
    } finally {
      wakeStartInFlightRef.current = false;
    }
  }, [acquireWakeMic, beginAsrRecorder, releaseWakeMic, stopAsrWake, stopSpeechWake]);

  useEffect(() => {
    beginAsrRecorderOnSharedMicRef.current = beginAsrRecorderOnSharedMic;
  }, [beginAsrRecorderOnSharedMic]);

  useEffect(() => {
    startAsrWakeRef.current = startAsrWake;
  }, [startAsrWake]);

  useEffect(() => {
    startSpeechWakePrimedRef.current = startSpeechWakePrimed;
  }, [startSpeechWakePrimed]);

  const start = useCallback(() => {
    if (!enabled || active || !isMicEnabled()) {
      return;
    }

    const speechAvailable = !!getSpeechRecognition();

    const tauriAsrOnly = isTauriRuntime();
    const recorderActive = recorderRef.current?.state === "recording";
    const canRetryWake = tauriAsrOnly
      ? !recorderActive
      : speechAvailable && !recognitionRef.current && !recorderRef.current;

    if (isWakeListeningRef.current && !canRetryWake) {
      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "T,Z",
        location: "useWakeWord.ts:start:skip",
        message: "wake start skipped, already listening",
        data: {
          recorderState: recorderRef.current?.state ?? "none",
          hasRecognition: Boolean(recognitionRef.current),
          tauriAsrOnly,
          canRetryWake,
        },
      });
      // #endregion
      return;
    }

    if (tauriAsrOnly && recognitionRef.current) {
      stopSpeechWake(false);
    }

    void checkAsrReady().then((ready) => {
      asrReadyRef.current = ready;
      const tauriAsrOnly = isTauriRuntime();
      dualWakeRef.current = false;

      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "A,B,Y",
        location: "useWakeWord.ts:start:entry",
        message: "wake start() resolved",
        data: {
          wakeFixVersion: "asr-wake-v11",
          enabled: enabledRef.current,
          active: activeRef.current,
          micEnabled: isMicEnabled(),
          isTauri: isTauriRuntime(),
          asrReady: ready,
          asrSuppressed: asrWakeSuppressedRef.current,
          hasRecognition: speechAvailable,
          tauriAsrOnly,
          hasMediaDevices: Boolean(navigator.mediaDevices),
          hasGetUserMedia: typeof navigator.mediaDevices?.getUserMedia === "function",
        },
      });
      // #endregion

      if (!enabledRef.current || activeRef.current || !isMicEnabled()) {
        return;
      }

      if (tauriAsrOnly) {
        void startOpenWakeWord();
        return;
      } else if (speechAvailable) {
        asrWakeSuppressedRef.current = true;
        stopAsrWake();
        void startSpeechWakePrimed();
      } else if (ready) {
        asrWakeSuppressedRef.current = false;
        void startAsrWake();
      }

      const useAsrPath = tauriAsrOnly ? ready : ready && !speechAvailable;
      const useSpeechPath = (!tauriAsrOnly && speechAvailable) || (tauriAsrOnly && !ready && speechAvailable);
      if (useAsrPath || useSpeechPath) {
        // #region agent log
        debugSessionLog({
          runId: "post-fix",
          hypothesisId: "A,M,Y",
          location: "useWakeWord.ts:start:paths",
          message: "wake listening paths started",
          data: {
            asrPath: useAsrPath,
            speechPath: useSpeechPath,
            tauriAsrOnly,
            isTauri: isTauriRuntime(),
          },
        });
        // #endregion
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
  }, [active, enabled, startAsrWake, startAsrWakeOnly, startOpenWakeWord, startSpeechWakePrimed, stopAsrWake]);

  useEffect(() => {
    startRef.current = start;
  }, [start]);

  useEffect(() => {
    if (enabled && !active && isMicEnabled()) {
      if (isTauriRuntime()) {
        stopSpeechWake(false);
      }
      start();
    } else {
      stop();
    }
    return stop;
  }, [active, enabled, start, stop, stopSpeechWake]);

  return { wakeListening, micBlocked };
}

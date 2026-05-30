import { useCallback, useEffect, useRef } from "react";
import { sendAssistantRequest, transcribeMicBlob } from "../lib/agent-api";
import { debugSessionLog } from "../lib/debug-session-log";
import { enqueueSyncItem } from "../lib/local-state";
import { isTauriRuntime, orbSaveAudioTemp } from "../lib/tauri-window";
import { isMicEnabled } from "../lib/orb-agent";

const SILENCE_END_MS = 1400;
const SPEECH_LEVEL_THRESHOLD = 14;
const MAX_LISTEN_MS = 30000;

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

function waitForSpeechVoices(timeoutMs = 1200): Promise<SpeechSynthesisVoice[]> {
  return new Promise((resolve) => {
    const voices = window.speechSynthesis.getVoices();
    if (voices.length > 0) {
      resolve(voices);
      return;
    }

    const finish = () => resolve(window.speechSynthesis.getVoices());
    window.speechSynthesis.onvoiceschanged = finish;
    window.setTimeout(finish, timeoutMs);
  });
}

function pickSpeechVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | undefined {
  const english =
    voices.find((voice) => voice.lang.toLowerCase().startsWith("en") && voice.localService) ??
    voices.find((voice) => voice.lang.toLowerCase().startsWith("en")) ??
    voices[0];
  return english;
}

function speakText(text: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (!("speechSynthesis" in window)) {
      reject(new Error("speech_synthesis_unavailable"));
      return;
    }

    void waitForSpeechVoices()
      .then((voices) => {
        window.speechSynthesis.cancel();
        window.speechSynthesis.resume();

        const utterance = new SpeechSynthesisUtterance(text);
        const voice = pickSpeechVoice(voices);
        if (voice) {
          utterance.voice = voice;
          utterance.lang = voice.lang;
        } else {
          utterance.lang = "en-US";
        }
        utterance.rate = 1;
        utterance.pitch = 1;
        utterance.onend = () => resolve();
        utterance.onerror = () => reject(new Error("speech_synthesis_failed"));
        window.speechSynthesis.speak(utterance);
      })
      .catch(() => reject(new Error("speech_synthesis_failed")));
  });
}

export interface VoiceSessionOptions {
  onLevel?: (level: number) => void;
  onUtteranceComplete?: () => void;
}

export interface AssistantTurn {
  reply: string;
  degraded: boolean;
  reason?: string;
}

export function useVoiceSession(options: VoiceSessionOptions = {}) {
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const transcriptRef = useRef("");
  const audioContextRef = useRef<AudioContext | null>(null);
  const vadFrameRef = useRef<number | null>(null);
  const speechSeenRef = useRef(false);
  const silenceStartRef = useRef<number | null>(null);
  const utteranceCompleteRef = useRef(options.onUtteranceComplete);
  const listenStartedAtRef = useRef(0);

  useEffect(() => {
    utteranceCompleteRef.current = options.onUtteranceComplete;
  }, [options.onUtteranceComplete]);

  const stopVad = useCallback(() => {
    if (vadFrameRef.current !== null) {
      cancelAnimationFrame(vadFrameRef.current);
      vadFrameRef.current = null;
    }
    speechSeenRef.current = false;
    silenceStartRef.current = null;
    if (audioContextRef.current) {
      void audioContextRef.current.close();
      audioContextRef.current = null;
    }
  }, []);

  const cleanupStream = useCallback(() => {
    stopVad();
    mediaRecorderRef.current = null;
    if (mediaStreamRef.current) {
      for (const track of mediaStreamRef.current.getTracks()) {
        track.stop();
      }
      mediaStreamRef.current = null;
    }
  }, [stopVad]);

  const stopRecognition = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.onend = null;
      recognitionRef.current.stop();
      recognitionRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => {
      stopRecognition();
      cleanupStream();
      if ("speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
    };
  }, [cleanupStream, stopRecognition]);

  const speak = useCallback(async (text: string) => {
    if (!text.trim()) {
      return;
    }
    await speakText(text);
  }, []);

  const startListening = useCallback(async (): Promise<void> => {
    if (!isMicEnabled()) {
      throw new Error("mic_disabled");
    }

    transcriptRef.current = "";
    chunksRef.current = [];
    speechSeenRef.current = false;
    silenceStartRef.current = null;
    listenStartedAtRef.current = Date.now();

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
      },
    });
    mediaStreamRef.current = stream;

    const audioContext = new AudioContext();
    audioContextRef.current = audioContext;
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 512;
    const source = audioContext.createMediaStreamSource(stream);
    source.connect(analyser);
    const frequencyData = new Uint8Array(analyser.frequencyBinCount);

    const runVadFrame = () => {
      if (!mediaStreamRef.current) {
        return;
      }
      analyser.getByteFrequencyData(frequencyData);
      let sum = 0;
      for (let index = 0; index < frequencyData.length; index += 1) {
        sum += frequencyData[index] ?? 0;
      }
      const level = sum / frequencyData.length;
      options.onLevel?.(Math.min(1, level / 64));

      if (level > SPEECH_LEVEL_THRESHOLD) {
        speechSeenRef.current = true;
        silenceStartRef.current = null;
      } else if (speechSeenRef.current) {
        const now = Date.now();
        if (silenceStartRef.current === null) {
          silenceStartRef.current = now;
        } else if (now - silenceStartRef.current >= SILENCE_END_MS) {
          // #region agent log
          debugSessionLog({
            runId: "pre-fix",
            hypothesisId: "D",
            location: "useVoiceSession.ts:vad",
            message: "silence after speech triggers utterance complete",
            data: { level: Math.round(level), transcriptLen: transcriptRef.current.length },
          });
          // #endregion
          utteranceCompleteRef.current?.();
          return;
        }
      }

      if (Date.now() - listenStartedAtRef.current >= MAX_LISTEN_MS) {
        utteranceCompleteRef.current?.();
        return;
      }

      vadFrameRef.current = requestAnimationFrame(runVadFrame);
    };
    vadFrameRef.current = requestAnimationFrame(runVadFrame);

    // In Tauri, prefer Qwen ASR (via stopListening) over the Web Speech API.
    // Web Speech is only used as a fallback in browser dev.
    const Recognition = isTauriRuntime() ? null : getSpeechRecognition();
    if (Recognition) {
      const recognition = new Recognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = "en-US";
      recognition.onresult = (event) => {
        let latest = "";
        let hasFinal = false;
        for (let index = 0; index < event.results.length; index += 1) {
          const result = event.results[index];
          if (result?.isFinal) {
            hasFinal = true;
          }
          if (result?.[0]?.transcript) {
            latest += result[0].transcript;
          }
        }
        transcriptRef.current = latest.trim();
        options.onLevel?.(Math.min(1, latest.length / 40));
        if (hasFinal && transcriptRef.current.length > 2) {
          speechSeenRef.current = true;
          silenceStartRef.current = Date.now() - SILENCE_END_MS;
        }
      };
      recognition.onerror = () => {
        // Recognition may fail silently; MediaRecorder remains the fallback.
      };
      recognition.start();
      recognitionRef.current = recognition;
    }

    const recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        chunksRef.current.push(event.data);
      }
    };
    recorder.start(250);
    mediaRecorderRef.current = recorder;
  }, [options]);

  const stopListening = useCallback(async (): Promise<string> => {
    stopRecognition();

    const recorder = mediaRecorderRef.current;
    let blob: Blob | null = null;

    if (recorder && recorder.state !== "inactive") {
      blob = await new Promise<Blob>((resolve) => {
        recorder.onstop = () => {
          resolve(new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" }));
        };
        recorder.stop();
      });
    }

    cleanupStream();

    const liveTranscript = transcriptRef.current.trim();
    if (liveTranscript) {
      return liveTranscript;
    }

    if (!blob || blob.size === 0) {
      return "";
    }

    try {
      const dataUrl = await blobToBase64(blob);
      const extension = blob.type.includes("webm") ? "webm" : "wav";
      let sourceValue = dataUrl;

      try {
        const tempPath = await orbSaveAudioTemp(dataUrl, extension);
        sourceValue = tempPath;
      } catch {
        // Browser-only fallback keeps data URL/base64 payload.
      }

      const asr = await transcribeMicBlob(sourceValue);
      if (asr.accepted && asr.text?.trim()) {
        return asr.text.trim();
      }
    } catch {
      // Fall through to empty transcript.
    }

    return "";
  }, [cleanupStream, stopRecognition]);

  const askAssistant = useCallback(async (text: string): Promise<AssistantTurn> => {
    const trimmed = text.trim();
    if (!trimmed) {
      return { reply: "I did not catch that. Try again.", degraded: false };
    }

    try {
      const response = await sendAssistantRequest({
        text: trimmed,
        mode: "chat",
        tab: "home",
      });
      // #region agent log
      debugSessionLog({
        runId: "post-fix",
        hypothesisId: "E",
        location: "useVoiceSession.ts:askAssistant",
        message: "assistant respond received",
        data: {
          provider: response.provider,
          model: response.model,
          degraded: response.degraded,
          fallbackReason: response.fallbackReason,
          replyLen: (response.reply ?? "").length,
        },
      });
      // #endregion
      if (response.degraded) {
        return {
          reply:
            response.reply?.trim() ||
            `Local model unavailable (${response.fallbackReason ?? "runtime_error"}). Check agent and AI runtime.`,
          degraded: true,
          reason: response.fallbackReason,
        };
      }
      return { reply: response.reply?.trim() || "I am ready when you are.", degraded: false };
    } catch {
      enqueueSyncItem({
        type: "chat",
        payload: { text: trimmed, mode: "chat", tab: "home" },
      });
      return {
        reply: "I am offline right now, but I queued your request.",
        degraded: true,
        reason: "agent_unreachable",
      };
    }
  }, []);

  return {
    speak,
    startListening,
    stopListening,
    askAssistant,
  };
}

import { useCallback, useEffect, useMemo, useRef } from "react";
import { convertBlobToWav } from "../lib/orb-audio";
import { streamAssistantRequest, synthesizeTts, transcribeMicBlob } from "../lib/agent-api";
import { enqueueSyncItem } from "../lib/local-state";
import { debugSessionLog } from "../lib/debug-session-log";
import { isTauriRuntime, orbSaveAudioTemp } from "../lib/tauri-window";
import { isMicEnabled, requestMicStream } from "../lib/orb-agent";

const SILENCE_END_MS = 1400;
const SPEECH_LEVEL_THRESHOLD = 14;
const MAX_LISTEN_MS = 30000;
const MIN_VOICE_TURN_MS = 1500;

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

function playAudioDataUrl(audioDataUrl: string, audioRef: { current: HTMLAudioElement | null }): Promise<void> {
  return new Promise((resolve, reject) => {
    const audio = new Audio(audioDataUrl);
    audioRef.current = audio;
    audio.onended = () => {
      if (audioRef.current === audio) {
        audioRef.current = null;
      }
      resolve();
    };
    audio.onerror = () => {
      if (audioRef.current === audio) {
        audioRef.current = null;
      }
      reject(new Error("audio_playback_failed"));
    };
    void audio.play().catch(() => reject(new Error("audio_playback_failed")));
  });
}

async function speakViaAiRuntime(text: string, audioRef: { current: HTMLAudioElement | null }): Promise<void> {
  const result = await synthesizeTts({ text });
  // #region agent log
  debugSessionLog({
    runId: "post-fix",
    hypothesisId: "H5",
    location: "useVoiceSession.ts:speakViaAiRuntime",
    message: "local AI TTS synthesis result",
    data: {
      accepted: result.accepted,
      reason: result.reason,
      provider: result.provider,
      model: result.model,
      textPreview: text.slice(0, 60),
    },
  });
  // #endregion
  if (!result.accepted || !result.audioDataUrl) {
    throw new Error(result.reason ?? "tts_unavailable");
  }
  await playAudioDataUrl(result.audioDataUrl, audioRef);
}

function splitSentences(buffer: string): { ready: string[]; remainder: string } {
  const parts = buffer.split(/(?<=[.!?])\s+/);
  if (parts.length <= 1) {
    return { ready: [], remainder: buffer };
  }
  const remainder = parts.pop() ?? "";
  return { ready: parts.filter((part) => part.trim().length > 0), remainder };
}

export interface VoiceSessionOptions {
  onLevel?: (level: number) => void;
  onUtteranceComplete?: () => void;
  onPartialTranscript?: (text: string) => void;
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
  const activeAudioRef = useRef<HTMLAudioElement | null>(null);

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
      if (activeAudioRef.current) {
        activeAudioRef.current.pause();
        activeAudioRef.current = null;
      }
    };
  }, [cleanupStream, stopRecognition]);

  const speak = useCallback(async (text: string) => {
    if (!text.trim()) {
      return;
    }
    if (activeAudioRef.current) {
      activeAudioRef.current.pause();
      activeAudioRef.current = null;
    }
    await speakViaAiRuntime(text, activeAudioRef);
  }, []);

  const stopSpeaking = useCallback(() => {
    if (activeAudioRef.current) {
      activeAudioRef.current.pause();
      activeAudioRef.current = null;
    }
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

    const stream = await requestMicStream();
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
        options.onPartialTranscript?.(transcriptRef.current);
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

    if (Date.now() - listenStartedAtRef.current < MIN_VOICE_TURN_MS) {
      return "";
    }

    try {
      const wavBlob = await convertBlobToWav(blob);
      const dataUrl = await blobToBase64(wavBlob);
      const extension = "wav";
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

  const askAssistant = useCallback(
    async (
      text: string,
      options?: {
        wakeInvoke?: boolean;
        onToken?: (token: string, fullText: string) => void;
        onSentence?: (sentence: string) => Promise<void>;
      },
    ): Promise<AssistantTurn> => {
    const trimmed = text.trim();
    const wakeInvoke = options?.wakeInvoke ?? false;
    if (!wakeInvoke && !trimmed) {
      return { reply: "I did not catch that. Try again.", degraded: false };
    }

    try {
      let streamed = "";
      let sentenceBuffer = "";
      const finalEvent = await streamAssistantRequest(
        {
          text: wakeInvoke ? "MINDI" : trimmed,
          mode: "chat",
          tab: "home",
          wakeInvoke,
        },
        async (event) => {
          if (!event.token) {
            return;
          }
          streamed += event.token;
          sentenceBuffer += event.token;
          options?.onToken?.(event.token, streamed);
          const { ready, remainder } = splitSentences(sentenceBuffer);
          sentenceBuffer = remainder;
          for (const sentence of ready) {
            if (options?.onSentence) {
              await options.onSentence(sentence);
            }
          }
        },
      );
      if (sentenceBuffer.trim() && options?.onSentence) {
        await options.onSentence(sentenceBuffer.trim());
      }
      if (finalEvent?.error) {
        return {
          reply: _LLM_UNAVAILABLE(finalEvent.error),
          degraded: true,
          reason: finalEvent.error,
        };
      }
      if (finalEvent?.degraded) {
        return {
          reply:
            finalEvent.reply?.trim() ||
            streamed.trim() ||
            `Local model unavailable (${finalEvent.fallbackReason ?? "runtime_error"}). Check agent and AI runtime.`,
          degraded: true,
          reason: finalEvent.fallbackReason,
        };
      }
      return {
        reply: finalEvent?.reply?.trim() || streamed.trim() || "I am ready when you are.",
        degraded: false,
      };
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

  return useMemo(
    () => ({
      speak,
      stopSpeaking,
      startListening,
      stopListening,
      askAssistant,
    }),
    [speak, stopSpeaking, startListening, stopListening, askAssistant],
  );
}

function _LLM_UNAVAILABLE(reason: string): string {
  const replies: Record<string, string> = {
    model_path_missing: "No local model is configured. Open Settings > AI Runtime and point MINDI to a GGUF model file.",
    voice_model_path_missing: "Voice model missing. Configure the 3B model in AI Runtime settings.",
    runtime_unreachable: "The AI Runtime service is not running. Start it from the MINDI launcher or terminal.",
  };
  return replies[reason] ?? "I am here but my language model is not loaded yet. Open the AI Runtime panel to configure and start it.";
}

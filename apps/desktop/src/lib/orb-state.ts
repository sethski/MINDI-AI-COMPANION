export type OrbPhase =
  | "idle"
  | "waking"
  | "greeting"
  | "listening"
  | "thinking"
  | "speaking"
  | "error";

export const ORB_IDLE_SIZE = { width: 72, height: 72 } as const;
export const ORB_MENU_SIZE = { width: 180, height: 156 } as const;
export const ORB_ACTIVE_SIZE = { width: 288, height: 96 } as const;

const WAKE_TOKEN_PATTERN = /\b(?:hey[,]?\s*)?(?:mindi|mindy)\b/i;
const WAKE_STRIP_PATTERN = /\b(?:hey[,]?\s*)?(?:mindi|mindy)\b/gi;

function normalizeTranscriptForWake(transcript: string): string {
  return transcript.toLowerCase().replace(/[^\w\s']/g, " ").replace(/\s+/g, " ").trim();
}

export function transcriptMatchesWake(transcript: string): boolean {
  const normalized = normalizeTranscriptForWake(transcript);
  return WAKE_TOKEN_PATTERN.test(normalized);
}

export function stripWakeWord(transcript: string): string {
  return transcript.replace(WAKE_STRIP_PATTERN, " ").replace(/\s+/g, " ").trim();
}

export function isActivePhase(phase: OrbPhase): boolean {
  return phase !== "idle" && phase !== "error";
}

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

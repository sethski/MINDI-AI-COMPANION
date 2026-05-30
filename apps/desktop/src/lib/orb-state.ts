export type OrbPhase =
  | "idle"
  | "waking"
  | "greeting"
  | "listening"
  | "thinking"
  | "speaking"
  | "error";

export const ORB_IDLE_SIZE = { width: 72, height: 72 } as const;
export const ORB_ACTIVE_SIZE = { width: 320, height: 120 } as const;

export const ORB_GREETINGS = [
  "Hi, I'm MINDI. What do you need?",
  "Hello. I'm listening.",
  "Hey there. How can I help?",
] as const;

export function pickGreeting(): string {
  const index = Math.floor(Math.random() * ORB_GREETINGS.length);
  return ORB_GREETINGS[index] ?? ORB_GREETINGS[0];
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

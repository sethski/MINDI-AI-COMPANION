import { emit, listen } from "@tauri-apps/api/event";
import {
  analyzeScreenPerception,
  postProactiveOrbActivity,
  pullProactiveNudges,
  streamAssistantRequest,
} from "./agent-api";
import { isTauriRuntime } from "./tauri-window";
import { captureScreenDataUrl } from "./screen-capture";

export async function reportOrbIdle(idle: boolean): Promise<void> {
  if (!isTauriRuntime()) {
    return;
  }
  try {
    await postProactiveOrbActivity(idle);
  } catch {
    // agent offline
  }
}

export async function pollProactiveNudges(): Promise<void> {
  if (!isTauriRuntime()) {
    return;
  }
  try {
    const nudges = await pullProactiveNudges(2);
    for (const nudge of nudges) {
      await emit("mindi-nudge", nudge);
    }
  } catch {
    // agent offline
  }
}

export async function runScreenHelpFlow(): Promise<void> {
  const imageDataUrl = await captureScreenDataUrl();
  const perception = await analyzeScreenPerception({
    imageDataUrl,
    includeOcr: true,
    maxBlocks: 25,
  });
  if (!perception.accepted) {
    throw new Error(perception.reason || "screen_analyze_failed");
  }
  const snippet = (perception.text || "").trim().slice(0, 1200);
  const prompt = snippet
    ? `I captured my screen. Based on this OCR text, tell me what I should focus on and offer one helpful next step.\n\nScreen text:\n${snippet}`
    : "I captured my screen but OCR found little text. Tell me what you can infer and one helpful next step.";
  let reply = "";
  await streamAssistantRequest({ text: prompt, mode: "chat", tab: "home" }, (event) => {
    if (event.token) {
      reply += event.token;
    }
  });
  await emit("mindi-screen-help-result", { reply: reply.trim() || "Screen captured." });
}

export async function listenScreenHelpHotkey(onResult: (reply: string) => void): Promise<() => void> {
  if (!isTauriRuntime()) {
    return () => undefined;
  }
  const unlistenHotkey = await listen("mindi-screen-help", () => {
    void runScreenHelpFlow().catch((error) => {
      void emit("mindi-screen-help-result", {
        reply: error instanceof Error ? error.message : "Screen help failed.",
      });
    });
  });
  const unlistenResult = await listen<{ reply: string }>("mindi-screen-help-result", (event) => {
    onResult(event.payload.reply);
  });
  return () => {
    unlistenHotkey();
    unlistenResult();
  };
}

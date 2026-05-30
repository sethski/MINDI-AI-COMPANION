import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";

export function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && isTauri();
}

export async function orbStartDrag(): Promise<void> {
  if (!isTauriRuntime()) {
    return;
  }
  await invoke("orb_start_drag");
}

export async function orbSetSize(width: number, height: number): Promise<void> {
  if (!isTauriRuntime()) {
    return;
  }
  await invoke("orb_set_size", { width, height });
}

export async function orbSavePosition(x: number, y: number): Promise<void> {
  if (!isTauriRuntime()) {
    return;
  }
  await invoke("orb_save_position", { x, y });
}

export async function orbClampPosition(): Promise<void> {
  if (!isTauriRuntime()) {
    return;
  }
  await invoke("orb_clamp_position");
}

export async function orbFocus(): Promise<void> {
  if (!isTauriRuntime()) {
    return;
  }
  await invoke("orb_focus");
}

export async function showMainWindow(): Promise<void> {
  if (!isTauriRuntime()) {
    return;
  }
  await invoke("show_main_window");
}

export async function quitApp(): Promise<void> {
  if (!isTauriRuntime()) {
    return;
  }
  await invoke("quit_app");
}

export async function saveUploadTemp(dataBase64: string, fileName: string): Promise<string> {
  if (!isTauriRuntime()) {
    throw new Error("tauri_unavailable");
  }
  return invoke<string>("save_upload_temp", { dataBase64, fileName });
}

export async function orbSaveAudioTemp(dataBase64: string, extension: string): Promise<string> {
  if (!isTauriRuntime()) {
    throw new Error("tauri_unavailable");
  }
  return invoke<string>("orb_save_audio_temp", { dataBase64, extension });
}

export async function listenOrbWake(onWake: () => void): Promise<() => void> {
  if (!isTauriRuntime()) {
    return () => undefined;
  }
  const unlisten = await listen("orb-wake", () => {
    onWake();
  });
  return unlisten;
}

export async function trackOrbDragEnd(onEnd: () => void): Promise<() => void> {
  if (!isTauriRuntime()) {
    return () => undefined;
  }
  const window = getCurrentWindow();
  const unlisten = await window.onMoved(() => {
    void (async () => {
      const pos = await window.outerPosition();
      await orbSavePosition(pos.x, pos.y);
      await orbClampPosition();
      onEnd();
    })();
  });
  return unlisten;
}

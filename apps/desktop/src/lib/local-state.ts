import type { QuickToggle, SyncQueueItem } from "@mindi/shared";

const TOGGLE_KEY = "mindi.quick_toggles.v1";
const SYNC_KEY = "mindi.sync_queue.v1";

export function loadToggleState(defaults: QuickToggle[]): QuickToggle[] {
  const raw = localStorage.getItem(TOGGLE_KEY);
  if (!raw) {
    return defaults;
  }

  try {
    const parsed = JSON.parse(raw) as QuickToggle[];
    const enabledById = new Map(parsed.map((item) => [item.id, item.enabled]));
    return defaults.map((item) => ({
      ...item,
      enabled: enabledById.get(item.id) ?? item.enabled,
    }));
  } catch {
    return defaults;
  }
}

export function saveToggleState(toggles: QuickToggle[]): void {
  localStorage.setItem(TOGGLE_KEY, JSON.stringify(toggles));
}

export function loadSyncQueue(): SyncQueueItem[] {
  const raw = localStorage.getItem(SYNC_KEY);
  if (!raw) {
    return [];
  }

  try {
    return JSON.parse(raw) as SyncQueueItem[];
  } catch {
    return [];
  }
}

export function saveSyncQueue(items: SyncQueueItem[]): void {
  localStorage.setItem(SYNC_KEY, JSON.stringify(items));
}

export function enqueueSyncItem(
  item: Omit<SyncQueueItem, "id" | "createdAt" | "status">,
): SyncQueueItem[] {
  const queue = loadSyncQueue();
  queue.push({
    ...item,
    id: crypto.randomUUID(),
    createdAt: new Date().toISOString(),
    status: "queued",
  });
  saveSyncQueue(queue);
  return queue;
}

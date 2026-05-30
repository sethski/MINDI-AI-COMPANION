export function registerServiceWorker(): void {
  if (!("serviceWorker" in navigator)) {
    return;
  }

  // Dev + Tauri WebView: a registered SW caches /@vite/client and breaks HMR (WS 400).
  if (import.meta.env.DEV) {
    void navigator.serviceWorker.getRegistrations().then((regs) => {
      for (const reg of regs) {
        void reg.unregister();
      }
    });
    return;
  }

  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // Keep boot path stable if SW fails.
    });
  });
}

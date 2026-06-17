import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";
import { resolve } from "node:path";

const tauriDevHost = process.env.TAURI_DEV_HOST;
const tauriPlatform = process.env.TAURI_ENV_PLATFORM ?? "";
const isMobileTauri =
  tauriPlatform === "android" ||
  tauriPlatform === "ios" ||
  tauriPlatform.startsWith("android") ||
  tauriPlatform.startsWith("ios");

// Only use TAURI_DEV_HOST HMR relay on mobile; on desktop it breaks WebSocket (400 handshake).
const useMobileHmr = isMobileTauri && Boolean(tauriDevHost);

export default defineConfig({
  plugins: [react(), tsconfigPaths()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    host: useMobileHmr ? tauriDevHost : "127.0.0.1",
    headers: {
      "Permissions-Policy": "microphone=*",
    },
    hmr: useMobileHmr
      ? {
          protocol: "ws",
          host: tauriDevHost,
          port: 1421,
        }
      : {
          protocol: "ws",
          host: "127.0.0.1",
          port: 5173,
          clientPort: 5173,
        },
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
  envPrefix: ["VITE_", "TAURI_ENV_*"],
  build: {
    target: process.env.TAURI_ENV_PLATFORM === "windows" ? "chrome105" : "safari13",
    minify: !process.env.TAURI_ENV_DEBUG ? "esbuild" : false,
    sourcemap: !!process.env.TAURI_ENV_DEBUG,
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        orb: resolve(__dirname, "orb.html"),
      },
    },
  },
});

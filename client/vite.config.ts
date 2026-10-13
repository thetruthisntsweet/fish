/// <reference types="vitest/config" />
// Vite config for the Fish client (T2.1 subtask 7).
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// fish-server (FastAPI) runs on this address in development (T2.1 §7).
const SERVER = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": SERVER,
      "/ws": { target: SERVER, ws: true },
    },
  },
  build: {
    sourcemap: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});

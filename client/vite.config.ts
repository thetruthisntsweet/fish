/// <reference types="vitest/config" />
// Vite config for the Fish client (T2.1 subtask 7).
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// fish-server (FastAPI) runs on this address in development (T2.1 §7).
const SERVER = "http://127.0.0.1:8000";

// Everything the server answers besides the client's own pages and files (T3.3). In
// production the server serves the client itself, so these are the same address there too.
const ENDPOINTS = ["/auth", "/study", "/consent", "/withdraw", "/sign-in", "/health"];

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1", // the address sign-in links point at locally (setup.md)
    port: 5173,
    strictPort: true,
    proxy: {
      ...Object.fromEntries(ENDPOINTS.map((path) => [path, SERVER])),
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

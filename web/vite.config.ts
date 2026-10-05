import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

declare const process: { env: Record<string, string | undefined> }; // Node, without @types/node

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // In Docker on Windows, edits made on the host don't reach the container as file events,
    // so Vite would keep serving old code. VITE_POLL=1 (set in docker-compose) checks instead.
    watch: process.env.VITE_POLL ? { usePolling: true, interval: 1000 } : undefined,
    proxy: {
      "/api": "http://api:8000",
      "/media": "http://api:8000",
    },
  },
});
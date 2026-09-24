import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// `npm run dev` serves the dashboard on :5173 and forwards API calls to a local
// API on :8000, so the app always calls its own origin, as it does in production.
const API = "http://localhost:8000";

export default defineConfig({
  base: "/dashboard/",
  plugins: [react(), tailwindcss()],
  build: {
    // FastAPI serves the built files at /dashboard (src/intake/api/main.py).
    outDir: "../src/intake/api/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/patients": API,
      "/calls": API,
      "/doctors": API,
      "/health": API,
      "/dashboard/config": API,
    },
  },
  test: {
    environment: "node",
  },
});

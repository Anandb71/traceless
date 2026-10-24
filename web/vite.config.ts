import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const api = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(["/api", "/fixtures", "/takes", "/d/", "/u/"].map((p) => [p, api])),
  },
  build: { chunkSizeWarningLimit: 2500 },
});

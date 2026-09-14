import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // Host stays localhost:5173, which STEWARD_DEVELOPMENT_ORIGINS must list.
      "/api": { target: "http://localhost:8000", changeOrigin: false },
      "/health": { target: "http://localhost:8000", changeOrigin: false },
    },
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});

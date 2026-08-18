import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig(async () => ({
  plugins: [react()],
  resolve: {
    dedupe: ["react", "react-dom"],
  },
  clearScreen: false,
  build: {
    chunkSizeWarningLimit: 700,
  },
  server: {
    port: 1420,
    strictPort: true,
    fs: {
      allow: [path.resolve(__dirname), path.resolve(__dirname, "../plugins/providers/builtin")],
    },
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
}));

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// În dezvoltare, /api merge la FastAPI pe portul 8000 (în Docker îl servește nginx).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY ?? "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});

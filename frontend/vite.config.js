import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The Flask API runs on 127.0.0.1:5001 in development; proxy /api to it so the
// frontend can use same-origin relative URLs.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:5001",
        changeOrigin: true,
      },
    },
  },
});

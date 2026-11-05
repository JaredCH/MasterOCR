import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Override with VITE_API when the backend runs on a non-default port.
      "/api": process.env.VITE_API ?? "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});

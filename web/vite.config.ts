import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the API is the backend on localhost:8001; in production the backend serves the built app itself, on the same origin.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8001" } },
  test: { environment: "node" },
});

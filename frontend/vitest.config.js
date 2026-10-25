import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
    env: { VITE_SENTINEL_MODE: "cloud", VITE_API_BASE_URL: "https://api.example.test" },
  },
});

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const api = "http://127.0.0.1:8010";
const proxied = ["/api", "/health", "/sources", "/inventory", "/backups", "/stats", "/audit", "/docs", "/openapi.json"];

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: Object.fromEntries(proxied.map((path) => [path, api])),
  },
});

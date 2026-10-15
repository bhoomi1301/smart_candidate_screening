/// <reference types="vitest" />
import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // In development the API is proxied so auth cookies stay first-party on the Vite origin.
  const proxyTarget = env.VITE_DEV_PROXY_TARGET || "http://127.0.0.1:8000";
  return {
    plugins: [react()],
    resolve: { alias: { "@": path.resolve(__dirname, "src") } },
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": { target: proxyTarget, changeOrigin: false },
        "/health": { target: proxyTarget, changeOrigin: false },
      },
    },
    // `npm run preview` serves the production build with the same /api proxy that vercel.json sets up.
    preview: {
      port: 4173,
      strictPort: true,
      proxy: {
        "/api": { target: proxyTarget, changeOrigin: true },
        "/health": { target: proxyTarget, changeOrigin: true },
      },
    },
    build: {
      rollupOptions: {
        output: {
          // One vendor chunk for shared libraries. Splitting react and react-dom into separate manual
          // chunks creates a circular chunk dependency that crashes the production bundle on load.
          // Chart libraries are left out so they stay in the lazily loaded dashboard chunk.
          manualChunks(id) {
            if (!id.includes("node_modules")) return undefined;
            if (/node_modules[\/](recharts|d3-|victory-vendor|react-smooth|recharts-scale|decimal.js-light|lodash|eventemitter3|fast-equals|tiny-invariant)/.test(id)) return undefined;
            return "vendor";
          },
        },
      },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test/setup.ts"],
      css: false,
    },
  };
});

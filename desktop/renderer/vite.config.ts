import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `base: "./"` makes the built index.html load assets via relative paths, which
// is required when Electron serves it over the file:// protocol in production.
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { port: 5173, strictPort: true },
  build: { outDir: "dist", emptyOutDir: true },
});

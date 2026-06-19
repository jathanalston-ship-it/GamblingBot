/**
 * Preload script — the only bridge between the sandboxed renderer and the host.
 *
 * Exposes a tiny, typed surface on `window.mrp`; the renderer talks to the
 * backend over HTTP using `apiBaseUrl`. No Node APIs leak into the renderer.
 */
import { contextBridge } from "electron";

const API_PORT = Number(process.env.MRP_API_PORT ?? 8000);

const bridge = {
  apiBaseUrl: `http://127.0.0.1:${API_PORT}`,
  platform: process.platform,
  version: process.env.npm_package_version ?? "0.1.0",
} as const;

export type MrpBridge = typeof bridge;

contextBridge.exposeInMainWorld("mrp", bridge);

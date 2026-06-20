/**
 * Preload script — the only bridge between the sandboxed renderer and the host.
 *
 * Exposes a tiny, typed surface on `window.mrp`; the renderer talks to the
 * backend over HTTP using `apiBaseUrl`. The only host event surfaced is
 * `onNavigate`, which the application menu uses to ask the renderer to route
 * (e.g. "Check for Updates…"). No Node APIs leak into the renderer.
 */
import { contextBridge, ipcRenderer, type IpcRendererEvent } from "electron";

const API_PORT = Number(process.env.MRP_API_PORT ?? 8000);

const bridge = {
  apiBaseUrl: `http://127.0.0.1:${API_PORT}`,
  platform: process.platform,
  version: process.env.npm_package_version ?? "0.1.0",
  onNavigate(cb: (path: string) => void): () => void {
    const listener = (_event: IpcRendererEvent, path: string) => cb(path);
    ipcRenderer.on("mrp:navigate", listener);
    return () => ipcRenderer.removeListener("mrp:navigate", listener);
  },
};

export type MrpBridge = typeof bridge;

contextBridge.exposeInMainWorld("mrp", bridge);

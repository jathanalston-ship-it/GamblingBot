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

/** A single lifecycle event from the packaged auto-updater (electron-updater). */
export interface UpdaterEvent {
  kind: "checking" | "available" | "not-available" | "progress" | "downloaded" | "error";
  payload: {
    version?: string;
    percent?: number;
    transferred?: number;
    total?: number;
    message?: string;
  } | null;
}

const bridge = {
  apiBaseUrl: `http://127.0.0.1:${API_PORT}`,
  platform: process.platform,
  version: process.env.MRP_APP_VERSION ?? process.env.npm_package_version ?? "0.1.0",
  /** True only in the packaged desktop build, where electron-updater is wired. */
  packaged: process.env.MRP_PACKAGED === "1",
  onNavigate(cb: (path: string) => void): () => void {
    const listener = (_event: IpcRendererEvent, path: string) => cb(path);
    ipcRenderer.on("mrp:navigate", listener);
    return () => ipcRenderer.removeListener("mrp:navigate", listener);
  },
  /** In-app auto-update controls (packaged build only). */
  updater: {
    check: (): Promise<{ version: string | null }> => ipcRenderer.invoke("mrp:update:check"),
    download: (): Promise<boolean> => ipcRenderer.invoke("mrp:update:download"),
    install: (): Promise<boolean> => ipcRenderer.invoke("mrp:update:install"),
    onEvent(cb: (e: UpdaterEvent) => void): () => void {
      const listener = (_event: IpcRendererEvent, data: UpdaterEvent) => cb(data);
      ipcRenderer.on("mrp:update:event", listener);
      return () => ipcRenderer.removeListener("mrp:update:event", listener);
    },
  },
};

export type MrpBridge = typeof bridge;

contextBridge.exposeInMainWorld("mrp", bridge);

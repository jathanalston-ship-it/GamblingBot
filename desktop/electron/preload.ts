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

/** One event from the seamless-update state machine (see update-flow.ts). */
export interface UpdateFlowEvent {
  state: string;
  label: string;
  expects: string;
  detail: string | null;
  progress: number | null;
  sequence: number;
  sinceStartMs: number;
  inStateMs: number;
  error: string | null;
  /** True for an unattended (automatic) update; drives the overlay's coverage. */
  unattended: boolean;
}

/** Measured startup performance (history stats + the latest waterfall). */
export interface StartupPerf {
  launches: number;
  stats: {
    stage: string;
    count: number;
    avgMs: number;
    medianMs: number;
    p95Ms: number;
    worstMs: number;
    lastMs: number;
    tier: "ok" | "over100" | "over250" | "over500" | "over1000";
  }[];
  waterfall: { stage: string; startMs: number; durationMs: number; tier: string }[];
  latest: { at: string; totalMs: number | null; completed: boolean } | null;
}

/** A single lifecycle event from the packaged auto-updater (electron-updater). */
export interface UpdaterEvent {
  kind: "checking" | "available" | "not-available" | "progress" | "downloaded" | "error";
  payload: {
    version?: string;
    percent?: number;
    transferred?: number;
    total?: number;
    message?: string;
    statusCode?: number | null;
  } | null;
}

/** The confirmation prompt raised when an automatic update is found on launch. */
export interface UpdatePrompt {
  version: string;
  releaseName: string | null;
  downloadBytes: number;
  downloadLabel: string;
  recommendedFreeBytes: number;
  recommendedFreeLabel: string;
  sizeKnown: boolean;
}

/** Persisted auto-update preferences (app-side, survive restarts). */
export interface UpdatePreferences {
  autoUpdate: boolean;
  skippedVersion: string | null;
}

/** Live diagnostics for the Updates screen: the release feed config + a probe. */
export interface UpdateDiagnostics {
  packaged: boolean;
  currentVersion: string;
  provider: string | null;
  owner: string | null;
  repo: string | null;
  feedUrl: string | null;
  autoUpdateDisabled: boolean;
  tokenConfigured: boolean;
  probe: { url: string; status: number; ok: boolean; interpretation: string } | null;
}

/** The live diagnostics shown in the Developer Panel (Development Mode only). */
export interface DevDiagnostics {
  version: string;
  packaged: boolean;
  portable: boolean;
  devApp: boolean;
  platform: string;
  host: string;
  port: number;
  healthUrl: string;
  backendPid: number | null;
  backendStatus: string;
  adopted: boolean;
  executable: string | null;
  startupStage: string | null;
  startupFailure: { stage: string; message: string } | null;
  startupDurationMs: number | null;
  databasePath: string;
  configPath: string;
  logPath: string;
  dataDir: string;
  branch: string | null;
  startupReport: string;
  backendReport: string;
}

const bridge = {
  apiBaseUrl: `http://127.0.0.1:${API_PORT}`,
  platform: process.platform,
  version: process.env.MRP_APP_VERSION ?? process.env.npm_package_version ?? "0.1.0",
  /** True only in the packaged desktop build, where electron-updater is wired. */
  packaged: process.env.MRP_PACKAGED === "1",
  /** True only under `npm run dev-app` — gates the banner + Developer Panel. */
  dev: process.env.MRP_DEV_APP === "1",
  /** Developer Panel controls (Development Mode only; handlers registered in main). */
  devtools: {
    diagnostics: (): Promise<DevDiagnostics> => ipcRenderer.invoke("mrp:dev:diagnostics"),
    restartBackend: (): Promise<{ ok: boolean; status: string }> =>
      ipcRenderer.invoke("mrp:dev:restart-backend"),
    reloadRenderer: (): Promise<boolean> => ipcRenderer.invoke("mrp:dev:reload-renderer"),
    openPath: (which: "logs" | "database" | "config"): Promise<string> =>
      ipcRenderer.invoke("mrp:dev:open-path", which),
    exportBundle: (): Promise<string> => ipcRenderer.invoke("mrp:dev:export-bundle"),
  },
  onNavigate(cb: (path: string) => void): () => void {
    const listener = (_event: IpcRendererEvent, path: string) => cb(path);
    ipcRenderer.on("mrp:navigate", listener);
    return () => ipcRenderer.removeListener("mrp:navigate", listener);
  },
  /** Backend lifecycle status: starting | healthy | failed | restarting | stopped. */
  onBackendStatus(cb: (status: string) => void): () => void {
    const listener = (_event: IpcRendererEvent, status: string) => cb(status);
    ipcRenderer.on("mrp:backend:status", listener);
    return () => ipcRenderer.removeListener("mrp:backend:status", listener);
  },
  getBackendStatus: (): Promise<string> => ipcRenderer.invoke("mrp:backend:get-status"),
  /** Restart the app (relaunch the process → fresh backend + reloaded UI). */
  relaunch: (): Promise<boolean> => ipcRenderer.invoke("mrp:app:relaunch"),
  /** Automation Mode: live power-save blocker status + a re-sync nudge. */
  automation: {
    status: (): Promise<{
      automationActive: boolean;
      sleepPrevented: boolean;
      preventSleepSetting: boolean;
      blockerId: number | null;
    }> => ipcRenderer.invoke("mrp:automation:status"),
    sync: (): Promise<{
      automationActive: boolean;
      sleepPrevented: boolean;
      preventSleepSetting: boolean;
      blockerId: number | null;
    }> => ipcRenderer.invoke("mrp:automation:sync"),
  },
  /** Profiles: isolated data roots (own DB/logs/settings). Switch + relaunch. */
  profiles: {
    get: (): Promise<{ active: string; profiles: string[] }> =>
      ipcRenderer.invoke("mrp:profiles:get"),
    switch: (name: string): Promise<{ ok: boolean; active: string }> =>
      ipcRenderer.invoke("mrp:profiles:switch", name),
  },
  /** In-app auto-update controls (packaged build only). */
  updater: {
    check: (): Promise<{ version: string | null }> => ipcRenderer.invoke("mrp:update:check"),
    download: (): Promise<boolean> => ipcRenderer.invoke("mrp:update:download"),
    install: (): Promise<boolean> => ipcRenderer.invoke("mrp:update:install"),
    diagnostics: (): Promise<UpdateDiagnostics> => ipcRenderer.invoke("mrp:update:diagnostics"),
    /** The pending automatic-update prompt (seed a late-mounting renderer). */
    getPending: (): Promise<UpdatePrompt | null> => ipcRenderer.invoke("mrp:update:get-pending"),
    /** Read the persisted auto-update preferences. */
    getPrefs: (): Promise<UpdatePreferences> => ipcRenderer.invoke("mrp:update:get-prefs"),
    /** Update the auto-update preferences (returns the merged result). */
    setPrefs: (patch: Partial<UpdatePreferences>): Promise<UpdatePreferences> =>
      ipcRenderer.invoke("mrp:update:set-prefs", patch),
    /** "Update now" — download + install this update automatically. */
    confirm: (): Promise<boolean> => ipcRenderer.invoke("mrp:update:confirm"),
    /** "Later" — skip this version's prompt (auto-update stays on for future ones). */
    defer: (version: string | null): Promise<boolean> =>
      ipcRenderer.invoke("mrp:update:defer", version),
    onEvent(cb: (e: UpdaterEvent) => void): () => void {
      const listener = (_event: IpcRendererEvent, data: UpdaterEvent) => cb(data);
      ipcRenderer.on("mrp:update:event", listener);
      return () => ipcRenderer.removeListener("mrp:update:event", listener);
    },
    /** The seamless-update state machine (UpdateFlow) — drives the overlay. */
    onFlow(cb: (e: UpdateFlowEvent) => void): () => void {
      const listener = (_event: IpcRendererEvent, data: UpdateFlowEvent) => cb(data);
      ipcRenderer.on("mrp:update:flow", listener);
      return () => ipcRenderer.removeListener("mrp:update:flow", listener);
    },
    /** The automatic-update confirmation prompt (version + size + free space). */
    onPrompt(cb: (p: UpdatePrompt) => void): () => void {
      const listener = (_event: IpcRendererEvent, data: UpdatePrompt) => cb(data);
      ipcRenderer.on("mrp:update:prompt", listener);
      return () => ipcRenderer.removeListener("mrp:update:prompt", listener);
    },
  },
  /** Startup-performance instrumentation (measured timings only). */
  perf: {
    /** Renderer marks: "renderer-hydrated" / "first-api-response" (once each). */
    mark(stage: string, ms?: number): void {
      ipcRenderer.send("mrp:perf:mark", stage, ms);
    },
    startup: (): Promise<StartupPerf> => ipcRenderer.invoke("mrp:perf:startup"),
  },
};

export type MrpBridge = typeof bridge;

contextBridge.exposeInMainWorld("mrp", bridge);

/// <reference types="vite/client" />

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

// The typed bridge exposed by the Electron preload script (see desktop/electron/preload.ts).
export interface MrpBridge {
  apiBaseUrl: string;
  platform: string;
  version: string;
  /** True only in the packaged desktop build, where electron-updater is wired. */
  packaged?: boolean;
  /** True only under `npm run dev-app` — gates the banner + Developer Panel. */
  dev?: boolean;
  /** Developer Panel controls (Development Mode only). */
  devtools?: {
    diagnostics: () => Promise<DevDiagnostics>;
    restartBackend: () => Promise<{ ok: boolean; status: string }>;
    reloadRenderer: () => Promise<boolean>;
    openPath: (which: "logs" | "database" | "config") => Promise<string>;
    exportBundle: () => Promise<string>;
  };
  /** Subscribe to navigation requests from the Electron menu; returns an unsubscribe fn. */
  onNavigate?: (cb: (path: string) => void) => () => void;
  /** Subscribe to backend lifecycle status; returns an unsubscribe fn. */
  onBackendStatus?: (cb: (status: string) => void) => () => void;
  /** The current backend status (for seeding on mount). */
  getBackendStatus?: () => Promise<string>;
  /** Restart the app (fresh backend + reloaded UI). Packaged build only. */
  relaunch?: () => Promise<boolean>;
  /** Automation Mode: live power-save blocker status + a re-sync nudge. */
  automation?: {
    status: () => Promise<{
      automationActive: boolean;
      sleepPrevented: boolean;
      preventSleepSetting: boolean;
      blockerId: number | null;
    }>;
    sync: () => Promise<{
      automationActive: boolean;
      sleepPrevented: boolean;
      preventSleepSetting: boolean;
      blockerId: number | null;
    }>;
  };
  /** Profiles: isolated data roots (own DB/logs/settings). Switch + relaunch. */
  profiles?: {
    get: () => Promise<{ active: string; profiles: string[] }>;
    switch: (name: string) => Promise<{ ok: boolean; active: string }>;
  };
  /** In-app auto-update controls (packaged build only). */
  updater?: {
    check: () => Promise<{ version: string | null }>;
    download: () => Promise<boolean>;
    install: () => Promise<boolean>;
    diagnostics: () => Promise<UpdateDiagnostics>;
    getPending: () => Promise<UpdatePrompt | null>;
    getPrefs: () => Promise<UpdatePreferences>;
    setPrefs: (patch: Partial<UpdatePreferences>) => Promise<UpdatePreferences>;
    confirm: () => Promise<boolean>;
    defer: (version: string | null) => Promise<boolean>;
    onEvent: (cb: (e: UpdaterEvent) => void) => () => void;
    onFlow?: (cb: (e: UpdateFlowEvent) => void) => () => void;
    onPrompt?: (cb: (p: UpdatePrompt) => void) => () => void;
  };
  /** Startup-performance instrumentation (measured timings only). */
  perf?: {
    mark: (stage: string, ms?: number) => void;
    startup: () => Promise<StartupPerf>;
  };
}


declare global {
  interface Window {
    mrp?: MrpBridge;
  }

  /** One event from the seamless-update state machine (see update-flow.ts). */
  interface UpdateFlowEvent {
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
  interface StartupPerf {
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
}

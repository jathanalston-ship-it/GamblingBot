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
  } | null;
}

/** The live diagnostics shown in the Developer Panel (Development Mode only). */
export interface DevDiagnostics {
  version: string;
  packaged: boolean;
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
  /** In-app auto-update controls (packaged build only). */
  updater?: {
    check: () => Promise<{ version: string | null }>;
    download: () => Promise<boolean>;
    install: () => Promise<boolean>;
    onEvent: (cb: (e: UpdaterEvent) => void) => () => void;
  };
}

declare global {
  interface Window {
    mrp?: MrpBridge;
  }
}

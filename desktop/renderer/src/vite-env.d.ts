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

// The typed bridge exposed by the Electron preload script (see desktop/electron/preload.ts).
export interface MrpBridge {
  apiBaseUrl: string;
  platform: string;
  version: string;
  /** True only in the packaged desktop build, where electron-updater is wired. */
  packaged?: boolean;
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

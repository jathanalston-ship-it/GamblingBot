/// <reference types="vite/client" />

// The typed bridge exposed by the Electron preload script (see desktop/electron/preload.ts).
export interface MrpBridge {
  apiBaseUrl: string;
  platform: string;
  version: string;
  /** Subscribe to navigation requests from the Electron menu; returns an unsubscribe fn. */
  onNavigate?: (cb: (path: string) => void) => () => void;
}

declare global {
  interface Window {
    mrp?: MrpBridge;
  }
}

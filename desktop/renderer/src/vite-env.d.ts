/// <reference types="vite/client" />

// The typed bridge exposed by the Electron preload script (see desktop/electron/preload.ts).
export interface MrpBridge {
  apiBaseUrl: string;
  platform: string;
  version: string;
}

declare global {
  interface Window {
    mrp?: MrpBridge;
  }
}

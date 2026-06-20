import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

/** Shared "is an app update available?" state, driven by electron-updater events. */
export interface UpdateStatus {
  available: boolean;
  downloaded: boolean;
  version: string | null;
}

const EMPTY: UpdateStatus = { available: false, downloaded: false, version: null };
const Ctx = createContext<UpdateStatus>(EMPTY);

/**
 * Subscribes once (packaged build only) to the auto-updater and exposes whether a
 * newer version is available/downloaded — so the nav and context bar can show a
 * subtle badge without each opening its own subscription. No-op in dev/browser.
 */
export function UpdateStatusProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<UpdateStatus>(EMPTY);

  useEffect(() => {
    const updater = window.mrp?.updater;
    if (!(window.mrp?.packaged && updater)) return;
    const off = updater.onEvent((e) => {
      if (e.kind === "available") {
        setStatus({ available: true, downloaded: false, version: e.payload?.version ?? null });
      } else if (e.kind === "downloaded") {
        setStatus({ available: true, downloaded: true, version: e.payload?.version ?? null });
      } else if (e.kind === "not-available") {
        setStatus(EMPTY);
      }
    });
    void updater.check().catch(() => {
      /* offline / no release yet — leave the badge hidden */
    });
    return off;
  }, []);

  return <Ctx.Provider value={status}>{children}</Ctx.Provider>;
}

export function useUpdateStatus(): UpdateStatus {
  return useContext(Ctx);
}

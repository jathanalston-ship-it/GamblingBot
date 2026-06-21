import { type ReactNode, useEffect, useState } from "react";

type BackendStatus = "starting" | "healthy" | "failed" | "restarting" | "stopped";

/**
 * Gates the app behind the backend lifecycle: shows a loading screen until the
 * backend reports `healthy`, then renders the app. Driven by the Electron main
 * process over the `mrp.onBackendStatus` bridge. In a plain browser (no bridge)
 * it assumes healthy so the app isn't blocked.
 */
export function BackendGate({ children }: { children: ReactNode }) {
  const hasBridge = typeof window.mrp?.onBackendStatus === "function";
  const [status, setStatus] = useState<BackendStatus>(hasBridge ? "starting" : "healthy");

  useEffect(() => {
    if (!hasBridge) return;
    void window.mrp?.getBackendStatus?.().then((s) => setStatus(s as BackendStatus));
    const off = window.mrp?.onBackendStatus?.((s) => setStatus(s as BackendStatus));
    return off;
  }, [hasBridge]);

  if (status === "healthy") return <>{children}</>;
  return <LoadingScreen status={status} />;
}

const COPY: Record<BackendStatus, { title: string; detail: string; tone: string; spin: boolean }> =
  {
    starting: {
      title: "Backend Starting",
      detail: "Bringing up the local engine…",
      tone: "text-slate-300",
      spin: true,
    },
    restarting: {
      title: "Backend Restarting",
      detail: "The engine stopped — restarting it…",
      tone: "text-amber-300",
      spin: true,
    },
    failed: {
      title: "Backend Failed",
      detail: "The engine could not start. Check the dialog, or restart Momentum Lab.",
      tone: "text-bear",
      spin: false,
    },
    healthy: { title: "Backend Healthy", detail: "", tone: "text-bull", spin: false },
    stopped: {
      title: "Backend Stopped",
      detail: "The engine is shutting down…",
      tone: "text-slate-400",
      spin: false,
    },
  };

function LoadingScreen({ status }: { status: BackendStatus }) {
  const c = COPY[status];
  return (
    <div className="flex h-screen w-screen flex-col items-center justify-center gap-4 bg-surface text-center">
      <div className="flex items-center gap-3">
        {c.spin ? (
          <span className="h-5 w-5 animate-spin rounded-full border-2 border-slate-600 border-t-accent" />
        ) : (
          <span className={`h-2.5 w-2.5 rounded-full ${status === "failed" ? "bg-bear" : "bg-slate-500"}`} />
        )}
        <span className={`text-lg font-medium ${c.tone}`}>{c.title}</span>
      </div>
      <p className="max-w-sm text-sm text-slate-500">{c.detail}</p>
      <p className="absolute bottom-6 text-xs text-slate-600">Momentum Lab</p>
    </div>
  );
}

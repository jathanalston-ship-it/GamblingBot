import { useEffect, useRef, useState } from "react";

/**
 * The seamless-update overlay. From the moment "Restart & install" is clicked
 * until the updated app's dashboard is open, this full-screen layer narrates
 * every UpdateFlow state — current step, spinner/progress bar, elapsed time,
 * a step checklist and (after 5 seconds in one state) extra reassurance — so
 * the application can NEVER appear frozen or ignored. A failed flow shows a
 * recovery dialog instead of dying silently.
 */

const OVERLAY_STATES = new Set([
  "preparing-restart",
  "stopping-backend",
  "waiting-for-shutdown",
  "launching-installer",
  "waiting-for-installer",
  "starting-backend",
  "waiting-for-health",
  "opening-desktop",
  "ready",
  "failed",
]);

const STEPS: { state: string; label: string }[] = [
  { state: "preparing-restart", label: "Please wait…" },
  { state: "stopping-backend", label: "Backend shutting down…" },
  { state: "waiting-for-shutdown", label: "Waiting for shutdown…" },
  { state: "launching-installer", label: "Installer launching…" },
  { state: "waiting-for-installer", label: "Waiting for installer…" },
  { state: "starting-backend", label: "Backend starting…" },
  { state: "waiting-for-health", label: "Loading workspace…" },
  { state: "opening-desktop", label: "Opening dashboard…" },
];

const REASSURANCE_AFTER_MS = 5_000;

function stepIndex(state: string): number {
  return STEPS.findIndex((s) => s.state === state);
}

export function UpdateOverlay() {
  const [event, setEvent] = useState<UpdateFlowEvent | null>(null);
  const [inStateMs, setInStateMs] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const enteredAt = useRef<number>(Date.now());

  useEffect(() => {
    const off = window.mrp?.updater?.onFlow?.((e) => {
      setEvent((prev) => {
        if (!prev || prev.state !== e.state) enteredAt.current = Date.now() - e.inStateMs;
        return e;
      });
      setDismissed(false);
    });
    return () => off?.();
  }, []);

  // A local ticker keeps elapsed time + reassurance live between IPC events.
  useEffect(() => {
    if (!event) return;
    const timer = window.setInterval(() => {
      setInStateMs(Date.now() - enteredAt.current);
    }, 500);
    return () => window.clearInterval(timer);
  }, [event]);

  // Auto-fade once the updated app is ready.
  useEffect(() => {
    if (event?.state !== "ready") return;
    const timer = window.setTimeout(() => setDismissed(true), 2_500);
    return () => window.clearTimeout(timer);
  }, [event?.state]);

  if (!event || dismissed || !OVERLAY_STATES.has(event.state)) return null;

  const failed = event.state === "failed";
  const ready = event.state === "ready";
  const current = stepIndex(event.state);
  const reassure = !failed && !ready && inStateMs >= REASSURANCE_AFTER_MS;

  return (
    <div
      data-testid="update-overlay"
      className="fixed inset-0 z-[100] flex items-center justify-center bg-[#0b1220]/95 backdrop-blur-sm transition-opacity duration-500"
    >
      <div className="w-[480px] max-w-[92vw] rounded-xl border border-surface-border bg-surface-raised p-8 shadow-2xl">
        {failed ? (
          <RecoveryDialog event={event} onDismiss={() => setDismissed(true)} />
        ) : (
          <>
            <div className="mb-6 flex items-center gap-4">
              {ready ? (
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-500/20 text-xl text-emerald-400">
                  ✓
                </div>
              ) : (
                <div className="h-10 w-10 animate-spin rounded-full border-[3px] border-surface-border border-t-sky-400" />
              )}
              <div>
                <div className="text-lg font-semibold text-slate-100">
                  {ready ? "Update complete" : "Installing Update…"}
                </div>
                <div className="text-sm text-slate-400">
                  {event.label}
                  {event.detail ? ` — ${event.detail}` : ""}
                </div>
              </div>
            </div>

            {event.progress !== null ? (
              <div className="mb-4 h-2 w-full overflow-hidden rounded bg-surface/70">
                <div
                  className="h-full bg-sky-500 transition-all duration-300"
                  style={{ width: `${Math.round(event.progress * 100)}%` }}
                />
              </div>
            ) : !ready ? (
              <div className="mb-4 h-2 w-full overflow-hidden rounded bg-surface/70">
                <div className="h-full w-1/3 animate-pulse rounded bg-sky-500/70" />
              </div>
            ) : null}

            <ol className="mb-5 space-y-1.5">
              {STEPS.map((step, index) => (
                <li key={step.state} className="flex items-center gap-2 text-sm">
                  <span
                    className={`inline-flex h-4 w-4 items-center justify-center rounded-full text-[10px] ${
                      ready || index < current
                        ? "bg-emerald-500/20 text-emerald-400"
                        : index === current
                          ? "bg-sky-500/20 text-sky-300"
                          : "bg-surface/70 text-slate-600"
                    }`}
                  >
                    {ready || index < current ? "✓" : index === current ? "●" : "○"}
                  </span>
                  <span
                    className={
                      index === current && !ready
                        ? "font-medium text-slate-200"
                        : index < current || ready
                          ? "text-slate-500 line-through decoration-slate-700"
                          : "text-slate-600"
                    }
                  >
                    {step.label}
                  </span>
                </li>
              ))}
            </ol>

            <div className="space-y-1 text-xs text-slate-500">
              <p>
                Safe to leave running — {event.expects || "this finishes on its own"}.
                {" "}Elapsed in this step: {Math.round(inStateMs / 1000)}s.
              </p>
              {reassure ? (
                <p className="text-amber-300/90">
                  Still working — this step is taking a little longer than usual. The
                  installer may be running in the background with the window closed;
                  Momentum Lab will reopen by itself. Nothing is frozen.
                </p>
              ) : null}
              {ready ? <p className="text-emerald-400">Updated successfully.</p> : null}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function RecoveryDialog({
  event,
  onDismiss,
}: {
  event: UpdateFlowEvent;
  onDismiss: () => void;
}) {
  const [retrying, setRetrying] = useState(false);
  return (
    <div data-testid="update-recovery">
      <div className="mb-4 flex items-center gap-4">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-rose-500/20 text-xl text-rose-400">
          !
        </div>
        <div>
          <div className="text-lg font-semibold text-slate-100">Update did not complete</div>
          <div className="text-sm text-slate-400">
            {event.error ?? "The installer did not finish."}
          </div>
        </div>
      </div>
      <p className="mb-5 text-sm text-slate-400">
        Your current version keeps working — nothing was lost. You can retry the update,
        or keep using this version and try again later from Settings → Updates.
      </p>
      <div className="flex gap-2">
        <button
          disabled={retrying}
          onClick={() => {
            setRetrying(true);
            void window.mrp?.updater?.install().catch(() => setRetrying(false));
          }}
          className="rounded bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
        >
          {retrying ? "Retrying…" : "Retry update"}
        </button>
        <button
          onClick={onDismiss}
          className="rounded border border-surface-border px-4 py-2 text-sm text-slate-300 hover:bg-surface/60"
        >
          Continue without updating
        </button>
      </div>
    </div>
  );
}

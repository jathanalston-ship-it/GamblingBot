import { useState } from "react";

import { apiPost } from "../api/client";
import { Card } from "./Card";

interface ResetResult {
  ok: boolean;
  rows_cleared: number;
  cache_files_removed: number;
  jobs_stopped: number;
  demo?: { trades?: number } | null;
}

type Mode = "reset" | "reset-demo";

const CONFIRM_TEXT =
  "This will permanently delete all locally stored Momentum Lab data, including " +
  "scans, watchlists, portfolios, settings, cached results, analytics, logs, and " +
  "demo data.\n\nThis action cannot be undone.";

/** Restart the app (Electron) or reload the page (plain browser). */
function restartApp(): void {
  if (window.mrp?.relaunch) {
    void window.mrp.relaunch();
  } else {
    window.location.reload();
  }
}

const dangerBtn =
  "rounded bg-bear px-4 py-2 text-sm font-semibold text-white hover:bg-bear/90 disabled:opacity-50";
const ghostBtn =
  "rounded border border-surface-border px-4 py-2 text-sm text-slate-300 hover:bg-surface/60 disabled:opacity-50";

/**
 * Development / factory reset. Two hardcoded buttons:
 *   • "Reset Local Data" — wipe everything back to fresh-install.
 *   • "Reset + Load Demo Data" — wipe, then re-seed the demo dataset.
 *
 * Both require an explicit confirmation dialog (no accidental one-click). On
 * success the user is offered a restart (Reset) or the app reloads (Reset+Demo).
 */
export function ResetPanel() {
  const [confirm, setConfirm] = useState<Mode | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ResetResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [restartPrompt, setRestartPrompt] = useState(false);

  const run = async (mode: Mode) => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiPost<ResetResult>("/actions/reset", {
        load_demo: mode === "reset-demo",
        preserve_api_keys: true,
      });
      setResult(res);
      setConfirm(null);
      if (mode === "reset-demo") {
        // Workflow ends by reloading the application to show the fresh demo data.
        setTimeout(() => window.location.reload(), 600);
      } else {
        setRestartPrompt(true);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Developer — Reset">
      <div className="space-y-4">
        <p className="text-sm text-slate-400">
          Reset the local application state for testing. Clears the database, cached scans,
          watchlists, portfolios, analytics, logs and demo data — and returns the app to a
          fresh-install state. The database schema, migration history and your API keys are
          preserved.
        </p>

        <div className="flex flex-wrap items-center gap-3">
          <button onClick={() => setConfirm("reset")} disabled={busy} className={dangerBtn}>
            Reset Local Data
          </button>
          <button onClick={() => setConfirm("reset-demo")} disabled={busy} className={ghostBtn}>
            Reset + Load Demo Data
          </button>
          {busy ? <span className="text-xs text-slate-400">Resetting…</span> : null}
          {error ? <span className="text-xs text-bear">✗ {error}</span> : null}
          {result && !restartPrompt ? (
            <span className="text-xs text-bull">
              ✓ Cleared {result.rows_cleared} rows
              {result.demo ? `, seeded ${result.demo.trades ?? 0} demo trades` : ""}
            </span>
          ) : null}
        </div>
      </div>

      {/* Confirmation dialog — requires an explicit second click. */}
      {confirm ? (
        <Overlay>
          <h3 className="text-base font-semibold text-slate-100">
            {confirm === "reset-demo" ? "Reset and load demo data?" : "Reset all local data?"}
          </h3>
          <p className="mt-3 whitespace-pre-line text-sm text-slate-300">{CONFIRM_TEXT}</p>
          <div className="mt-6 flex justify-end gap-3">
            <button onClick={() => setConfirm(null)} disabled={busy} className={ghostBtn}>
              Cancel
            </button>
            <button onClick={() => void run(confirm)} disabled={busy} className={dangerBtn}>
              {busy ? "Resetting…" : confirm === "reset-demo" ? "Reset & Seed" : "Reset Everything"}
            </button>
          </div>
        </Overlay>
      ) : null}

      {/* Post-reset restart prompt. */}
      {restartPrompt ? (
        <Overlay>
          <h3 className="text-base font-semibold text-slate-100">Reset complete.</h3>
          <p className="mt-3 text-sm text-slate-300">Restart Momentum Lab now?</p>
          <div className="mt-6 flex justify-end gap-3">
            <button onClick={() => setRestartPrompt(false)} className={ghostBtn}>
              Later
            </button>
            <button onClick={restartApp} className={dangerBtn}>
              Restart
            </button>
          </div>
        </Overlay>
      ) : null}
    </Card>
  );
}

function Overlay({ children }: { children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-md rounded-lg border border-surface-border bg-surface-raised p-6 shadow-xl">
        {children}
      </div>
    </div>
  );
}

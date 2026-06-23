import type { Job } from "../api/types";
import { useAction } from "../hooks/useAction";

function summarize(job: Job): string {
  const r = (job.result ?? {}) as Record<string, unknown>;
  switch (job.kind) {
    case "scan": {
      const passed = String(r.symbols_passed ?? r.candidates ?? 0);
      const scanned = String(r.symbols_scanned ?? 0);
      const ms = r.duration_ms != null ? ` · ${Math.round(Number(r.duration_ms))}ms` : "";
      return `${passed}/${scanned} passed${ms}`;
    }
    case "backtest":
      return `${String(r.num_trades ?? 0)} trades · equity ${String(r.final_equity ?? "?")}`;
    case "paper-session":
      return `opened ${String(r.num_opened ?? 0)}`;
    case "refresh-data":
      return `fetched ${String(r.fetched ?? 0)} symbols`;
    case "seed-demo":
      return `loaded ${String(r.trades ?? 0)} trades · ${String(r.scan_results ?? 0)} candidates`;
    default:
      return "done";
  }
}

/**
 * A button that triggers a backend action and shows inline progress + a
 * success/failure result. The page can react to completion via `onDone`.
 */
export function ActionButton({
  label,
  path,
  body,
  onDone,
  variant = "primary",
}: {
  label: string;
  path: string;
  body?: unknown;
  onDone?: (job: Job) => void;
  variant?: "primary" | "ghost";
}) {
  const { job, running, start } = useAction(path, onDone);

  const base =
    variant === "primary"
      ? "bg-accent text-white hover:bg-accent/90"
      : "border border-surface-border text-slate-300 hover:bg-surface/60";

  return (
    <span className="inline-flex items-center gap-2">
      <button
        onClick={() => void start(body)}
        disabled={running}
        className={`rounded px-3 py-1.5 text-sm ${base} disabled:opacity-50`}
      >
        {running ? "Running…" : label}
      </button>
      {job && running ? (
        <span className="text-xs text-slate-400">
          {Math.round((job.progress ?? 0) * 100)}% {job.message}
        </span>
      ) : null}
      {job && job.status === "succeeded" ? (
        <span className="text-xs text-bull">✓ {summarize(job)}</span>
      ) : null}
      {job && job.status === "failed" ? (
        <span className="max-w-xs truncate text-xs text-bear" title={job.error ?? ""}>
          ✗ {job.error}
        </span>
      ) : null}
    </span>
  );
}

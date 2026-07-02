import { useState } from "react";

import { apiDelete } from "../api/client";
import type { ErrorRecord, RecentErrors } from "../api/types";
import { useApi } from "../hooks/useApi";
import { dateTime } from "../lib/format";
import { Card } from "./Card";
import { ErrorBox, Loading } from "./Page";

/**
 * Settings → Diagnostics: the last N unhandled backend exceptions (route, stack
 * trace, request params, timestamp). Turns a blind 500 in any screen into a
 * specific, copy-pasteable failure. Backed by GET /diagnostics/recent-errors.
 */
export function DiagnosticsPanel() {
  const { data, error, loading, reload } = useApi<RecentErrors>("/diagnostics/recent-errors");
  const [busy, setBusy] = useState(false);

  const clear = async () => {
    setBusy(true);
    try {
      await apiDelete("/diagnostics/recent-errors");
      reload();
    } finally {
      setBusy(false);
    }
  };

  const action = (
    <div className="flex items-center gap-2">
      <button
        onClick={reload}
        disabled={loading}
        className="rounded border border-surface-border px-2 py-1 text-xs text-slate-300 hover:bg-surface/60 disabled:opacity-50"
      >
        {loading ? "Refreshing…" : "Refresh"}
      </button>
      <button
        onClick={() => void clear()}
        disabled={busy || (data?.count ?? 0) === 0}
        className="rounded border border-surface-border px-2 py-1 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-40"
      >
        Clear
      </button>
    </div>
  );

  return (
    <Card title="Diagnostics — Recent Backend Errors" action={action}>
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} />
      ) : !data || data.count === 0 ? (
        <p className="text-sm text-slate-500">
          No backend errors recorded. Unhandled 500s appear here automatically (newest first, up to{" "}
          {data?.capacity ?? 50}) with route, stack trace, parameters and timestamp.
        </p>
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-slate-500">
            {data.count} of {data.capacity} captured — newest first.
          </p>
          {data.errors.map((e, i) => (
            <ErrorRow key={`${e.ts}-${i}`} err={e} />
          ))}
        </div>
      )}
    </Card>
  );
}

function ErrorRow({ err }: { err: ErrorRecord }) {
  const [open, setOpen] = useState(false);
  const when = dateTime(err.ts);
  const params = { ...err.path_params, ...err.query_params };
  const hasParams = Object.keys(params).length > 0;

  return (
    <div className="rounded border border-surface-border bg-surface/40">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-start justify-between gap-3 px-3 py-2 text-left"
      >
        <span className="min-w-0">
          <span className="font-mono text-xs text-bear">
            {err.status} {err.exc_type}
          </span>
          <span className="ml-2 break-all text-sm text-slate-200">{err.exc_message}</span>
          <span className="mt-0.5 block font-mono text-xs text-slate-500">
            {err.method} {err.path}
            {err.route ? ` · ${err.route}` : ""}
          </span>
        </span>
        <span className="shrink-0 whitespace-nowrap text-xs text-slate-500">{when}</span>
      </button>
      {open ? (
        <div className="space-y-2 border-t border-surface-border px-3 py-2">
          {hasParams ? (
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500">Parameters</div>
              <table className="mt-1 text-xs">
                <tbody>
                  {Object.entries(params).map(([k, v]) => (
                    <tr key={k}>
                      <td className="pr-3 font-mono text-slate-400">{k}</td>
                      <td className="font-mono text-slate-200">{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <div>
            <div className="text-xs uppercase tracking-wide text-slate-500">Stack trace</div>
            <pre className="mt-1 max-h-72 overflow-auto rounded bg-surface p-3 text-xs leading-relaxed text-slate-300">
              {err.traceback}
            </pre>
          </div>
        </div>
      ) : null}
    </div>
  );
}

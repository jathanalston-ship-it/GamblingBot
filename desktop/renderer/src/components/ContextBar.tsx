import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import type { Regime, Run } from "../api/types";
import { useApi } from "../hooks/useApi";
import { useUpdateStatus } from "../state/updates";
import { useWorkspace } from "../state/workspace";
import { ActionButton } from "./ActionButton";
import { Badge, regimeTone } from "./Badge";

/** The persistent context bar: run selector · live regime · ⌘K · selected symbol · paper/live. */
export function ContextBar({ onOpenPalette }: { onOpenPalette: () => void }) {
  const { runId, setRunId, symbol } = useWorkspace();
  const navigate = useNavigate();
  const update = useUpdateStatus();
  const runs = useApi<Run[]>("/runs");
  const regime = useApi<Regime>("/regimes/latest");

  useEffect(() => {
    if (!runId && runs.data && runs.data.length > 0) setRunId(runs.data[0].run_id);
  }, [runId, runs.data, setRunId]);

  const adx = regime.data ? regime.data["adx"] : null;

  return (
    <header className="flex items-center gap-4 border-b border-surface-border bg-surface-raised px-4 py-2 text-sm">
      <span className="font-semibold tracking-tight text-slate-100">MRP</span>

      <label className="flex items-center gap-1.5 text-slate-400">
        Run
        <select
          value={runId ?? ""}
          onChange={(e) => setRunId(e.target.value || null)}
          className="rounded border border-surface-border bg-surface px-2 py-1 text-slate-200"
        >
          {(runs.data ?? []).length === 0 ? <option value="">—</option> : null}
          {(runs.data ?? []).map((r) => (
            <option key={r.run_id} value={r.run_id}>
              {r.run_id}
            </option>
          ))}
        </select>
      </label>

      <span className="flex items-center gap-2">
        {regime.data ? (
          <Badge tone={regimeTone(regime.data.regime)}>{regime.data.regime}</Badge>
        ) : (
          <span className="text-slate-500">no regime</span>
        )}
        {adx != null ? <span className="text-xs text-slate-500">ADX {String(adx)}</span> : null}
      </span>

      <span className="ml-auto flex items-center gap-2">
        <ActionButton
          label="Load sample data"
          path="/actions/seed-demo"
          variant="ghost"
          onDone={() => window.location.reload()}
        />
        <ActionButton label="Refresh data" path="/actions/refresh-data" variant="ghost" />
        <ActionButton
          label="Paper session"
          path="/actions/paper-session"
          variant="ghost"
          onDone={() => runs.reload()}
        />
      </span>

      {update.available ? (
        <button
          onClick={() => navigate("/updates")}
          title={update.version ? `Version ${update.version}` : "A new version is available"}
          className="flex items-center gap-1.5 rounded-full border border-accent/40 bg-accent/10 px-2.5 py-1 text-xs text-accent hover:bg-accent/20"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
          {update.downloaded ? "Update ready" : "Update available"}
        </button>
      ) : null}

      <button
        onClick={onOpenPalette}
        className="rounded border border-surface-border px-2 py-1 text-xs text-slate-400 hover:text-slate-200"
      >
        ⌘K · search / command
      </button>

      <span className="text-slate-400">
        {symbol ? (
          <>
            focus <b className="text-slate-100">{symbol}</b>
          </>
        ) : (
          <span className="text-slate-500">no symbol</span>
        )}
      </span>

      <span className="flex items-center gap-2 text-xs">
        <span className="text-bull">● PAPER</span>
        <span className="text-slate-600">◌ LIVE 🔒</span>
      </span>
    </header>
  );
}

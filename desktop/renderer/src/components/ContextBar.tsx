import { useNavigate } from "react-router-dom";

import type { PortfolioSnapshot, Regime, Run } from "../api/types";
import { useApi } from "../hooks/useApi";
import { money, pct, signed } from "../lib/format";
import { useUpdateStatus } from "../state/updates";
import { useWorkspace } from "../state/workspace";
import { Badge, regimeTone } from "./Badge";

/** The persistent context bar: run selector · live regime · account · ⌘K · symbol · paper/live. */
export function ContextBar({ onOpenPalette }: { onOpenPalette: () => void }) {
  const { runId, setRunId, symbol } = useWorkspace();
  const navigate = useNavigate();
  const update = useUpdateStatus();
  const runs = useApi<Run[]>("/runs");
  const regime = useApi<Regime>("/regimes/latest");
  const snaps = useApi<PortfolioSnapshot[]>("/portfolio/snapshots?limit=400");

  // NB: do NOT auto-pin runId here. Leaving it null lets every read resolve to the
  // latest *live scan* run on the backend (resolve_active_run_id) — auto-pinning to
  // an arbitrary run (e.g. demo or a paper session) silently emptied or demo-fied
  // the research screens. The dropdown below remains an explicit opt-in override.

  const adx = regime.data ? regime.data["adx"] : null;
  const rv = regime.data ? regime.data["realized_vol"] : null;
  const breadth = regime.data ? regime.data["breadth"] : null;

  const latest =
    snaps.data && snaps.data.length > 0 ? snaps.data[snaps.data.length - 1] : null;
  const dayPnl = latest?.daily_pnl ?? null;

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
          <option value="">latest (auto)</option>
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
        {typeof rv === "number" ? (
          <span className="text-xs text-slate-500">RV {pct(rv, 1)}</span>
        ) : null}
        {typeof breadth === "number" ? (
          <span className="text-xs text-slate-500" title="% of universe above its 200DMA">
            Breadth {pct(breadth, 0)}
          </span>
        ) : null}
      </span>

      <span className="flex items-center gap-4 text-xs">
        <span className="flex items-center gap-1">
          <span className="text-slate-500">Equity</span>
          <span className="tabular-nums text-slate-200">{money(latest?.equity ?? null)}</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="text-slate-500">Day P&L</span>
          {dayPnl == null ? (
            <span className="tabular-nums text-slate-500">—</span>
          ) : (
            <span className={`tabular-nums ${dayPnl >= 0 ? "text-bull" : "text-bear"}`}>
              {signed(dayPnl, 0)}
            </span>
          )}
        </span>
        <span className="flex items-center gap-1">
          <span className="text-slate-500">Heat</span>
          <span className="tabular-nums text-slate-200">
            {latest?.portfolio_heat != null ? pct(latest.portfolio_heat, 1) : "—"}
          </span>
        </span>
      </span>

      {update.available ? (
        <button
          onClick={() => navigate("/updates")}
          title={update.version ? `Version ${update.version}` : "A new version is available"}
          className="ml-auto flex items-center gap-1.5 rounded-full border border-accent/40 bg-accent/10 px-2.5 py-1 text-xs text-accent hover:bg-accent/20"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
          {update.downloaded ? "Update ready" : "Update available"}
        </button>
      ) : null}

      <button
        onClick={onOpenPalette}
        className={`${update.available ? "" : "ml-auto"} rounded border border-surface-border px-2 py-1 text-xs text-slate-400 hover:text-slate-200`}
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

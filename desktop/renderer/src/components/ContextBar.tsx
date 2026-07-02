import { useNavigate } from "react-router-dom";

import type { PortfolioSnapshot, Regime, Run } from "../api/types";
import { useApi } from "../hooks/useApi";
import { money, pct, signed } from "../lib/format";
import { useUpdateStatus } from "../state/updates";
import { useWorkspace } from "../state/workspace";
import { Badge, regimeTone } from "./Badge";

function Divider() {
  return <span className="h-4 w-px bg-surface-border" aria-hidden />;
}

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <span className="flex items-baseline gap-1.5 text-xs">
      <span className="text-slate-500">{label}</span>
      <span className="tabular-nums">{children}</span>
    </span>
  );
}

/** The persistent top bar: brand · market context · account · ⌘K · mode. */
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

  const latest = snaps.data && snaps.data.length > 0 ? snaps.data[snaps.data.length - 1] : null;
  const dayPnl = latest?.daily_pnl ?? null;

  return (
    <header className="flex h-12 items-center gap-3.5 border-b border-surface-border bg-surface-raised/80 px-4 backdrop-blur">
      <span className="flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-accent-soft/20 text-sm font-bold text-accent">
          M
        </span>
        <span className="text-sm font-semibold tracking-tight text-slate-100">Momentum Lab</span>
      </span>

      <Divider />

      <span className="flex items-center gap-3">
        {regime.data ? (
          <Badge tone={regimeTone(regime.data.regime)}>{regime.data.regime}</Badge>
        ) : (
          <span className="text-xs text-slate-600">no regime</span>
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

      <Divider />

      <span className="flex items-center gap-3">
        <Metric label="Equity">
          <span className="text-slate-200">{money(latest?.equity ?? null)}</span>
        </Metric>
        <Metric label="Day">
          {dayPnl == null ? (
            <span className="text-slate-600">—</span>
          ) : (
            <span className={dayPnl >= 0 ? "text-bull" : "text-bear"}>{signed(dayPnl, 0)}</span>
          )}
        </Metric>
        <Metric label="Heat">
          <span className="text-slate-200">
            {latest?.portfolio_heat != null ? pct(latest.portfolio_heat, 1) : "—"}
          </span>
        </Metric>
      </span>

      <span className="ml-auto" />

      {update.available ? (
        <button
          onClick={() => navigate("/updates")}
          title={update.version ? `Version ${update.version}` : "A new version is available"}
          className="flex items-center gap-1.5 rounded-full border border-accent/40 bg-accent/10 px-2.5 py-1 text-xs text-accent hover:bg-accent/20"
        >
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
          {update.downloaded ? "Update ready" : "Update available"}
        </button>
      ) : null}

      <label className="flex items-center gap-1.5 text-xs text-slate-500">
        Run
        <select
          value={runId ?? ""}
          onChange={(e) => setRunId(e.target.value || null)}
          className="field max-w-40 py-0.5 text-xs"
        >
          <option value="">latest (auto)</option>
          {(runs.data ?? []).map((r) => (
            <option key={r.run_id} value={r.run_id}>
              {r.run_id}
            </option>
          ))}
        </select>
      </label>

      {symbol ? (
        <span
          className="rounded-md border border-surface-edge/60 px-2 py-0.5 text-xs font-medium text-slate-300"
          title="focused symbol"
        >
          {symbol}
        </span>
      ) : null}

      <button onClick={onOpenPalette} className="btn-quiet border border-surface-border">
        <span className="text-slate-500">⌘K</span> search
      </button>

      <span
        className="rounded-full border border-bull/30 bg-bull/10 px-2 py-0.5 text-[10px] font-semibold tracking-wide text-bull"
        title="Live execution stays locked until paper results justify it"
      >
        PAPER
      </span>
    </header>
  );
}

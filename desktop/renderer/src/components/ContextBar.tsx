import { useLocation, useNavigate } from "react-router-dom";

import type { Today } from "../api/today";
import type { Run } from "../api/types";
import { useApi } from "../hooks/useApi";
import { money, signed } from "../lib/format";
import { useUpdateStatus } from "../state/updates";
import { useWorkspace } from "../state/workspace";
import { ADVANCED_PATHS } from "./StageRail";

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

/** The persistent top bar: brand · is it OK to buy · account · search. The run
 *  selector is a research tool and only appears on the Advanced screens. */
export function ContextBar({ onOpenPalette }: { onOpenPalette: () => void }) {
  const { runId, setRunId, symbol } = useWorkspace();
  const navigate = useNavigate();
  const location = useLocation();
  const update = useUpdateStatus();
  const today = useApi<Today>("/today", { refreshMs: 30_000 });
  const advanced = ADVANCED_PATHS.some(
    (p) => location.pathname === p || location.pathname.startsWith(`${p}/`),
  );
  const runs = useApi<Run[]>("/runs");

  const market = today.data?.market;
  const account = today.data?.account;
  const gateTone =
    market?.uptrend === true
      ? "border-bull/30 bg-bull/10 text-bull"
      : market?.uptrend === false
        ? "border-bear/40 bg-bear/10 text-bear"
        : "border-surface-edge/60 text-slate-400";
  const gateWord =
    market?.uptrend === true
      ? "Market uptrend · buying allowed"
      : market?.uptrend === false
        ? "Market downtrend · no new buys"
        : "Market trend unknown";

  return (
    <header className="flex h-12 items-center gap-3.5 border-b border-surface-border bg-surface-raised/80 px-4 backdrop-blur">
      <button onClick={() => navigate("/")} className="flex items-center gap-2" title="Today">
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-accent-soft/20 text-sm font-bold text-accent">
          M
        </span>
        <span className="text-sm font-semibold tracking-tight text-slate-100">Momentum Lab</span>
      </button>

      <Divider />

      <span
        className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${gateTone}`}
        title={market?.detail ?? "Run a scan to measure the market trend"}
      >
        {gateWord}
      </span>

      <Divider />

      <span className="flex items-center gap-3.5">
        <Metric label="Account">
          <span className="text-slate-200">{money(account?.equity ?? null)}</span>
        </Metric>
        <Metric label="Open P/L">
          {account == null ? (
            <span className="text-slate-600">—</span>
          ) : (
            <span
              className={
                account.unrealized_pnl > 0
                  ? "text-bull"
                  : account.unrealized_pnl < 0
                    ? "text-bear"
                    : "text-slate-300"
              }
            >
              {signed(account.unrealized_pnl, 0)}
            </span>
          )}
        </Metric>
        <Metric label="Positions">
          <span className="text-slate-200">
            {account ? `${account.open_positions}/${account.max_positions}` : "—"}
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

      {advanced ? (
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
      ) : null}

      {advanced && symbol ? (
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
        title="Paper trading — no real money is ever traded"
      >
        PAPER
      </span>
    </header>
  );
}

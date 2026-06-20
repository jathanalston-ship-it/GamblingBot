import { useEffect, useMemo, useState, type ReactNode } from "react";

import type { ConvictionScore, Trade } from "../api/types";
import { Badge, regimeTone, type Tone } from "../components/Badge";
import { Card } from "../components/Card";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { useApi } from "../hooks/useApi";
import { date, money, num, signed } from "../lib/format";
import { useWorkspace } from "../state/workspace";

/** 6 · Replay — pick a completed trade and inspect how it played out. */
export default function Replay() {
  const { runId, symbol, setSymbol } = useWorkspace();
  const path = `/trades?status=closed&limit=500${runId ? `&run_id=${runId}` : ""}`;
  const { data, error, loading } = useApi<Trade[]>(path);

  const trades = useMemo(() => data ?? [], [data]);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Auto-select: keep the focused symbol if it has a trade, else the first row.
  useEffect(() => {
    if (trades.length === 0) {
      setSelectedId(null);
      return;
    }
    if (trades.some((t) => t.id === selectedId)) return;
    const focused = symbol ? trades.find((t) => t.symbol === symbol) : undefined;
    setSelectedId((focused ?? trades[0]).id ?? null);
  }, [trades, selectedId, symbol]);

  const selected = trades.find((t) => t.id === selectedId) ?? null;

  return (
    <div className="p-5">
      <PageTitle
        title="Replay"
        subtitle="Reconstruct a completed trade — entry, exit, excursions and conviction"
      >
        <span className="text-xs text-slate-500">
          {runId ? `run ${runId} · ` : ""}
          {trades.length} completed
        </span>
      </PageTitle>

      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} />
      ) : trades.length === 0 ? (
        <div className="text-sm text-slate-500">
          No completed trades for this run. Seed the demo dataset (<code>make seed-demo</code>) or
          run a paper session.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[20rem_1fr]">
          <TradeList
            trades={trades}
            selectedId={selectedId}
            onSelect={(t) => {
              setSelectedId(t.id ?? null);
              setSymbol(t.symbol);
            }}
          />
          {selected ? (
            <TradeDetail trade={selected} runId={runId} />
          ) : (
            <div className="text-sm text-slate-500">Select a trade to replay it.</div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Trade list ─────────────────────────────────────────────────────────── */

function TradeList({
  trades,
  selectedId,
  onSelect,
}: {
  trades: Trade[];
  selectedId: number | null;
  onSelect: (t: Trade) => void;
}) {
  return (
    <Card title={`Completed trades · ${trades.length}`}>
      <ul className="-m-1 flex max-h-[70vh] flex-col gap-1 overflow-auto p-1">
        {trades.map((t, i) => {
          const win = (t.net_pnl ?? 0) > 0;
          const active = t.id === selectedId;
          return (
            <li key={t.id ?? i}>
              <button
                onClick={() => onSelect(t)}
                className={`flex w-full items-center justify-between rounded px-3 py-2 text-left text-sm ${
                  active
                    ? "bg-accent/20 text-slate-100 ring-1 ring-accent/40"
                    : "text-slate-300 hover:bg-surface"
                }`}
              >
                <span className="flex flex-col">
                  <span className="font-medium">{t.symbol}</span>
                  <span className="text-xs text-slate-500">{date(t.exit_ts)}</span>
                </span>
                <span className="flex flex-col items-end">
                  <span className={`tabular-nums ${win ? "text-bull" : "text-bear"}`}>
                    {money(t.net_pnl)}
                  </span>
                  <span className="text-xs tabular-nums text-slate-500">
                    {signed(t.r_multiple, 1)}R
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

/* ── Trade detail ───────────────────────────────────────────────────────── */

function TradeDetail({ trade, runId }: { trade: Trade; runId: string | null }) {
  const conviction = useApi<ConvictionScore[]>(
    `/conviction?symbol=${trade.symbol}${runId ? `&run_id=${runId}` : ""}`,
  );
  const c = conviction.data?.[0] ?? null;
  const win = (trade.net_pnl ?? 0) > 0;
  const notional =
    trade.quantity != null && trade.entry_price != null
      ? trade.quantity * trade.entry_price
      : null;

  return (
    <div className="flex flex-col gap-5">
      {/* header */}
      <div className="flex items-baseline gap-3">
        <h2 className="text-lg font-semibold text-slate-100">{trade.symbol}</h2>
        <Badge tone="default">{trade.direction}</Badge>
        {trade.sector ? <span className="text-xs text-slate-500">{trade.sector}</span> : null}
        <span
          className={`ml-auto text-xl font-semibold tabular-nums ${win ? "text-bull" : "text-bear"}`}
        >
          {money(trade.net_pnl)}
        </span>
        <span className={`tabular-nums ${win ? "text-bull" : "text-bear"}`}>
          {signed(trade.r_multiple, 2)}R
        </span>
      </div>

      {/* fields grid */}
      <Card title="Trade detail">
        <div className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3">
          <Field label="Entry" value={money(trade.entry_price)} hint={fmtTs(trade.entry_ts)} />
          <Field label="Exit" value={money(trade.exit_price)} hint={fmtTs(trade.exit_ts)} />
          <Field
            label="Holding Period"
            value={trade.holding_days != null ? `${trade.holding_days}d` : "—"}
            hint={trade.entry_reason ?? undefined}
          />
          <Field
            label="MFE"
            value={`${signed(trade.mfe, 2)}R`}
            valueClass="text-bull"
            hint="max favorable excursion"
          />
          <Field
            label="MAE"
            value={`${signed(trade.mae, 2)}R`}
            valueClass="text-bear"
            hint="max adverse excursion"
          />
          <Field
            label="Market Regime"
            value={
              trade.regime_label ? (
                <Badge tone={regimeTone(trade.regime_label)}>{trade.regime_label}</Badge>
              ) : (
                "—"
              )
            }
          />
          <Field
            label="Conviction"
            value={
              conviction.loading ? (
                "…"
              ) : c ? (
                <span className="flex items-baseline gap-2">
                  <span className="tabular-nums">{num(c.score, 0)}</span>
                  <Badge tone={bandTone(c.band)}>{c.band}</Badge>
                </span>
              ) : (
                "—"
              )
            }
            hint={c ? undefined : "no score recorded"}
          />
          <Field
            label="Position Size"
            value={trade.quantity != null ? `${num(trade.quantity, 0)} sh` : "—"}
            hint={notional != null ? `${money(notional)} notional` : undefined}
          />
          <Field
            label="Exit Reason"
            value={trade.exit_reason ? trade.exit_reason.replace(/_/g, " ") : "—"}
            hint={trade.initial_risk != null ? `risk ${money(trade.initial_risk)}` : undefined}
          />
        </div>
      </Card>

      {/* timeline */}
      <Card title="Timeline">
        <TradeTimeline trade={trade} />
      </Card>
    </div>
  );
}

function Field({
  label,
  value,
  hint,
  valueClass,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  valueClass?: string;
}) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1 text-base font-semibold text-slate-100 ${valueClass ?? ""}`}>
        {value}
      </div>
      {hint ? <div className="mt-0.5 text-xs text-slate-500">{hint}</div> : null}
    </div>
  );
}

/* ── Timeline visualization ─────────────────────────────────────────────── */

/**
 * A compact excursion chart: time runs left (entry) → right (exit); the vertical
 * axis is R-multiple. We shade the favorable band up to MFE and the adverse band
 * down to MAE, then draw the realised path entry(0) → MAE → MFE → exit(R).
 */
function TradeTimeline({ trade }: { trade: Trade }) {
  const W = 720;
  const H = 200;
  const padX = 48;
  const padY = 24;

  const mfe = trade.mfe ?? 0;
  const mae = trade.mae ?? 0;
  const r = trade.r_multiple ?? 0;
  const span = Math.max(1, Math.abs(mfe), Math.abs(mae), Math.abs(r));

  const x0 = padX;
  const x1 = W - padX;
  const xMae = x0 + (x1 - x0) * 0.38;
  const xMfe = x0 + (x1 - x0) * 0.68;
  const yFor = (v: number): number => H / 2 - (v / span) * (H / 2 - padY);

  const yZero = yFor(0);
  const yMfe = yFor(mfe);
  const yMae = yFor(mae);
  const yExit = yFor(r);

  // Realised path: entry → adverse trough → favorable peak → exit.
  const pathD = `M ${x0} ${yZero} L ${xMae} ${yMae} L ${xMfe} ${yMfe} L ${x1} ${yExit}`;

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full min-w-[560px]"
        role="img"
        aria-label="Trade excursion timeline"
      >
        {/* favorable / adverse bands */}
        <rect x={x0} y={yMfe} width={x1 - x0} height={Math.max(0, yZero - yMfe)} className="fill-bull/10" />
        <rect x={x0} y={yZero} width={x1 - x0} height={Math.max(0, yMae - yZero)} className="fill-bear/10" />

        {/* zero (entry) baseline */}
        <line
          x1={x0}
          y1={yZero}
          x2={x1}
          y2={yZero}
          className="stroke-surface-border"
          strokeWidth={1}
        />
        <text x={x0 - 6} y={yZero + 4} textAnchor="end" className="fill-slate-500 text-[10px]">
          0R
        </text>

        {/* MFE / MAE guide lines */}
        <line x1={x0} y1={yMfe} x2={x1} y2={yMfe} className="stroke-bull/40" strokeDasharray="3 3" />
        <text x={x0 - 6} y={yMfe + 4} textAnchor="end" className="fill-bull text-[10px]">
          {signed(mfe, 1)}R
        </text>
        <line x1={x0} y1={yMae} x2={x1} y2={yMae} className="stroke-bear/40" strokeDasharray="3 3" />
        <text x={x0 - 6} y={yMae + 4} textAnchor="end" className="fill-bear text-[10px]">
          {signed(mae, 1)}R
        </text>

        {/* realised path */}
        <path d={pathD} className="fill-none stroke-accent" strokeWidth={2} />

        {/* markers */}
        <Marker x={x0} y={yZero} className="fill-slate-300" label="Entry" sub={date(trade.entry_ts)} />
        <Marker x={xMfe} y={yMfe} className="fill-bull" label="MFE" />
        <Marker x={xMae} y={yMae} className="fill-bear" label="MAE" />
        <Marker
          x={x1}
          y={yExit}
          className={r >= 0 ? "fill-bull" : "fill-bear"}
          label="Exit"
          sub={date(trade.exit_ts)}
          anchor="end"
        />
      </svg>
      <div className="mt-1 flex justify-between px-1 text-xs text-slate-500">
        <span>{fmtTs(trade.entry_ts)}</span>
        <span>{trade.holding_days != null ? `${trade.holding_days} days held` : ""}</span>
        <span>{fmtTs(trade.exit_ts)}</span>
      </div>
    </div>
  );
}

function Marker({
  x,
  y,
  className,
  label,
  sub,
  anchor = "middle",
}: {
  x: number;
  y: number;
  className: string;
  label: string;
  sub?: string;
  anchor?: "start" | "middle" | "end";
}) {
  return (
    <g>
      <circle cx={x} cy={y} r={4} className={className} />
      <text x={x} y={y - 10} textAnchor={anchor} className="fill-slate-300 text-[10px] font-medium">
        {label}
      </text>
      {sub ? (
        <text x={x} y={y + 16} textAnchor={anchor} className="fill-slate-500 text-[9px]">
          {sub}
        </text>
      ) : null}
    </g>
  );
}

/* ── helpers ────────────────────────────────────────────────────────────── */

function fmtTs(ts: string | null): string {
  if (!ts) return "—";
  return ts.replace("T", " ").slice(0, 16);
}

function bandTone(band: string): Tone {
  const b = band.toLowerCase();
  if (b === "extreme" || b === "high") return "bull";
  if (b === "low") return "bear";
  return "neutral";
}

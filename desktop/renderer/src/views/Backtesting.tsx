import { useState } from "react";

import { apiBaseUrl } from "../api/client";
import type { Optimization } from "../api/types";
import { ActionButton } from "../components/ActionButton";
import { Card } from "../components/Card";
import type { Column } from "../components/DataTable";
import { DataTable } from "../components/DataTable";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { useApi } from "../hooks/useApi";
import { num } from "../lib/format";

interface EquityPoint {
  ts: string;
  equity: number;
}

interface BacktestTrade extends Record<string, unknown> {
  symbol: string;
  entry_date: string | null;
  exit_date: string | null;
  pnl: number;
  r_multiple: number;
  holding_days: number;
  exit_reason: string | null;
}

interface BacktestDetail {
  run_id: string;
  equity_curve: EquityPoint[];
  trades: BacktestTrade[];
}

function ParamPills({ value }: { value: unknown }) {
  if (!value || typeof value !== "object") return <span className="text-slate-500">—</span>;
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length === 0) return <span className="text-slate-500">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {entries.map(([key, val]) => (
        <span key={key} className="rounded bg-surface px-1.5 py-0.5 text-xs">
          <span className="text-slate-500">{key}</span> {String(val)}
        </span>
      ))}
    </div>
  );
}

/** Pure-SVG equity line with a subtle baseline — no chart library. */
function EquityCurve({ points }: { points: EquityPoint[] }) {
  if (points.length < 2) {
    return <div className="py-6 text-center text-xs text-slate-500">no equity curve stored</div>;
  }
  const width = 720;
  const height = 200;
  const pad = 10;
  const padL = 56;
  const values = points.map((p) => p.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (i: number) => padL + (i / (points.length - 1)) * (width - padL - pad);
  const y = (v: number) => pad + (1 - (v - min) / span) * (height - pad * 2);
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(p.equity)}`).join(" ");
  const start = points[0];
  const end = points[points.length - 1];
  const up = end.equity >= start.equity;
  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label="equity curve">
        {[0.25, 0.5, 0.75].map((f) => {
          const value = min + span * f;
          return (
            <g key={f}>
              <line x1={padL} x2={width - pad} y1={y(value)} y2={y(value)} stroke="#1f2a3d" strokeWidth={1} />
              <text x={4} y={y(value) + 3} fontSize={9} fill="#64748b">
                {num(value, 0)}
              </text>
            </g>
          );
        })}
        <line x1={padL} x2={width - pad} y1={y(start.equity)} y2={y(start.equity)} stroke="#334155" strokeDasharray="4 4" strokeWidth={1} />
        <path d={path} fill="none" stroke={up ? "#22c55e" : "#ef4444"} strokeWidth={1.6} />
      </svg>
      <div className="mt-1 flex justify-between text-[10px] text-slate-600">
        <span>{start.ts}</span>
        <span>
          {num(start.equity, 0)} → {num(end.equity, 0)}
        </span>
        <span>{end.ts}</span>
      </div>
    </div>
  );
}

const tradeCols: Column<BacktestTrade>[] = [
  { key: "symbol", header: "Symbol" },
  { key: "entry_date", header: "Entry", render: (t) => t.entry_date ?? "—" },
  { key: "exit_date", header: "Exit", render: (t) => t.exit_date ?? "—" },
  {
    key: "r_multiple",
    header: "R",
    align: "right",
    render: (t) => (
      <span className={t.r_multiple >= 0 ? "text-emerald-400" : "text-bear"}>
        {num(t.r_multiple, 2)}
      </span>
    ),
  },
  { key: "pnl", header: "P&L $", align: "right", render: (t) => num(t.pnl, 0) },
  { key: "holding_days", header: "Days", align: "right" },
  { key: "exit_reason", header: "Exit reason", render: (t) => t.exit_reason ?? "—" },
];

/** Opens the run's persisted HTML tearsheet in the system browser. */
function TearsheetButton({ runId }: { runId: string }) {
  const [note, setNote] = useState<string | null>(null);
  const url = `${apiBaseUrl()}/backtests/optimizations/${runId}/tearsheet`;
  const open = async () => {
    try {
      const res = await fetch(url, { method: "GET" });
      if (!res.ok) {
        setNote("no tearsheet on disk for this run (re-run the backtest to generate one)");
        return;
      }
      setNote(null);
      window.open(url); // Electron routes this to the OS default browser
    } catch {
      setNote("tearsheet unavailable — backend unreachable");
    }
  };
  return (
    <span className="flex items-center gap-2">
      <button
        onClick={() => void open()}
        className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-surface"
      >
        Open tearsheet
      </button>
      {note && <span className="text-[11px] text-amber-400">{note}</span>}
    </span>
  );
}

function RunDetail({ runId }: { runId: string }) {
  const { data, error, loading } = useApi<BacktestDetail>(
    `/backtests/optimizations/${runId}/detail`,
  );
  if (loading) return <Loading />;
  if (error) return <ErrorBox message={`no detail for this run: ${error}`} />;
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <TearsheetButton runId={runId} />
      </div>
      <EquityCurve points={data?.equity_curve ?? []} />
      <DataTable
        columns={tradeCols}
        rows={data?.trades ?? []}
        empty="No trades recorded for this run."
      />
    </div>
  );
}

export default function Backtesting() {
  const { data, error, loading, reload } = useApi<Optimization[]>(
    "/backtests/optimizations?limit=200",
  );
  const [selected, setSelected] = useState<string | null>(null);

  const cols: Column<Optimization>[] = [
    {
      key: "run_id",
      header: "Run",
      render: (o) =>
        o["run_id"] ? (
          <button
            className={`underline decoration-dotted ${selected === o["run_id"] ? "text-sky-400" : "text-slate-300"}`}
            onClick={() => setSelected(String(o["run_id"]))}
          >
            {String(o["run_id"])}
          </button>
        ) : (
          <span className="text-slate-500">—</span>
        ),
    },
    { key: "study_name", header: "Study" },
    { key: "objective_value", header: "Objective", align: "right", render: (o) => num(o.objective_value, 4) },
    {
      key: "params",
      header: "Parameters",
      render: (o) => <ParamPills value={o["params"]} />,
    },
  ];

  return (
    <div>
      <PageTitle title="Backtesting" subtitle="Event-driven backtests & optimization results">
        <ActionButton label="Run backtest" path="/actions/backtest" onDone={() => reload()} />
      </PageTitle>
      <div className="space-y-4">
        <Card title="Optimization Results">
          {loading ? (
            <Loading />
          ) : error ? (
            <ErrorBox message={error} />
          ) : (
            <DataTable columns={cols} rows={data ?? []} empty="No optimization runs recorded." />
          )}
        </Card>
        {selected ? (
          <Card title={`Run detail — ${selected}`}>
            <RunDetail runId={selected} />
          </Card>
        ) : (
          <div className="text-xs text-slate-500">
            Select a run above to see its equity curve and trade list.
          </div>
        )}
      </div>
    </div>
  );
}

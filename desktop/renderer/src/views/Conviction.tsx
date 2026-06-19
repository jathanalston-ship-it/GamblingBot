import { Link } from "react-router-dom";
import type { ReactNode } from "react";

import type { ConvictionScore } from "../api/types";
import { ContributionBar } from "../components/ContributionBar";
import { useApi } from "../hooks/useApi";
import { num } from "../lib/format";
import { useWorkspace } from "../state/workspace";

const BAND_CLASS: Record<string, string> = {
  low: "bg-slate-600/30 text-slate-300",
  medium: "bg-accent/20 text-accent",
  high: "bg-indigo-500/20 text-indigo-300",
  extreme: "bg-violet-500/25 text-violet-300",
};

export default function Conviction() {
  const { runId, symbol } = useWorkspace();
  if (!symbol) {
    return (
      <Msg>
        No symbol selected — pick a candidate in{" "}
        <Link className="text-accent" to="/scan">
          Scan
        </Link>
        .
      </Msg>
    );
  }
  return <Body symbol={symbol} runId={runId} />;
}

function Body({ symbol, runId }: { symbol: string; runId: string | null }) {
  const { data, error, loading } = useApi<ConvictionScore[]>(
    `/conviction?symbol=${symbol}${runId ? `&run_id=${runId}` : ""}`,
  );
  const c = data?.[0];

  if (loading) return <Msg>Loading…</Msg>;
  if (error) return <Msg className="text-bear">Failed: {error}</Msg>;
  if (!c) return <Msg>No conviction score recorded for {symbol}.</Msg>;

  const comps = [...(c.breakdown?.components ?? [])].sort((a, b) => b.contribution - a.contribution);
  const maxC = Math.max(1, ...comps.map((x) => x.contribution));

  return (
    <div className="p-4">
      <div className="mb-4 flex items-baseline gap-3">
        <h1 className="text-lg font-semibold text-slate-100">Conviction · {symbol}</h1>
        <span className="text-3xl font-bold tabular-nums text-slate-100">{num(c.score, 0)}</span>
        <span
          className={`rounded px-2 py-0.5 text-xs font-medium uppercase ${
            BAND_CLASS[c.band] ?? "bg-surface-border text-slate-300"
          }`}
        >
          {c.band}
        </span>
        <span className="ml-auto text-xs text-slate-500">
          {c.model_version} · {c.config_hash}
        </span>
      </div>

      <table className="w-full text-sm">
        <thead className="text-xs uppercase tracking-wide text-slate-400">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Input</th>
            <th className="px-3 py-2 text-right font-medium">Norm</th>
            <th className="px-3 py-2 text-right font-medium">Wt</th>
            <th className="px-3 py-2 text-right font-medium">Contrib</th>
            <th className="px-3 py-2 text-left font-medium" />
          </tr>
        </thead>
        <tbody>
          {comps.map((x) => (
            <tr key={x.name} className="border-b border-surface-border/40">
              <td className="px-3 py-1.5 text-slate-200">{x.name.replace(/_/g, " ")}</td>
              <td className="px-3 py-1.5 text-right tabular-nums text-slate-300">
                {num(x.normalized, 2)}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums text-slate-400">
                {num(x.weight, 2)}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums text-slate-100">
                {num(x.contribution, 1)}
              </td>
              <td className="px-3 py-1.5">
                <ContributionBar value={x.contribution} max={maxC} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="mt-4 flex gap-2 text-sm">
        <Link to="/analogs" className="rounded bg-accent/15 px-3 py-1.5 text-accent hover:bg-accent/25">
          4 Review analogs →
        </Link>
        <Link
          to="/backtest"
          className="rounded bg-accent/15 px-3 py-1.5 text-accent hover:bg-accent/25"
        >
          5 Backtest →
        </Link>
      </div>
    </div>
  );
}

function Msg({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={`p-6 text-sm text-slate-500 ${className ?? ""}`}>{children}</div>;
}

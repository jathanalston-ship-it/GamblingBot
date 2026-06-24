import { Link } from "react-router-dom";

import type { Analogs as AnalogsData, Trade } from "../api/types";
import { ProvenancePanel } from "../components/ProvenancePanel";
import { Badge, regimeTone } from "../components/Badge";
import { Histogram } from "../components/charts/Histogram";
import type { Column } from "../components/DataTable";
import { DataTable } from "../components/DataTable";
import { Stat } from "../components/Stat";
import { useApi } from "../hooks/useApi";
import { date, num, pct, signed } from "../lib/format";
import { useWorkspace } from "../state/workspace";

const cols: Column<Trade>[] = [
  { key: "exit_ts", header: "Exit", render: (t) => date(t.exit_ts) },
  { key: "symbol", header: "Sym" },
  {
    key: "r_multiple",
    header: "R",
    align: "right",
    render: (t) => (
      <span className={(t.r_multiple ?? 0) >= 0 ? "text-bull" : "text-bear"}>
        {signed(t.r_multiple)}
      </span>
    ),
  },
  { key: "holding_days", header: "Hold", align: "right", render: (t) => num(t.holding_days, 0) },
  { key: "mfe", header: "MFE", align: "right", render: (t) => signed(t.mfe) },
  { key: "mae", header: "MAE", align: "right", render: (t) => signed(t.mae) },
  { key: "exit_reason", header: "Exit reason", render: (t) => t.exit_reason ?? "—" },
];

export default function Analogs() {
  const { runId, symbol } = useWorkspace();
  if (!symbol) {
    return (
      <div className="p-6 text-sm text-slate-500">
        No symbol selected — pick a candidate in{" "}
        <Link className="text-accent" to="/scan">
          Scan
        </Link>
        .
      </div>
    );
  }
  return <Body symbol={symbol} runId={runId} />;
}

function Body({ symbol, runId }: { symbol: string; runId: string | null }) {
  const { data, error, loading } = useApi<AnalogsData>(
    `/analogs?symbol=${symbol}${runId ? `&run_id=${runId}` : ""}`,
  );

  if (loading) return <div className="p-6 text-sm text-slate-500">Loading…</div>;
  if (error) return <div className="p-6 text-sm text-bear">Failed: {error}</div>;
  if (!data) return null;

  const rMultiples = data.trades.map((t) => t.r_multiple ?? 0);
  const smallSample = data.sample_size < 20;

  return (
    <div className="p-4">
      <ProvenancePanel screen="analogs" />
      <div className="mb-4 flex items-center gap-3">
        <h1 className="text-lg font-semibold text-slate-100">Historical Analogs · {symbol}</h1>
        <span className="flex items-center gap-2 text-xs text-slate-500">
          match
          {data.regime ? <Badge tone={regimeTone(data.regime)}>{data.regime}</Badge> : null}
          {data.sector ? <span className="text-slate-400">{data.sector}</span> : null}
        </span>
        <span className="ml-auto text-sm text-slate-400">n = {data.sample_size}</span>
      </div>

      {data.sample_size === 0 ? (
        <div className="mb-4 rounded-lg border border-surface-border bg-surface-raised p-4 text-sm text-slate-400">
          <span className="font-medium text-slate-300">No comparable trade history yet.</span>{" "}
          Analogs are drawn from your closed trades in this regime + sector — they populate as
          paper/live trades close. This is a true empty state, not demo or stale data.
        </div>
      ) : null}

      <div className="mb-2 grid grid-cols-2 gap-4 md:grid-cols-5">
        <Stat label="Expectancy" value={`${num(data.expectancy_r, 2)} R`} />
        <Stat label="Avg winner" value={`${num(data.avg_winner_r, 2)} R`} />
        <Stat label="Avg loser" value={`${num(data.avg_loser_r, 2)} R`} />
        <Stat label="Sample" value={data.sample_size} />
        <div className="rounded-lg border border-surface-border bg-surface-raised p-4 opacity-70">
          <div className="text-xs uppercase tracking-wide text-slate-500">Win rate</div>
          <div className="mt-1 text-base font-medium text-slate-400">{pct(data.win_rate)}</div>
        </div>
      </div>

      {smallSample ? (
        <div className="mb-4 text-xs text-neutral">
          ⚠ Small sample (n={data.sample_size}) — treat averages as indicative, not reliable.
        </div>
      ) : null}

      <div className="mb-5 rounded-lg border border-surface-border bg-surface-raised p-3">
        <div className="mb-2 text-xs uppercase tracking-wide text-slate-400">
          R-multiple distribution
        </div>
        <Histogram values={rMultiples} />
      </div>

      <DataTable
        columns={cols}
        rows={data.trades}
        empty="No closed analogs for this regime + sector yet."
      />
    </div>
  );
}

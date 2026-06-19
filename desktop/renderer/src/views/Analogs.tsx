import { Link } from "react-router-dom";

import type { Analogs as AnalogsData, Trade } from "../api/types";
import { Badge, regimeTone } from "../components/Badge";
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

  return (
    <div className="p-4">
      <div className="mb-4 flex items-center gap-3">
        <h1 className="text-lg font-semibold text-slate-100">Historical Analogs · {symbol}</h1>
        <span className="flex items-center gap-2 text-xs text-slate-500">
          match
          {data.regime ? <Badge tone={regimeTone(data.regime)}>{data.regime}</Badge> : null}
          {data.sector ? <span className="text-slate-400">{data.sector}</span> : null}
        </span>
        <span className="ml-auto text-sm text-slate-400">n = {data.sample_size}</span>
      </div>

      <div className="mb-5 grid grid-cols-2 gap-4 md:grid-cols-5">
        <Stat label="Expectancy" value={`${num(data.expectancy_r, 2)} R`} />
        <Stat label="Win rate" value={pct(data.win_rate)} />
        <Stat label="Avg winner" value={`${num(data.avg_winner_r, 2)} R`} />
        <Stat label="Avg loser" value={`${num(data.avg_loser_r, 2)} R`} />
        <Stat label="Sample" value={data.sample_size} />
      </div>

      <DataTable
        columns={cols}
        rows={data.trades}
        empty="No closed analogs for this regime + sector yet."
      />
    </div>
  );
}

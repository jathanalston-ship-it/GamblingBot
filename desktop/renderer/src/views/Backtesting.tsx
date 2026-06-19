import type { Optimization } from "../api/types";
import { Card } from "../components/Card";
import type { Column } from "../components/DataTable";
import { DataTable } from "../components/DataTable";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { useApi } from "../hooks/useApi";
import { num } from "../lib/format";

const params = (o: Optimization): string => {
  const p = o["params"];
  return p && typeof p === "object" ? JSON.stringify(p) : "—";
};

const cols: Column<Optimization>[] = [
  { key: "study_name", header: "Study" },
  { key: "objective_value", header: "Objective", align: "right", render: (o) => num(o.objective_value, 4) },
  {
    key: "params",
    header: "Parameters",
    render: (o) => <span className="text-xs text-slate-400">{params(o)}</span>,
  },
];

export default function Backtesting() {
  const { data, error, loading } = useApi<Optimization[]>("/backtests/optimizations?limit=200");
  return (
    <div>
      <PageTitle title="Backtesting" subtitle="Event-driven backtests & optimization results">
        <button
          disabled
          title="Planned: POST /backtests/run (see docs/DESKTOP_APP.md implementation plan)"
          className="cursor-not-allowed rounded bg-accent/30 px-3 py-1.5 text-sm text-slate-300"
        >
          Run backtest
        </button>
      </PageTitle>
      <Card title="Optimization Results">
        {loading ? (
          <Loading />
        ) : error ? (
          <ErrorBox message={error} />
        ) : (
          <DataTable columns={cols} rows={data ?? []} empty="No optimization runs recorded." />
        )}
      </Card>
    </div>
  );
}

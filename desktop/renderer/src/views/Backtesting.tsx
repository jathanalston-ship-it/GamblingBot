import type { Optimization } from "../api/types";
import { ActionButton } from "../components/ActionButton";
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
  const { data, error, loading, reload } = useApi<Optimization[]>(
    "/backtests/optimizations?limit=200",
  );
  return (
    <div>
      <PageTitle title="Backtesting" subtitle="Event-driven backtests & optimization results">
        <ActionButton label="Run backtest" path="/actions/backtest" onDone={() => reload()} />
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

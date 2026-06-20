import type { Optimization } from "../api/types";
import { ActionButton } from "../components/ActionButton";
import { Card } from "../components/Card";
import type { Column } from "../components/DataTable";
import { DataTable } from "../components/DataTable";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { useApi } from "../hooks/useApi";
import { num } from "../lib/format";

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

const cols: Column<Optimization>[] = [
  { key: "study_name", header: "Study" },
  { key: "objective_value", header: "Objective", align: "right", render: (o) => num(o.objective_value, 4) },
  {
    key: "params",
    header: "Parameters",
    render: (o) => <ParamPills value={o["params"]} />,
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

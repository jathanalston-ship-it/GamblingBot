import type { PortfolioSnapshot, RiskMetric } from "../api/types";
import { Card } from "../components/Card";
import type { Column } from "../components/DataTable";
import { DataTable } from "../components/DataTable";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { Stat } from "../components/Stat";
import { useApi } from "../hooks/useApi";
import { date, money } from "../lib/format";

const str = (v: unknown): string => (v == null ? "—" : String(v));

const snapCols: Column<PortfolioSnapshot>[] = [
  { key: "session_date", header: "Date", render: (s) => date(s.session_date) },
  { key: "equity", header: "Equity", align: "right", render: (s) => money(s.equity) },
  { key: "gross_exposure", header: "Gross Exp", align: "right", render: (s) => str(s["gross_exposure"]) },
  { key: "open_positions", header: "Positions", align: "right", render: (s) => str(s["open_positions"]) },
];

const riskCols: Column<RiskMetric>[] = [
  { key: "as_of", header: "Date", render: (m) => date(m.as_of) },
  { key: "scope", header: "Scope" },
  { key: "window", header: "Window", render: (m) => m.window ?? "—" },
  { key: "name", header: "Metric", render: (m) => str(m["name"]) },
  { key: "value", header: "Value", align: "right", render: (m) => str(m["value"]) },
];

export default function Portfolio() {
  const snaps = useApi<PortfolioSnapshot[]>("/portfolio/snapshots?limit=400");
  const risk = useApi<RiskMetric[]>("/risk/metrics?limit=100");
  const latest = snaps.data?.[snaps.data.length - 1];

  return (
    <div>
      <PageTitle title="Portfolio" subtitle="Equity curve, exposure and risk metrics" />
      <div className="space-y-5">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
          <Stat
            label="Equity"
            value={money(latest?.equity ?? null)}
            hint={latest ? date(latest.session_date) : "no snapshot"}
          />
          <Stat label="Snapshots" value={snaps.data?.length ?? 0} />
          <Stat label="Risk Metrics" value={risk.data?.length ?? 0} />
        </div>
        <Card title="Equity Snapshots">
          {snaps.loading ? (
            <Loading />
          ) : snaps.error ? (
            <ErrorBox message={snaps.error} />
          ) : (
            <DataTable columns={snapCols} rows={snaps.data ?? []} empty="No portfolio snapshots." />
          )}
        </Card>
        <Card title="Risk Metrics">
          {risk.loading ? (
            <Loading />
          ) : risk.error ? (
            <ErrorBox message={risk.error} />
          ) : (
            <DataTable columns={riskCols} rows={risk.data ?? []} empty="No risk metrics." />
          )}
        </Card>
      </div>
    </div>
  );
}

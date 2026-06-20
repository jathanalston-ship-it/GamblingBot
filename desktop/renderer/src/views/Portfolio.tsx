import type { PortfolioSnapshot, RiskMetric } from "../api/types";
import { Card } from "../components/Card";
import type { Column } from "../components/DataTable";
import { DataTable } from "../components/DataTable";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { Stat } from "../components/Stat";
import { useApi } from "../hooks/useApi";
import { date, money, num, pct } from "../lib/format";

const nz = (v: unknown): number | null => (typeof v === "number" ? v : null);

const snapCols: Column<PortfolioSnapshot>[] = [
  { key: "session_date", header: "Date", render: (s) => date(s.session_date) },
  { key: "equity", header: "Equity", align: "right", render: (s) => money(s.equity) },
  { key: "realized_pnl", header: "Realized", align: "right", render: (s) => money(nz(s["realized_pnl"])) },
  { key: "num_positions", header: "Positions", align: "right", render: (s) => num(nz(s["num_positions"]), 0) },
  { key: "drawdown", header: "Drawdown", align: "right", render: (s) => pct(nz(s["drawdown"]), 1) },
];

const riskCols: Column<RiskMetric>[] = [
  { key: "as_of", header: "Date", render: (m) => date(m.as_of) },
  { key: "window", header: "Window", render: (m) => m.window ?? "—" },
  { key: "num_trades", header: "Trades", align: "right", render: (m) => num(nz(m["num_trades"]), 0) },
  { key: "win_rate", header: "Win %", align: "right", render: (m) => pct(nz(m["win_rate"]), 0) },
  { key: "profit_factor", header: "Profit Factor", align: "right", render: (m) => num(nz(m["profit_factor"]), 2) },
  { key: "expectancy_r", header: "Expectancy R", align: "right", render: (m) => num(nz(m["expectancy_r"]), 2) },
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

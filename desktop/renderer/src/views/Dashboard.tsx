import type { ReactNode } from "react";

import type { Dashboard as DashboardData, ScanResult, Trade } from "../api/types";
import { Badge, regimeTone } from "../components/Badge";
import { Card } from "../components/Card";
import type { Column } from "../components/DataTable";
import { DataTable } from "../components/DataTable";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { Stat } from "../components/Stat";
import { useApi } from "../hooks/useApi";
import { date, money, num, signed } from "../lib/format";

const scanCols: Column<ScanResult>[] = [
  { key: "rank", header: "#", align: "right", render: (r) => num(r.rank, 0) },
  { key: "symbol", header: "Symbol" },
  { key: "momentum_score", header: "Score", align: "right", render: (r) => num(r.momentum_score, 3) },
  { key: "relative_volume", header: "RVol", align: "right", render: (r) => num(r.relative_volume, 2) },
];

const tradeCols: Column<Trade>[] = [
  { key: "symbol", header: "Symbol" },
  { key: "status", header: "Status" },
  { key: "r_multiple", header: "R", align: "right", render: (t) => signed(t.r_multiple) },
  {
    key: "net_pnl",
    header: "P&L",
    align: "right",
    render: (t) => (
      <span className={(t.net_pnl ?? 0) >= 0 ? "text-bull" : "text-bear"}>{money(t.net_pnl)}</span>
    ),
  },
];

export default function Dashboard() {
  const { data, error, loading } = useApi<DashboardData>("/dashboard");
  if (loading) return <PageWrap>{<Loading />}</PageWrap>;
  if (error) return <PageWrap>{<ErrorBox message={error} />}</PageWrap>;
  if (!data) return null;

  const perf = data.performance.performance;
  return (
    <PageWrap>
      <div className="space-y-5">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <Stat
            label="Market Regime"
            value={
              data.latest_regime ? (
                <Badge tone={regimeTone(data.latest_regime.regime)}>
                  {data.latest_regime.regime}
                </Badge>
              ) : (
                "—"
              )
            }
            hint={data.latest_regime ? date(data.latest_regime.as_of) : "no data"}
          />
          <Stat
            label="Equity"
            value={money(data.latest_snapshot?.equity ?? null)}
            hint={data.latest_snapshot ? date(data.latest_snapshot.session_date) : "no snapshot"}
          />
          <Stat label="Open Trades" value={data.open_trades} />
          <Stat
            label="Total Return"
            value={perf ? `${(perf.total_return * 100).toFixed(1)}%` : "—"}
            hint={`${data.performance.n_trades} closed trades`}
          />
        </div>
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          <Card title="Top Scans">
            <DataTable columns={scanCols} rows={data.top_scans} empty="No scans yet." />
          </Card>
          <Card title="Recent Trades">
            <DataTable columns={tradeCols} rows={data.recent_trades} empty="No trades yet." />
          </Card>
        </div>
      </div>
    </PageWrap>
  );
}

function PageWrap({ children }: { children: ReactNode }) {
  return (
    <div>
      <PageTitle title="Dashboard" subtitle="Latest regime, scans, trades and performance" />
      {children}
    </div>
  );
}

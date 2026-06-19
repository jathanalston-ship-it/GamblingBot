import type { Regime as RegimeRow } from "../api/types";
import { Badge, regimeTone } from "../components/Badge";
import { Card } from "../components/Card";
import type { Column } from "../components/DataTable";
import { DataTable } from "../components/DataTable";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { Stat } from "../components/Stat";
import { useApi } from "../hooks/useApi";
import { date } from "../lib/format";

const str = (v: unknown): string => (v == null ? "—" : String(v));

const cols: Column<RegimeRow>[] = [
  { key: "as_of", header: "Date", render: (r) => date(r.as_of) },
  {
    key: "regime",
    header: "Regime",
    render: (r) => <Badge tone={regimeTone(r.regime)}>{r.regime}</Badge>,
  },
  { key: "trend_state", header: "Trend", render: (r) => str(r["trend_state"]) },
  { key: "volatility_state", header: "Volatility", render: (r) => str(r["volatility_state"]) },
];

export default function Regime() {
  const { data, error, loading } = useApi<RegimeRow[]>("/regimes?limit=120");
  const latest = data?.[0];
  return (
    <div>
      <PageTitle title="Market Regime" subtitle="Bullish / neutral / bearish classification" />
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} />
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
            <Stat
              label="Current Regime"
              value={
                latest ? <Badge tone={regimeTone(latest.regime)}>{latest.regime}</Badge> : "—"
              }
              hint={latest ? date(latest.as_of) : "no data"}
            />
            <Stat label="Trend" value={str(latest?.["trend_state"])} />
            <Stat label="Volatility" value={str(latest?.["volatility_state"])} />
          </div>
          <Card title="History">
            <DataTable columns={cols} rows={data ?? []} empty="No regime classifications yet." />
          </Card>
        </div>
      )}
    </div>
  );
}

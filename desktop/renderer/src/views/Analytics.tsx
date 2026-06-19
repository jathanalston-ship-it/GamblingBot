import type { Performance } from "../api/types";
import { Card } from "../components/Card";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { Stat } from "../components/Stat";
import { useApi } from "../hooks/useApi";

const isPctKey = (k: string): boolean => /(return|cagr|drawdown|volatility|rate)/i.test(k);
const label = (k: string): string => k.replace(/_/g, " ");
const fmt = (k: string, v: number | null): string =>
  v == null ? "—" : isPctKey(k) ? `${(v * 100).toFixed(1)}%` : v.toFixed(2);

export default function Analytics() {
  const { data, error, loading } = useApi<Performance>("/performance");
  return (
    <div>
      <PageTitle title="Analytics" subtitle="Expectancy, profit factor and trend capture" />
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} />
      ) : data ? (
        <div className="space-y-5">
          <Card title={`Trade Statistics · ${data.n_trades} trades`}>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              {Object.entries(data.trade_stats).map(([k, v]) => (
                <Stat key={k} label={label(k)} value={fmt(k, v)} />
              ))}
            </div>
          </Card>
          <Card title="Performance">
            {data.performance ? (
              <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                {Object.entries(data.performance).map(([k, v]) => (
                  <Stat key={k} label={label(k)} value={fmt(k, v)} />
                ))}
              </div>
            ) : (
              <div className="text-sm text-slate-500">
                No equity curve yet — run a backtest to populate performance metrics.
              </div>
            )}
          </Card>
        </div>
      ) : null}
    </div>
  );
}

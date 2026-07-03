import type {
  Attribution,
  AttributionGroup,
  Performance,
  PortfolioSnapshot,
  Trade,
} from "../api/types";
import { Card } from "../components/Card";
import { EquityChart } from "../components/charts/EquityChart";
import { Histogram } from "../components/charts/Histogram";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { Stat } from "../components/Stat";
import { useApi } from "../hooks/useApi";
import { useWorkspace } from "../state/workspace";
import { date, num, pct } from "../lib/format";

const isPctKey = (k: string): boolean => /(return|cagr|drawdown|volatility|rate)/i.test(k);
const label = (k: string): string => k.replace(/_/g, " ");
const fmt = (k: string, v: number | null): string =>
  typeof v !== "number" || !Number.isFinite(v)
    ? "—"
    : isPctKey(k)
      ? pct(v, 1)
      : num(v, 2);

// Stat helper that reads a key from a stats record and formats it.
function statFrom(stats: Record<string, number | null>, key: string): JSX.Element {
  const v = key in stats ? stats[key] : null;
  return <Stat key={key} label={label(key)} value={fmt(key, v ?? null)} />;
}

const EDGE_KEYS = [
  "expectancy_r",
  "profit_factor",
  "avg_winner_r",
  "largest_winner_r",
  "payoff_ratio",
  "trend_capture",
];
const PERF_KEYS = ["total_return", "cagr", "sharpe", "sortino", "max_drawdown", "calmar"];
const BEHAVIOR_KEYS = [
  "win_rate",
  "num_winners",
  "num_losers",
  "avg_loser_r",
  "largest_loser_r",
  "avg_holding_days",
  "median_holding_days",
  "max_holding_days",
  "max_consecutive_wins",
  "max_consecutive_losses",
];

function AttrTable({ title, rows }: { title: string; rows: AttributionGroup[] }) {
  return (
    <div>
      <div className="mb-2 text-xs uppercase tracking-wide text-slate-400">{title}</div>
      {rows.length === 0 ? (
        <div className="py-6 text-center text-sm text-slate-500">No data.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-surface-border text-left text-xs uppercase tracking-wide text-slate-400">
                <th className="px-3 py-2 font-medium">Key</th>
                <th className="px-3 py-2 text-right font-medium">Trades</th>
                <th className="px-3 py-2 text-right font-medium">Expectancy R</th>
                <th className="px-3 py-2 text-right font-medium">Profit Factor</th>
                <th className="px-3 py-2 text-right font-medium">Win %</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((g, i) => (
                <tr key={i} className="border-b border-surface-border/50 hover:bg-surface/40">
                  <td className="px-3 py-2">{g.key}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{num(g.num_trades, 0)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {typeof g.expectancy_r === "number" && Number.isFinite(g.expectancy_r) ? (
                      <span className={g.expectancy_r >= 0 ? "text-bull" : "text-bear"}>
                        {num(g.expectancy_r, 2)}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{num(g.profit_factor, 2)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{pct(g.win_rate, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


interface DollarDriverRow {
  driver: string;
  label: string;
  num_trades: number;
  net_pnl: number;
  share_of_total: number | null;
}

interface DollarAttribution {
  total_net_pnl: number;
  total_fees: number;
  total_opportunity: number;
  total_give_back: number;
  trades_with_opportunity: number;
  sizing_effect: number | null;
  drivers: DollarDriverRow[];
}

const DRIVER_LABEL: Record<string, string> = {
  regime: "Market regime",
  sector: "Sector selection",
  entry_reason: "Scanner / entry",
  exit_reason: "Stop & exit management",
  holding_period: "Holding period",
  instrument: "Instrument",
};

/** Every dollar attributed: identity totals + driver tables ($, not R). */
function DollarAttributionPanel() {
  const { data, error, loading } = useApi<DollarAttribution>("/attribution");
  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!data) return null;
  const drivers = [...new Set(data.drivers.map((d) => d.driver))];
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat
          label="Net P&L"
          value={
            <span className={data.total_net_pnl >= 0 ? "text-bull" : "text-bear"}>
              {num(data.total_net_pnl, 0)}
            </span>
          }
        />
        <Stat
          label="Opportunity found"
          value={num(data.total_opportunity, 0)}
          hint={`across ${data.trades_with_opportunity} trades with MFE`}
        />
        <Stat
          label="Given back"
          value={num(data.total_give_back, 0)}
          hint="opportunity management didn't capture"
        />
        <Stat
          label="Sizing effect"
          value={data.sizing_effect != null ? num(data.sizing_effect, 0) : "—"}
          hint="vs risking the average on every trade"
        />
      </div>
      {drivers.map((driver) => {
        const rows = data.drivers.filter((d) => d.driver === driver);
        return (
          <div key={driver}>
            <div className="mb-2 text-xs uppercase tracking-wide text-slate-400">
              {DRIVER_LABEL[driver] ?? driver}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={i} className="border-b border-surface-border/50">
                      <td className="px-3 py-1.5">{r.label}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-slate-500">
                        {r.num_trades} trades
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums">
                        <span className={r.net_pnl >= 0 ? "text-bull" : "text-bear"}>
                          ${num(r.net_pnl, 0)}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-slate-500">
                        {r.share_of_total != null ? pct(r.share_of_total, 0) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function Analytics() {
  const { runId } = useWorkspace();
  const ampRun = runId ? `&run_id=${runId}` : "";
  const qRun = runId ? `?run_id=${runId}` : "";

  const perf = useApi<Performance>(`/performance${qRun}`);
  const trades = useApi<Trade[]>(`/trades?status=closed&limit=1000${ampRun}`);
  const snaps = useApi<PortfolioSnapshot[]>(`/portfolio/snapshots?limit=400${ampRun}`);
  const attr = useApi<Attribution>(`/performance/attribution${qRun}`);

  const rValues = (trades.data ?? [])
    .map((t) => t.r_multiple)
    .filter((v): v is number => typeof v === "number");

  const snapRows = snaps.data ?? [];
  const points = snapRows.map((s) => ({
    label: date(s.session_date),
    equity: s.equity,
    drawdown: s.drawdown ?? 0,
  }));

  return (
    <div className="p-5">
      <PageTitle title="Analytics" subtitle="Expectancy, profit factor and trend capture" />
      <div className="space-y-5">
        <Card title="Edge">
          {perf.loading ? (
            <Loading />
          ) : perf.error ? (
            <ErrorBox message={perf.error} />
          ) : perf.data ? (
            <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
              {EDGE_KEYS.map((k) => statFrom(perf.data!.trade_stats, k))}
            </div>
          ) : (
            <div className="text-sm text-slate-500">No trade statistics yet.</div>
          )}
        </Card>

        <Card title="R-multiple distribution">
          {trades.loading ? (
            <Loading />
          ) : trades.error ? (
            <ErrorBox message={trades.error} />
          ) : rValues.length > 0 ? (
            <Histogram values={rValues} />
          ) : (
            <div className="py-8 text-center text-sm text-slate-500">No closed trades yet.</div>
          )}
        </Card>

        <Card title="Equity & performance">
          {perf.loading || snaps.loading ? (
            <Loading />
          ) : perf.error ? (
            <ErrorBox message={perf.error} />
          ) : perf.data?.performance ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
                {PERF_KEYS.map((k) => {
                  const p = perf.data!.performance!;
                  const v = k in p ? p[k] : null;
                  return <Stat key={k} label={label(k)} value={fmt(k, v ?? null)} />;
                })}
              </div>
              {points.length >= 2 ? <EquityChart points={points} /> : null}
            </div>
          ) : (
            <div className="text-sm text-slate-500">
              No equity curve yet — run a backtest to populate performance metrics.
            </div>
          )}
        </Card>

        <Card title="Attribution">
          {attr.loading ? (
            <Loading />
          ) : attr.error ? (
            <ErrorBox message={attr.error} />
          ) : attr.data ? (
            <div className="space-y-5">
              <AttrTable title="By sector" rows={attr.data.by_sector} />
              <AttrTable title="By regime" rows={attr.data.by_regime} />
              <AttrTable title="By exit reason" rows={attr.data.by_exit_reason} />
            </div>
          ) : (
            <div className="text-sm text-slate-500">No attribution data.</div>
          )}
        </Card>

        <Card title="Dollar Attribution">
          <DollarAttributionPanel />
        </Card>

        <Card title="Behavior / diagnostics">
          {perf.loading ? (
            <Loading />
          ) : perf.error ? (
            <ErrorBox message={perf.error} />
          ) : perf.data ? (
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              {BEHAVIOR_KEYS.filter((k) => k in perf.data!.trade_stats).map((k) =>
                statFrom(perf.data!.trade_stats, k),
              )}
            </div>
          ) : (
            <div className="text-sm text-slate-500">No diagnostics yet.</div>
          )}
        </Card>
      </div>
    </div>
  );
}

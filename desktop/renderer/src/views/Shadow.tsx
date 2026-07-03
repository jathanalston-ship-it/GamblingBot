import { Card } from "../components/Card";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { Stat } from "../components/Stat";
import { useApi } from "../hooks/useApi";
import { dateTime, money, num } from "../lib/format";

interface ShadowTradeOut {
  id: number;
  symbol: string;
  run_id: string | null;
  entered_at: string | null;
  quantity: number;
  conviction_score: number | null;
  expected_entry: number;
  reference_entry: number;
  entry_slippage_bps: number;
  stop_price: number;
  current_stop: number | null;
  target_price: number | null;
  status: string;
  closed_at: string | null;
  expected_exit: number | null;
  exit_slippage_bps: number | null;
  exit_reason: string | null;
  expected_pnl: number | null;
  expected_r: number | null;
  last_price: number | null;
  evaluations: number;
}

interface ShadowReportOut {
  enabled: boolean;
  generated_at: string;
  window_trading_days: number;
  trading_days_observed: number;
  window_complete: boolean;
  orders_generated: number;
  orders_submitted: number;
  open: number;
  closed: number;
  execution_accuracy: {
    entry_slippage_bps_p50: number | null;
    entry_slippage_bps_p95: number | null;
    exit_slippage_bps_p50: number | null;
    exit_slippage_bps_p95: number | null;
    fills_modeled: number;
  };
  pnl: {
    expected_total: number | null;
    expectancy_r: number | null;
    win_rate: number | null;
    profit_factor: number | null;
    largest_winner: number | null;
    largest_loser: number | null;
  };
  exits: Record<string, number>;
  missed_opportunities: {
    candidates_above_floor: number;
    orders_generated: number;
    left_on_the_table: number;
  };
}

const fmtBps = (v: number | null) => (v === null ? "—" : `${v.toFixed(1)} bps`);
const fmtPct = (v: number | null) => (v === null ? "—" : `${(v * 100).toFixed(1)}%`);

export default function Shadow() {
  const { data, error, loading, reload } = useApi<ShadowReportOut>("/shadow", {
    refreshMs: 60_000,
  });
  const trades = useApi<ShadowTradeOut[]>("/shadow/trades?limit=100", { refreshMs: 60_000 });

  return (
    <div className="p-5">
      <PageTitle
        title="Shadow Mode"
        subtitle="Orders generated, never submitted — the strategy proves itself first"
      >
        <button
          onClick={reload}
          className="rounded border border-surface-border px-3 py-1.5 text-sm text-slate-300 hover:bg-surface/60"
        >
          Refresh
        </button>
      </PageTitle>

      {loading && !data ? <Loading /> : null}
      {error ? <ErrorBox message={error} /> : null}

      {data ? (
        <div className="grid gap-4">
          {!data.enabled ? (
            <div className="rounded border border-amber-400/40 bg-amber-400/10 px-4 py-3 text-sm text-amber-200">
              Shadow mode is OFF — enable it in Settings → Shadow Trading Mode to start the
              60-trading-day proving window.
            </div>
          ) : null}

          <Card title={`Proving Window — day ${Math.min(data.trading_days_observed, data.window_trading_days)} of ${data.window_trading_days} trading days`}>
            <div className="mb-2 flex flex-wrap items-center gap-4 text-sm text-slate-300">
              <span>
                {data.window_complete
                  ? "Window complete — the report below covers the full proving period."
                  : "The window fills only with actual continuous operation."}
              </span>
              <span className="text-xs text-slate-500">
                evaluated {dateTime(data.generated_at)} · orders submitted:{" "}
                <strong className="text-emerald-400">{data.orders_submitted}</strong> (always
                zero — shadow never submits)
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded bg-surface/70">
              <div
                className="h-full bg-sky-500"
                style={{
                  width: `${Math.min(
                    (data.trading_days_observed / data.window_trading_days) * 100,
                    100,
                  )}%`,
                }}
              />
            </div>
          </Card>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Orders generated" value={String(data.orders_generated)} />
            <Stat label="Open / closed" value={`${data.open} / ${data.closed}`} />
            <Stat
              label="Expected P&L"
              value={data.pnl.expected_total === null ? "—" : money(data.pnl.expected_total)}
            />
            <Stat
              label="Expectancy"
              value={data.pnl.expectancy_r === null ? "—" : `${data.pnl.expectancy_r.toFixed(2)}R`}
            />
            <Stat label="Win rate" value={fmtPct(data.pnl.win_rate)} />
            <Stat
              label="Profit factor"
              value={data.pnl.profit_factor === null ? "—" : num(data.pnl.profit_factor)}
            />
            <Stat
              label="Entry slippage p50 / p95"
              value={`${fmtBps(data.execution_accuracy.entry_slippage_bps_p50)} / ${fmtBps(
                data.execution_accuracy.entry_slippage_bps_p95,
              )}`}
            />
            <Stat
              label="Exit slippage p50 / p95"
              value={`${fmtBps(data.execution_accuracy.exit_slippage_bps_p50)} / ${fmtBps(
                data.execution_accuracy.exit_slippage_bps_p95,
              )}`}
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <Card title="Exits">
              {Object.keys(data.exits).length === 0 ? (
                <p className="text-sm text-slate-500">No closed shadow trades yet.</p>
              ) : (
                <div className="space-y-1">
                  {Object.entries(data.exits).map(([reason, count]) => (
                    <div key={reason} className="flex justify-between text-sm">
                      <span className="text-slate-300">{reason}</span>
                      <span className="tabular-nums text-slate-200">{count}</span>
                    </div>
                  ))}
                </div>
              )}
            </Card>
            <Card title="Missed Opportunities">
              <div className="space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-300">Candidates above the conviction floor</span>
                  <span className="tabular-nums text-slate-200">
                    {data.missed_opportunities.candidates_above_floor}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-300">Orders generated</span>
                  <span className="tabular-nums text-slate-200">
                    {data.missed_opportunities.orders_generated}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-300">Left on the table (caps / already held)</span>
                  <span className="tabular-nums text-amber-300">
                    {data.missed_opportunities.left_on_the_table}
                  </span>
                </div>
              </div>
            </Card>
          </div>

          <Card title="Shadow Ledger">
            {trades.error ? <ErrorBox message={trades.error} /> : null}
            {(trades.data ?? []).length === 0 ? (
              <p className="text-sm text-slate-500">
                No shadow trades yet — they appear as scans run with shadow mode enabled.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-surface-border text-xs uppercase tracking-wide text-slate-500">
                      <th className="py-2 pr-3">Symbol</th>
                      <th className="py-2 pr-3">Entered</th>
                      <th className="py-2 pr-3">Qty</th>
                      <th className="py-2 pr-3">Expected entry</th>
                      <th className="py-2 pr-3">Slip (bps)</th>
                      <th className="py-2 pr-3">Stop</th>
                      <th className="py-2 pr-3">Target</th>
                      <th className="py-2 pr-3">Status</th>
                      <th className="py-2 pr-3">Exit</th>
                      <th className="py-2 pr-3">Expected P&L</th>
                      <th className="py-2">R</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(trades.data ?? []).map((t) => (
                      <tr key={t.id} className="border-b border-surface-border/60">
                        <td className="py-1.5 pr-3 font-medium text-slate-200">{t.symbol}</td>
                        <td className="py-1.5 pr-3 text-slate-400">
                          {t.entered_at ? dateTime(t.entered_at) : "—"}
                        </td>
                        <td className="py-1.5 pr-3 tabular-nums">{t.quantity}</td>
                        <td className="py-1.5 pr-3 tabular-nums">{num(t.expected_entry)}</td>
                        <td className="py-1.5 pr-3 tabular-nums">
                          {t.entry_slippage_bps.toFixed(1)}
                        </td>
                        <td className="py-1.5 pr-3 tabular-nums">
                          {num(t.current_stop ?? t.stop_price)}
                        </td>
                        <td className="py-1.5 pr-3 tabular-nums">
                          {t.target_price === null ? "—" : num(t.target_price)}
                        </td>
                        <td className="py-1.5 pr-3">
                          <span
                            className={
                              t.status === "open" ? "text-sky-300" : "text-slate-400"
                            }
                          >
                            {t.status}
                            {t.exit_reason ? ` (${t.exit_reason})` : ""}
                          </span>
                        </td>
                        <td className="py-1.5 pr-3 tabular-nums">
                          {t.expected_exit === null ? "—" : num(t.expected_exit)}
                        </td>
                        <td
                          className={`py-1.5 pr-3 tabular-nums ${
                            (t.expected_pnl ?? 0) > 0
                              ? "text-emerald-400"
                              : (t.expected_pnl ?? 0) < 0
                                ? "text-rose-400"
                                : ""
                          }`}
                        >
                          {t.expected_pnl === null ? "—" : money(t.expected_pnl)}
                        </td>
                        <td className="py-1.5 tabular-nums">
                          {t.expected_r === null ? "—" : `${t.expected_r.toFixed(2)}R`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      ) : null}
    </div>
  );
}

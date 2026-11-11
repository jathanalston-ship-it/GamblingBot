import type { StrategyInfo } from "../api/today";
import type { Today as TodayPayload } from "../api/today";
import { ErrorBox, Loading } from "../components/Page";
import { Empty, Figure, Gain, Panel, Section, fraction, usd } from "../components/simple/common";
import { EvidenceCard } from "../components/simple/EvidenceCard";
import { useApi } from "../hooks/useApi";

interface CurvePoint {
  ts: string;
  equity: number;
}

interface BacktestDetail {
  run_id: string;
  equity_curve: CurvePoint[];
  benchmark_curve?: CurvePoint[];
}

/** Strategy vs SPY, both starting from the same dollar value on the same date. */
function GrowthChart({ runId }: { runId: string }) {
  const { data, error, loading } = useApi<BacktestDetail>(
    `/backtests/optimizations/${runId}/detail`,
  );
  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  const points = data?.equity_curve ?? [];
  const bench = (data?.benchmark_curve ?? []).length >= 2 ? (data?.benchmark_curve ?? []) : null;
  if (points.length < 2) return null;

  const W = 960;
  const H = 300;
  const padL = 64;
  const padR = 150;
  const padT = 14;
  const padB = 26;
  const all = points.map((p) => p.equity).concat(bench ? bench.map((p) => p.equity) : []);
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  const y = (v: number): number => padT + (1 - (v - min) / span) * (H - padT - padB);
  const xOf = (i: number, n: number): number => padL + (i / (n - 1)) * (W - padL - padR);
  const path = (pts: CurvePoint[]): string =>
    pts.map((p, i) => `${i === 0 ? "M" : "L"}${xOf(i, pts.length).toFixed(1)},${y(p.equity).toFixed(1)}`).join(" ");
  const last = points[points.length - 1];
  const benchLast = bench ? bench[bench.length - 1] : null;
  // Keep the two end labels from overlapping.
  let labelY = y(last.equity);
  let benchLabelY = benchLast ? y(benchLast.equity) : 0;
  if (benchLast && Math.abs(labelY - benchLabelY) < 16) {
    if (labelY < benchLabelY) benchLabelY = labelY + 16;
    else labelY = benchLabelY + 16;
  }
  const ticks = [0, 0.5, 1].map((f) => min + span * f);
  const years = [0, 0.25, 0.5, 0.75, 1].map((f) => points[Math.round(f * (points.length - 1))]);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Growth of $100,000">
      {ticks.map((v) => (
        <g key={v}>
          <line x1={padL} x2={W - padR} y1={y(v)} y2={y(v)} stroke="#1c2739" strokeWidth={1} />
          <text x={padL - 8} y={y(v) + 4} fontSize={11} fill="#64748b" textAnchor="end">
            {usd(v)}
          </text>
        </g>
      ))}
      {years.map((p, i) => (
        <text
          key={`${p.ts}-${i}`}
          x={padL + (i / (years.length - 1)) * (W - padL - padR)}
          y={H - 8}
          fontSize={11}
          fill="#64748b"
          textAnchor={i === 0 ? "start" : i === years.length - 1 ? "end" : "middle"}
        >
          {p.ts.slice(0, 4)}
        </text>
      ))}
      {bench ? (
        <path d={path(bench)} fill="none" stroke="#64748b" strokeWidth={1.5} strokeLinejoin="round" />
      ) : null}
      <path d={path(points)} fill="none" stroke="#3b82f6" strokeWidth={2} strokeLinejoin="round" />
      <text x={W - padR + 8} y={labelY + 4} fontSize={12} fill="#e2e8f0" fontWeight={600}>
        These rules {usd(last.equity)}
      </text>
      {benchLast ? (
        <text x={W - padR + 8} y={benchLabelY + 4} fontSize={12} fill="#94a3b8">
          Holding SPY {usd(benchLast.equity)}
        </text>
      ) : null}
    </svg>
  );
}

export default function Results() {
  const strategy = useApi<StrategyInfo>("/strategy");
  const today = useApi<TodayPayload>("/today");

  if ((strategy.loading && !strategy.data) || (today.loading && !today.data)) return <Loading />;
  const failure = strategy.error ?? today.error;
  if (failure && (!strategy.data || !today.data)) {
    return (
      <div className="p-6">
        <ErrorBox message={failure} />
      </div>
    );
  }
  if (!strategy.data || !today.data) return null;
  const s = strategy.data;
  const a = today.data.account;
  const closed = a.closed_trades > 0;
  const reload = (): void => {
    strategy.reload();
    today.reload();
  };

  return (
    <div className="mx-auto max-w-[1180px] px-6 pb-12 pt-5">
      <h1 className="text-[22px] font-semibold tracking-tight text-slate-50">Results</h1>
      <p className="mt-0.5 text-[13px] text-slate-400">
        The evidence for the rules, and how your own paper account is doing.
      </p>

      <Section
        title="The rules, tested on real history"
        hint="The backtest trades exactly what this app trades: same signals, same stops, same exits, with commissions and slippage, buying at the next day's open."
      >
        <EvidenceCard evidence={s.evidence} onChanged={reload} />
        {s.evidence?.run_id ? (
          <Panel className="mt-3">
            <div className="px-5 py-4">
              <div className="mb-2 text-[13px] font-semibold text-slate-100">
                Growth of $100,000
              </div>
              <GrowthChart runId={s.evidence.run_id} />
            </div>
          </Panel>
        ) : null}
      </Section>

      <Section
        title="Your paper account"
        hint="Real results from trades placed in this app. It takes dozens of trades before these numbers mean much."
      >
        {!closed && a.open_positions === 0 ? (
          <Empty>No trades yet. Results will appear here once positions are opened and closed.</Empty>
        ) : (
          <Panel>
            <div className="grid grid-cols-2 divide-x divide-y divide-surface-border/60 sm:grid-cols-3 lg:grid-cols-6 lg:divide-y-0">
              <Figure
                label="Account value"
                value={usd(a.equity)}
                sub={
                  <>
                    <Gain value={a.equity - a.starting_balance} /> since start
                  </>
                }
              />
              <Figure label="Closed profit / loss" value={<Gain value={a.realized_pnl_total} />} />
              <Figure label="Open profit / loss" value={<Gain value={a.unrealized_pnl} />} />
              <Figure
                label="Winning trades"
                value={closed && a.win_rate != null ? fraction(a.win_rate, 0) : "—"}
                sub={closed ? `of ${a.closed_trades} closed` : "no closed trades yet"}
              />
              <Figure
                label="Avg winner / loser"
                value={
                  closed && a.avg_winner != null && a.avg_loser != null
                    ? `${usd(a.avg_winner)} / ${usd(a.avg_loser)}`
                    : "—"
                }
              />
              <Figure
                label="$ won per $ lost"
                value={
                  closed && a.profit_factor != null && Number.isFinite(a.profit_factor)
                    ? a.profit_factor.toFixed(2)
                    : "—"
                }
              />
            </div>
          </Panel>
        )}
      </Section>

      <Section title="The four rules" hint={s.market.headline + "."}>
        <div className="grid gap-3 md:grid-cols-2">
          {s.rules.map((rule, i) => (
            <Panel key={rule.title}>
              <div className="px-5 py-4">
                <div className="text-[13px] font-semibold text-slate-100">
                  {i + 1}. {rule.title}
                </div>
                <p className="mt-1 text-[13px] leading-relaxed text-slate-400">{rule.text}</p>
              </div>
            </Panel>
          ))}
        </div>
      </Section>

      <Section title="What to expect">
        <Panel>
          <ul className="list-disc space-y-1.5 px-9 py-4 text-[13px] leading-relaxed text-slate-400">
            <li>
              Roughly two out of three trades lose a little. That is the design: losses are cut at
              the stop, and a few winners held for months pay for all of them.
            </li>
            <li>
              In a strong, steady bull market these rules usually trail simply holding the index.
              Their job is to keep most of the gain while avoiding the worst of a bear market — in
              the 2008 backtest year these rules lost about 17% while the S&amp;P 500 lost 37%.
            </li>
            <li>
              When the market is below its 200-day average the app stops buying. Weeks with nothing
              to do are normal.
            </li>
            <li>
              This is paper trading. Nothing here is a promise of future profit or investment
              advice, and real fills, taxes and your own discipline will change the outcome.
            </li>
          </ul>
        </Panel>
      </Section>
    </div>
  );
}

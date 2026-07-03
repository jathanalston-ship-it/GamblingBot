import { useNavigate } from "react-router-dom";

import type { CommandCenter as CC, WatchlistEntry } from "../api/types";
import { Badge, regimeTone } from "../components/Badge";
import { Card } from "../components/Card";
import { Freshness } from "../components/Freshness";
import { LiveClock } from "../components/LiveClock";
import { AutomationStatus } from "../components/AutomationStatus";
import { LivePulse } from "../components/LivePulse";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { Stat } from "../components/Stat";
import { useApi } from "../hooks/useApi";
import { date, dateTime, money, num, pct, signed } from "../lib/format";
import { useWorkspace } from "../state/workspace";

export default function CommandCenter() {
  const { runId, setSymbol } = useWorkspace();
  const navigate = useNavigate();
  const { data, error, loading, updatedAt } = useApi<CC>(
    `/command-center${runId ? `?run_id=${runId}` : ""}`,
    { refreshMs: 30_000 }, // auto-refresh every 30s; keeps showing data while polling
  );

  const go = (symbol: string, to: string): void => {
    setSymbol(symbol);
    navigate(to);
  };

  if (loading && !data) return <Loading />; // only block on the first load
  if (error && !data) return <ErrorBox message={error} />;
  if (!data) return null;

  const perf = data.performance;
  const rv = data.regime ? data.regime["realized_vol"] : null;
  const adx = data.regime ? data.regime["adx"] : null;

  return (
    <div className="space-y-5 p-5">
      <PageTitle
        title="Market Command Center"
        subtitle={
          data.updated_at
            ? `updated ${dateTime(data.updated_at)}${data.as_of ? ` · data through ${date(data.as_of)}` : ""}`
            : data.as_of
              ? `data through ${date(data.as_of)}`
              : "the day at a glance"
        }
      >
        <div className="flex items-center gap-3">
          {error ? <span className="text-xs text-bear">refresh failed</span> : null}
          <LiveClock />
          <Freshness updatedAt={updatedAt} />
        </div>
      </PageTitle>

      {/* top stats */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <div className="rounded-card border border-surface-border bg-surface-raised px-4 py-3 shadow-card">
          <div className="overline">Market Regime</div>
          <div className="mt-1.5 flex items-center gap-2">
            {data.regime ? (
              <Badge tone={regimeTone(data.regime.regime)}>{data.regime.regime}</Badge>
            ) : (
              <span className="text-sm text-slate-500">no regime</span>
            )}
          </div>
          <div className="mt-1 text-[11px] text-slate-500">
            {adx != null ? `ADX ${num(Number(adx), 0)}` : ""}
            {rv != null ? ` · RV ${pct(Number(rv), 0)}` : ""}
          </div>
        </div>
        <Stat
          label="Portfolio Heat"
          value={data.portfolio_heat != null ? pct(data.portfolio_heat, 1) : "—"}
          hint={data.equity != null ? `equity ${money(data.equity)}` : undefined}
        />
        <Stat
          label="Daily P&L"
          value={
            data.daily_pnl == null ? (
              "—"
            ) : (
              <span className={data.daily_pnl >= 0 ? "text-bull" : "text-bear"}>
                {signed(data.daily_pnl, 0)}
              </span>
            )
          }
        />
        <Stat
          label="Recent Performance"
          value={perf.expectancy_r != null ? `${num(perf.expectancy_r, 2)}R` : "—"}
          hint={`${perf.n_trades} trades · PF ${perf.profit_factor != null ? num(perf.profit_factor, 2) : "—"} · win ${perf.win_rate != null ? pct(perf.win_rate, 0) : "—"}`}
        />
      </div>

      {/* highlights */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card title="Highest Conviction">
          {data.highest_conviction ? (
            <button
              onClick={() => go(data.highest_conviction!.symbol, "/conviction")}
              className="group flex w-full items-baseline gap-3 text-left"
            >
              <span className="text-lg font-semibold text-slate-100">
                {data.highest_conviction.symbol}
              </span>
              <span className="text-2xl font-bold tabular-nums text-slate-100">
                {num(data.highest_conviction.score, 0)}
              </span>
              <span className="text-xs uppercase text-slate-400">
                {data.highest_conviction.band}
              </span>
              <span className="ml-auto text-xs text-slate-600 transition-colors group-hover:text-accent">
                conviction →
              </span>
            </button>
          ) : (
            <Empty />
          )}
        </Card>
        <Card title="Best Risk / Reward">
          {data.best_reward_risk ? (
            <button
              onClick={() => go(data.best_reward_risk!.symbol, "/tradeplan")}
              className="group flex w-full items-baseline gap-3 text-left"
            >
              <span className="text-lg font-semibold text-slate-100">
                {data.best_reward_risk.symbol}
              </span>
              <span className="text-2xl font-bold tabular-nums text-bull">
                {num(data.best_reward_risk.reward_risk, 2)}x
              </span>
              <span className="text-xs text-slate-400">
                {data.best_reward_risk.horizon_label}
              </span>
              <span className="ml-auto text-xs text-slate-600 transition-colors group-hover:text-accent">
                plan →
              </span>
            </button>
          ) : (
            <Empty />
          )}
        </Card>
        <Card title="Most Attractive Sector">
          {data.top_sector ? (
            <div className="flex items-baseline gap-3">
              <span className="text-lg font-semibold text-slate-100">{data.top_sector.sector}</span>
              <span className="tabular-nums text-slate-300">
                {num(data.top_sector.avg_conviction, 0)} avg
              </span>
              <span className="text-xs text-slate-500">{data.top_sector.count} names</span>
            </div>
          ) : (
            <Empty />
          )}
        </Card>
      </div>

      {/* opportunities */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <OppCard title="Top 5 — Today" entries={data.daily} onPick={go} />
        <OppCard title="Top 5 — This Week" entries={data.weekly} onPick={go} />
        <OppCard title="Top 5 — This Month" entries={data.monthly} onPick={go} />
      </div>

      {/* live pulse: daemon, movers, alerts, activity, performance */}
      <LivePulse />

      <AutomationStatus />

      {/* changes + triggered */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Watchlist Changes (Today)">
          {!data.watchlist_changes ? (
            <div className="text-sm text-slate-500">
              Generate watchlists on two dates to see changes.
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <div className="mb-1 text-xs uppercase tracking-wide text-bull">
                  Entered ({data.watchlist_changes.added.length})
                </div>
                <SymList symbols={data.watchlist_changes.added.map((e) => e.symbol)} tone="bull" />
              </div>
              <div>
                <div className="mb-1 text-xs uppercase tracking-wide text-bear">
                  Dropped ({data.watchlist_changes.removed.length})
                </div>
                <SymList symbols={data.watchlist_changes.removed.map((e) => e.symbol)} tone="bear" />
              </div>
            </div>
          )}
        </Card>

        <Card title="Recently Triggered Setups">
          {data.recent_triggered.length === 0 ? (
            <Empty text="No triggered setups." />
          ) : (
            <ul className="flex flex-col gap-1 text-sm">
              {data.recent_triggered.map((t) => (
                <li
                  key={t.id}
                  onClick={() => go(t.symbol, "/lifecycle")}
                  className="flex cursor-pointer items-center justify-between gap-2 border-b border-surface-border/40 py-1 hover:bg-surface/40"
                >
                  <span className="font-medium text-slate-200">{t.symbol}</span>
                  <span className="flex items-center gap-2">
                    <Badge tone="neutral">{t.state}</Badge>
                    <span className="text-xs text-slate-500">{date(t.state_since)}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function OppCard({
  title,
  entries,
  onPick,
}: {
  title: string;
  entries: WatchlistEntry[];
  onPick: (symbol: string, to: string) => void;
}) {
  return (
    <Card title={title}>
      {entries.length === 0 ? (
        <Empty text="No watchlist yet." />
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-slate-600">
              <th className="pb-1 text-left font-semibold">#</th>
              <th className="pb-1 text-left font-semibold">Sym</th>
              <th className="pb-1 text-right font-semibold">Conv</th>
              <th className="pb-1 text-right font-semibold">R:R</th>
              <th className="pb-1 pl-2 text-left font-semibold">Risk</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {entries.map((e) => (
              <tr
                key={e.id}
                onClick={() => onPick(e.symbol, "/tradeplan")}
                className="cursor-pointer border-b border-surface-border/40 transition-colors last:border-0 hover:bg-surface-border/20"
                title="open trade plan"
              >
                <td className="py-1.5 text-slate-500">{e.rank}</td>
                <td className="py-1.5 font-medium text-slate-100">{e.symbol}</td>
                <td className="py-1.5 text-right text-slate-300">{num(e.conviction, 0)}</td>
                <td className="py-1.5 text-right">
                  <span className={(e.reward_risk ?? 0) >= 1 ? "text-bull" : "text-slate-400"}>
                    {e.reward_risk != null ? `${num(e.reward_risk, 2)}x` : "—"}
                  </span>
                </td>
                <td className="py-1.5 pl-2 text-xs text-slate-500">{e.risk_rating}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function SymList({ symbols, tone }: { symbols: string[]; tone: "bull" | "bear" }) {
  if (symbols.length === 0) return <span className="text-slate-500">—</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {symbols.map((s) => (
        <span
          key={s}
          className={`rounded px-1.5 py-0.5 text-xs ${tone === "bull" ? "bg-bull/15 text-bull" : "bg-bear/15 text-bear"}`}
        >
          {s}
        </span>
      ))}
    </div>
  );
}

function Empty({ text = "—" }: { text?: string }) {
  return <div className="text-sm text-slate-500">{text}</div>;
}

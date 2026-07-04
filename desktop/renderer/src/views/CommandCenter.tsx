import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiPost } from "../api/client";
import { LiveClock } from "../components/LiveClock";
import { PlanModal, PlanSearch } from "../components/terminal/PlanModal";
import { TradeCard, type TrackedTradeRow } from "../components/terminal/TradeCard";
import { useApi } from "../hooks/useApi";
import { countdown, dateTime, fmtTime, money, num, signed } from "../lib/format";

/**
 * The Auto Pilot Trading Command Center — the default landing page, built to
 * answer four questions within three seconds: what is the market doing, what
 * is the bot doing, what is my money doing, do I need to intervene.
 *
 * Every value on this screen is served by a live backend aggregate
 * (/command-center/hud, /command-center/autopilot, /trade-lifecycle,
 * /alerts, /activity, /audit) — nothing is fabricated in the renderer;
 * unknown values render as "—".
 */

/* ------------------------------------------------------------------ */
/* Backend shapes (mirrors hud_service / autopilot_service payloads)   */
/* ------------------------------------------------------------------ */

interface HealthLight {
  status: "green" | "yellow" | "red";
  detail: string;
}

interface Hud {
  clock: {
    state: string;
    market_time: string;
    market_tz: string;
    next_market_open: string;
    next_market_close: string;
    seconds_to_market_open: number;
    seconds_to_market_close: number;
    closed_reason: string | null;
    early_close_today: boolean;
  };
  health: Record<string, HealthLight>;
  timestamps: {
    latest_bar: string | null;
    latest_scan: string | null;
    latest_portfolio_update: string | null;
  };
  account: {
    starting_balance: number;
    equity: number;
    cash: number;
    buying_power: number;
    today_realized_pnl: number;
    unrealized_pnl: number;
    realized_pnl_total: number;
    open_positions: number;
    closed_today: number;
    win_rate: number | null;
    avg_winner: number | null;
    avg_loser: number | null;
    profit_factor: number | null;
    expectancy_r: number | null;
    largest_winner: number | null;
    largest_loser: number | null;
    max_drawdown: number | null;
    exposure: number;
    exposure_pct: number | null;
    risk_used: number;
    max_risk_allowed: number | null;
    portfolio_heat_pct: number | null;
    heat_cap_pct: number;
  };
  market: {
    regime: string | null;
    regime_score: number | null;
    confidence: number | null;
    breadth_pct: number | null;
    posture: string | null;
    as_of: string | null;
    indexes: { symbol: string; last: number; change_pct: number | null; as_of: string }[];
    spy_realized_vol_pct: number | null;
  };
  generated_at: string;
}

interface BotStatus {
  state: string;
  state_label: string;
  enabled: boolean;
  activity: string;
  market_state: string;
  open_positions: number;
  managed_positions: number;
  manual_positions: number;
  last_scan_at: string | null;
  last_error: string | null;
  last_cycle: {
    entered: number | null;
    managed: number | null;
    closed: number | null;
    candidates: number | null;
  } | null;
  last_completed_action: { at: string; message: string } | null;
  next_action: { label: string; seconds: number | null; at: string | null };
}

interface AlertRow {
  id: number;
  severity: string;
  kind: string;
  symbol: string | null;
  title: string;
  description: string | null;
  ts: string | null;
}

interface ActivityRow {
  id: number;
  category: string;
  symbol: string | null;
  text: string;
  ts: string | null;
}

interface AuditRow {
  id: number;
  event_type: string;
  symbol: string | null;
  summary: string | null;
  ts: string | null;
}

/* ------------------------------------------------------------------ */
/* Tones                                                               */
/* ------------------------------------------------------------------ */

const LIGHT_DOT: Record<string, string> = {
  green: "bg-emerald-400",
  yellow: "bg-amber-400",
  red: "bg-rose-500",
};

const MARKET_CHIP: Record<string, string> = {
  premarket: "bg-sky-500/15 text-sky-300",
  regular: "bg-emerald-500/15 text-emerald-300",
  after_hours: "bg-indigo-500/15 text-indigo-300",
  closed: "bg-slate-600/20 text-slate-400",
};

const MARKET_LABEL: Record<string, string> = {
  premarket: "PREMARKET",
  regular: "MARKET OPEN",
  after_hours: "AFTER HOURS",
  closed: "CLOSED",
};

function marketLabel(clock: Hud["clock"] | undefined): string {
  if (!clock) return "CLOSED";
  if (clock.state === "closed") {
    if (clock.closed_reason === "weekend") return "WEEKEND";
    if (clock.closed_reason === "holiday") return "HOLIDAY";
  }
  return MARKET_LABEL[clock.state] ?? clock.state.toUpperCase();
}

const BOT_TONE: Record<string, string> = {
  RUNNING: "bg-emerald-500/15 text-emerald-300 border-emerald-500/50",
  MANAGING: "bg-emerald-500/15 text-emerald-300 border-emerald-500/50",
  ENTERING: "bg-emerald-500/15 text-emerald-300 border-emerald-500/50",
  EXITING: "bg-amber-400/15 text-amber-200 border-amber-400/50",
  SCANNING: "bg-sky-500/15 text-sky-300 border-sky-500/50",
  WAITING: "bg-slate-600/20 text-slate-300 border-slate-500/50",
  IDLE: "bg-slate-600/20 text-slate-300 border-slate-500/50",
  PAUSED: "bg-amber-400/15 text-amber-200 border-amber-400/50",
  STOPPED: "bg-rose-500/15 text-rose-300 border-rose-500/50",
};

const POSTURE: Record<string, { label: string; tone: string }> = {
  risk_on: { label: "RISK-ON", tone: "text-emerald-400" },
  neutral: { label: "NEUTRAL", tone: "text-slate-300" },
  risk_off: { label: "RISK-OFF", tone: "text-rose-400" },
};

const SEVERITY_TONE: Record<string, string> = {
  critical: "border-rose-500/50 bg-rose-500/10 text-rose-300",
  warning: "border-amber-400/50 bg-amber-400/10 text-amber-200",
  info: "border-surface-border bg-surface/40 text-slate-400",
};

/* ------------------------------------------------------------------ */
/* View                                                                */
/* ------------------------------------------------------------------ */

export default function CommandCenter() {
  const hud = useApi<Hud>("/command-center/hud", { refreshMs: 15_000 });
  const bot = useApi<BotStatus>("/command-center/autopilot", { refreshMs: 10_000 });
  const trades = useApi<TrackedTradeRow[]>("/trade-lifecycle?status=open", { refreshMs: 15_000 });
  const alerts = useApi<AlertRow[]>("/alerts?limit=14", { refreshMs: 20_000 });
  const activity = useApi<ActivityRow[]>("/activity?limit=25", { refreshMs: 20_000 });
  const audit = useApi<AuditRow[]>("/audit?limit=25", { refreshMs: 30_000 });

  const open = trades.data ?? [];
  const positions = open.filter((t) => t.journal_trade_id != null);
  const watched = open.filter((t) => t.journal_trade_id == null);

  return (
    <div className="space-y-4 p-4">
      <TopStatusBar hud={hud.data} error={hud.error} />
      <AutopilotHero bot={bot.data} onChanged={bot.reload} />
      {hud.data ? <AccountSummary account={hud.data.account} /> : <PanelSkeleton rows={2} />}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <section>
            <SectionTitle
              title="Active Trade Manager"
              hint={`${positions.length} position${positions.length === 1 ? "" : "s"} · every override is logged and the bot adapts`}
            />
            {positions.length === 0 ? (
              <EmptyPanel text="No open positions. The bot enters when Auto Pilot is ON and a setup qualifies — or take a trade from a plan." />
            ) : (
              <div className="grid grid-cols-1 gap-3 2xl:grid-cols-2">
                {positions.map((t) => (
                  <TradeCard key={t.trade_uid} trade={t} onChanged={trades.reload} />
                ))}
              </div>
            )}
          </section>

          <ManagedWatchlist watched={watched} onChanged={trades.reload} />
        </div>

        <div className="space-y-4">
          {hud.data ? <MarketPanel market={hud.data.market} /> : <PanelSkeleton rows={4} />}
          <AlertCenter alerts={alerts.data ?? []} />
          <MissionLog activity={activity.data ?? []} audit={audit.data ?? []} />
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Top status bar — date/time, market status, countdown, freshness,    */
/* five health lights                                                  */
/* ------------------------------------------------------------------ */

function TopStatusBar({ hud, error }: { hud: Hud | null; error: string | null }) {
  const clock = hud?.clock;
  const state = clock?.state ?? "closed";
  const nextIsOpen = state === "closed" || state === "premarket" || state === "after_hours";
  const seconds = clock
    ? nextIsOpen
      ? clock.seconds_to_market_open
      : clock.seconds_to_market_close
    : null;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-surface-border bg-surface-raised px-4 py-2.5 shadow-card">
      <LiveClock />
      <span
        className={`rounded px-2.5 py-1 text-xs font-bold tracking-wider ${MARKET_CHIP[state] ?? MARKET_CHIP.closed}`}
      >
        {marketLabel(clock)}
      </span>
      {clock?.early_close_today ? (
        <span className="rounded bg-amber-400/15 px-2 py-0.5 text-[10px] font-bold tracking-wider text-amber-300">
          EARLY CLOSE 1PM ET
        </span>
      ) : null}
      <span className="text-xs tabular-nums text-slate-400">
        {nextIsOpen ? "opens in" : "closes in"}{" "}
        <span className="font-medium text-slate-200">{countdown(seconds)}</span>
      </span>

      <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1">
        <FreshnessChip label="data" iso={hud?.timestamps.latest_bar ?? null} />
        <FreshnessChip label="scan" iso={hud?.timestamps.latest_scan ?? null} />
        <FreshnessChip label="portfolio" iso={hud?.timestamps.latest_portfolio_update ?? null} />
        <div className="flex items-center gap-2 border-l border-surface-border pl-4">
          {(["backend", "scheduler", "automation", "broker", "data_provider"] as const).map(
            (key) => {
              const light = hud?.health[key];
              return (
                <span
                  key={key}
                  title={`${key.replace("_", " ")}: ${light?.detail ?? "loading"}`}
                  className="flex items-center gap-1"
                >
                  <span
                    className={`h-2 w-2 rounded-full ${light ? LIGHT_DOT[light.status] : "bg-slate-600 animate-pulse"}`}
                  />
                  <span className="hidden text-[10px] uppercase tracking-wide text-slate-500 lg:inline">
                    {key === "data_provider" ? "data" : key === "scheduler" ? "sched" : key}
                  </span>
                </span>
              );
            },
          )}
        </div>
        {error ? <span className="text-[11px] text-rose-400">refresh failed</span> : null}
      </div>
    </div>
  );
}

function FreshnessChip({ label, iso }: { label: string; iso: string | null }) {
  return (
    <span className="text-[11px] text-slate-500">
      {label}{" "}
      <span className="tabular-nums text-slate-300">{iso ? fmtTime(iso) : "—"}</span>
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Autopilot hero — what the bot is doing right now, plain language    */
/* ------------------------------------------------------------------ */

function AutopilotHero({ bot, onChanged }: { bot: BotStatus | null; onChanged: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [fail, setFail] = useState<string | null>(null);

  const control = async (path: string) => {
    setBusy(path);
    setFail(null);
    try {
      await apiPost(path, {});
      onChanged();
    } catch (e) {
      setFail(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const label = bot?.state_label ?? "…";
  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised px-4 py-3 shadow-card">
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={`rounded border px-3 py-1 text-sm font-bold tracking-wider ${BOT_TONE[label] ?? "border-surface-border text-slate-300"}`}
        >
          AUTO PILOT · {label}
        </span>
        <p className="min-w-[16rem] flex-1 text-sm text-slate-300">
          {bot?.activity ?? "Reading the bot's status…"}
        </p>
        <PlanSearch />
        <div className="flex items-center gap-2">
          <button
            disabled={!!busy || !bot}
            onClick={() =>
              void control(bot?.state === "paused" ? "/daemon/resume" : "/daemon/pause")
            }
            className="rounded border border-surface-border px-3 py-1.5 text-xs text-slate-300 hover:bg-surface/60 disabled:opacity-40"
          >
            {busy && busy !== "/daemon/scan-now"
              ? "…"
              : bot?.state === "paused"
                ? "Resume"
                : "Pause"}
          </button>
          <button
            disabled={!!busy}
            onClick={() => void control("/daemon/scan-now")}
            className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
          >
            {busy === "/daemon/scan-now" ? "Requesting…" : "Scan now"}
          </button>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-[11px] text-slate-500">
        <span>
          {bot?.next_action.label ?? "next action"}:{" "}
          <span className="tabular-nums text-slate-300">
            {countdown(bot?.next_action.seconds)}
          </span>
        </span>
        {bot?.last_scan_at ? <span>last scan {fmtTime(bot.last_scan_at)}</span> : null}
        {bot?.last_cycle ? (
          <span>
            last cycle: {bot.last_cycle.candidates ?? 0} candidates ·{" "}
            {bot.last_cycle.managed ?? 0} managed · {bot.last_cycle.entered ?? 0} entered
            {bot.last_cycle.closed ? ` · ${bot.last_cycle.closed} closed` : ""}
          </span>
        ) : null}
        {bot?.last_completed_action ? (
          <span className="truncate">
            last action: {bot.last_completed_action.message} (
            {fmtTime(bot.last_completed_action.at)})
          </span>
        ) : null}
        {bot?.last_error ? (
          <span className="text-rose-400">last error: {bot.last_error}</span>
        ) : null}
        {fail ? <span className="text-rose-400">{fail}</span> : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Account summary — the money, at a glance                            */
/* ------------------------------------------------------------------ */

function AccountSummary({ account }: { account: Hud["account"] }) {
  const a = account;
  const heat = a.portfolio_heat_pct ?? 0;
  const heatFrac = Math.min(heat / a.heat_cap_pct, 1);
  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised px-4 py-3 shadow-card">
      <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4 lg:grid-cols-8">
        <Metric label="Equity" value={money(a.equity)} big />
        <Metric
          label="Today's P/L"
          value={money(a.today_realized_pnl + a.unrealized_pnl)}
          tone={a.today_realized_pnl + a.unrealized_pnl}
          big
        />
        <Metric label="Unrealized" value={money(a.unrealized_pnl)} tone={a.unrealized_pnl} />
        <Metric
          label="Realized (total)"
          value={money(a.realized_pnl_total)}
          tone={a.realized_pnl_total}
        />
        <Metric label="Cash" value={money(a.cash)} />
        <Metric label="Buying power" value={money(a.buying_power)} />
        <Metric label="Open / closed today" value={`${a.open_positions} / ${a.closed_today}`} />
        <Metric
          label="Exposure"
          value={`${money(a.exposure)}${a.exposure_pct != null ? ` (${num(a.exposure_pct, 1)}%)` : ""}`}
        />
        <Metric
          label="Win rate"
          value={a.win_rate != null ? `${num(a.win_rate * 100, 0)}%` : "—"}
        />
        <Metric label="Profit factor" value={num(a.profit_factor)} />
        <Metric
          label="Expectancy"
          value={a.expectancy_r != null ? `${signed(a.expectancy_r)}R` : "—"}
          tone={a.expectancy_r}
        />
        <Metric label="Avg winner" value={money(a.avg_winner)} tone={a.avg_winner} />
        <Metric label="Avg loser" value={money(a.avg_loser)} tone={a.avg_loser} />
        <Metric label="Largest win / loss" value={`${money(a.largest_winner)} / ${money(a.largest_loser)}`} />
        <Metric
          label="Max drawdown"
          value={a.max_drawdown != null ? `${num(Math.abs(a.max_drawdown) * 100, 1)}%` : "—"}
        />
        <Metric
          label="Risk used / allowed"
          value={`${money(a.risk_used)} / ${money(a.max_risk_allowed)}`}
        />
      </div>
      <div className="mt-3">
        <div className="mb-1 flex items-center justify-between text-[11px] text-slate-500">
          <span>
            Portfolio heat{" "}
            <span className="tabular-nums text-slate-300">{num(heat, 2)}%</span> of{" "}
            {num(a.heat_cap_pct, 0)}% cap
          </span>
        </div>
        <div className="h-1.5 overflow-hidden rounded bg-surface">
          <div
            className={`h-full rounded transition-all duration-500 ${heatFrac > 0.85 ? "bg-rose-500" : heatFrac > 0.6 ? "bg-amber-400" : "bg-emerald-500"}`}
            style={{ width: `${Math.max(heatFrac * 100, heat > 0 ? 2 : 0)}%` }}
          />
        </div>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
  big,
}: {
  label: string;
  value: string;
  tone?: number | null;
  big?: boolean;
}) {
  const color =
    tone == null || tone === 0
      ? "text-slate-100"
      : tone > 0
        ? "text-emerald-400"
        : "text-rose-400";
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`tabular-nums ${big ? "text-lg font-semibold" : "text-sm"} ${color}`}>
        {value}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Market panel — regime, posture, indexes, breadth, volatility        */
/* ------------------------------------------------------------------ */

function MarketPanel({ market }: { market: Hud["market"] }) {
  const posture = market.posture ? POSTURE[market.posture] : null;
  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised p-4 shadow-card">
      <SectionTitle title="Market" hint={market.as_of ? `regime as of ${market.as_of}` : undefined} />
      <div className="mb-3 flex items-baseline gap-3">
        <span className={`text-xl font-bold ${posture?.tone ?? "text-slate-400"}`}>
          {posture?.label ?? "UNKNOWN"}
        </span>
        <span className="text-sm capitalize text-slate-300">{market.regime ?? "no regime"}</span>
        {market.confidence != null ? (
          <span className="text-xs text-slate-500">
            confidence {num(market.confidence * 100, 0)}%
          </span>
        ) : null}
      </div>
      <div className="mb-3 space-y-1.5">
        {market.indexes.length === 0 ? (
          <p className="text-xs text-slate-500">
            No index bars cached yet — run a scan to pull SPY/QQQ/DIA/IWM.
          </p>
        ) : (
          market.indexes.map((ix) => (
            <div key={ix.symbol} className="flex items-center justify-between text-sm">
              <span className="font-medium text-slate-200">{ix.symbol}</span>
              <span className="tabular-nums text-slate-300">{num(ix.last)}</span>
              <span
                className={`w-16 text-right tabular-nums ${
                  (ix.change_pct ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"
                }`}
              >
                {ix.change_pct != null ? `${signed(ix.change_pct)}%` : "—"}
              </span>
            </div>
          ))
        )}
      </div>
      <div className="flex items-center justify-between border-t border-surface-border pt-2 text-xs text-slate-500">
        <span>
          Breadth{" "}
          <span className="tabular-nums text-slate-300">
            {market.breadth_pct != null ? `${num(market.breadth_pct, 0)}% > 200DMA` : "—"}
          </span>
        </span>
        <span>
          SPY vol{" "}
          <span className="tabular-nums text-slate-300">
            {market.spy_realized_vol_pct != null ? `${num(market.spy_realized_vol_pct, 1)}%` : "—"}
          </span>
        </span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Managed watchlist — tracked-but-not-positioned symbols              */
/* ------------------------------------------------------------------ */

function ManagedWatchlist({
  watched,
  onChanged,
}: {
  watched: TrackedTradeRow[];
  onChanged: () => void;
}) {
  const navigate = useNavigate();
  const [plan, setPlan] = useState<string | null>(null);

  return (
    <section>
      <SectionTitle
        title="Managed Watchlist"
        hint="tracked by the bot — no position; readiness regraded every scan"
      />
      {watched.length === 0 ? (
        <EmptyPanel text="Nothing tracked without a position. Search a ticker above and choose Track — the bot will monitor it every scan." />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-surface-border bg-surface-raised shadow-card">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-slate-600">
                <th className="px-3 py-2 text-left font-semibold">Symbol</th>
                <th className="px-3 py-2 text-right font-semibold">Entry plan</th>
                <th className="px-3 py-2 text-right font-semibold">Stop</th>
                <th className="px-3 py-2 text-right font-semibold">Conviction</th>
                <th className="px-3 py-2 text-left font-semibold">Health</th>
                <th className="px-3 py-2 text-left font-semibold">Last advice</th>
                <th className="px-3 py-2 text-right font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {watched.map((t) => (
                <tr key={t.trade_uid} className="border-t border-surface-border/40">
                  <td className="px-3 py-2 font-medium text-slate-100">{t.symbol}</td>
                  <td className="px-3 py-2 text-right text-slate-300">{num(t.entry_price)}</td>
                  <td className="px-3 py-2 text-right text-slate-300">{num(t.stop_price)}</td>
                  <td className="px-3 py-2 text-right text-slate-300">
                    {t.conviction_score != null ? Math.round(t.conviction_score) : "—"}
                    {t.conviction_band ? (
                      <span className="ml-1 text-[10px] text-slate-500">{t.conviction_band}</span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 text-slate-300">{t.trade_health ?? "—"}</td>
                  <td className="max-w-[16rem] truncate px-3 py-2 text-xs text-slate-400">
                    {t.latest_action ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={() => setPlan(t.symbol)}
                      className="mr-2 rounded border border-surface-border px-2 py-0.5 text-[11px] text-slate-300 hover:bg-surface/60"
                    >
                      Thesis
                    </button>
                    <button
                      onClick={() => navigate(`/trades?symbol=${t.symbol}`)}
                      className="rounded border border-surface-border px-2 py-0.5 text-[11px] text-slate-300 hover:bg-surface/60"
                    >
                      History
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {plan ? (
        <PlanModal
          symbol={plan}
          onClose={() => {
            setPlan(null);
            onChanged();
          }}
        />
      ) : null}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Alert center + mission log                                          */
/* ------------------------------------------------------------------ */

const SEVERITY_ORDER: Record<string, number> = { critical: 0, warning: 1, info: 2 };

function AlertCenter({ alerts }: { alerts: AlertRow[] }) {
  const ordered = [...alerts].sort(
    (a, b) => (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3),
  );
  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised p-4 shadow-card">
      <SectionTitle title="Alert Center" hint={`${alerts.length} recent`} />
      {ordered.length === 0 ? (
        <p className="text-xs text-slate-500">No alerts. Quiet is good.</p>
      ) : (
        <ul className="space-y-1.5">
          {ordered.slice(0, 8).map((a) => (
            <li
              key={a.id}
              title={a.description ?? undefined}
              className={`rounded border px-2.5 py-1.5 text-xs ${SEVERITY_TONE[a.severity] ?? SEVERITY_TONE.info}`}
            >
              <span className="mr-2 font-semibold uppercase">{a.severity}</span>
              {a.symbol ? <span className="mr-1 font-medium">{a.symbol}</span> : null}
              {a.title}
              <span className="ml-2 text-[10px] opacity-70">{fmtTime(a.ts)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MissionLog({ activity, audit }: { activity: ActivityRow[]; audit: AuditRow[] }) {
  const merged: { key: string; ts: string; label: string; text: string }[] = [
    ...activity.map((a) => ({
      key: `act-${a.id}`,
      ts: a.ts ?? "",
      label: a.category,
      text: `${a.symbol ? `${a.symbol} — ` : ""}${a.text}`,
    })),
    ...audit.map((a) => ({
      key: `aud-${a.id}`,
      ts: a.ts ?? "",
      label: a.event_type,
      text: `${a.symbol ? `${a.symbol} — ` : ""}${a.summary ?? ""}`,
    })),
  ]
    .sort((a, b) => (a.ts < b.ts ? 1 : -1))
    .slice(0, 20);

  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised p-4 shadow-card">
      <SectionTitle title="Mission Log" hint="every scan, decision, override and alert" />
      {merged.length === 0 ? (
        <p className="text-xs text-slate-500">Nothing yet — the log fills as the bot works.</p>
      ) : (
        <ul className="max-h-80 space-y-1 overflow-y-auto text-xs">
          {merged.map((row) => (
            <li key={row.key} className="flex gap-2 border-b border-surface-border/30 py-1">
              <span
                className="w-[4.5rem] shrink-0 tabular-nums text-slate-500"
                title={dateTime(row.ts)}
              >
                {fmtTime(row.ts)}
              </span>
              <span className="w-28 shrink-0 truncate uppercase tracking-wide text-slate-500">
                {row.label.replace(/_/g, " ")}
              </span>
              <span className="text-slate-300">{row.text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Shared bits                                                         */
/* ------------------------------------------------------------------ */

function SectionTitle({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="mb-2 flex items-baseline gap-3">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">{title}</h2>
      {hint ? <span className="text-[11px] text-slate-500">{hint}</span> : null}
    </div>
  );
}

function EmptyPanel({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-dashed border-surface-border bg-surface-raised/50 p-6 text-center text-sm text-slate-500">
      {text}
    </div>
  );
}

function PanelSkeleton({ rows }: { rows: number }) {
  return (
    <div className="animate-pulse rounded-lg border border-surface-border bg-surface-raised p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="mb-2 h-4 rounded bg-surface last:mb-0" />
      ))}
    </div>
  );
}

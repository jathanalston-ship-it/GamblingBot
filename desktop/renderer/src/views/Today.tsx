import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import type { ActivityItem, Today as TodayPayload } from "../api/today";
import { ErrorBox, Loading } from "../components/Page";
import { AutopilotSwitch, ScanButton } from "../components/simple/actions";
import {
  Empty,
  Figure,
  Gain,
  Panel,
  Section,
  fraction,
  percent,
  usd,
} from "../components/simple/common";
import { EvidenceCard } from "../components/simple/EvidenceCard";
import { PositionsTable, SignalsTable } from "../components/simple/tables";
import { useApi } from "../hooks/useApi";
import { date as fmtDate, dateTime } from "../lib/format";

const ACTIVITY_TONE: Record<string, string> = {
  critical: "bg-bear",
  warning: "bg-neutral",
  info: "bg-slate-500",
};

function ago(iso: string | null | undefined): string {
  if (!iso) return "never";
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

function MarketBanner({ t, onChanged }: { t: TodayPayload; onChanged: () => void }) {
  const gate = t.market;
  const tone =
    gate.uptrend === true
      ? { ring: "border-bull/30", dot: "bg-bull", text: "text-bull", word: "Uptrend" }
      : gate.uptrend === false
        ? { ring: "border-bear/40", dot: "bg-bear", text: "text-bear", word: "Downtrend" }
        : { ring: "border-surface-border", dot: "bg-slate-500", text: "text-slate-300", word: "Unknown" };
  return (
    <div className={`rounded-card border ${tone.ring} bg-surface-raised px-5 py-4 shadow-card`}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 max-w-3xl">
          <div className="flex items-center gap-2 text-[12px] font-medium uppercase tracking-wide">
            <span className={`h-2 w-2 rounded-full ${tone.dot}`} />
            <span className={tone.text}>Market: {tone.word}</span>
          </div>
          <h1 className="mt-1.5 text-[22px] font-semibold leading-snug tracking-tight text-slate-50">
            {t.headline}
          </h1>
          <p className="mt-1 text-[13px] leading-relaxed text-slate-400">{gate.detail}</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <ScanButton onDone={onChanged} />
          <span className="text-right text-[12px] text-slate-500">
            {t.data.has_scan ? (
              <>
                Prices through {fmtDate(t.data.bars_through ?? null)} · checked{" "}
                {ago(t.data.last_scan_at)}
                <br />
                {t.data.symbols} stocks · {t.data.universe}
              </>
            ) : (
              "No market data loaded yet"
            )}
          </span>
        </div>
      </div>
      {t.data.stale ? (
        <div className="mt-3 rounded-md border border-neutral/30 bg-neutral/10 px-3 py-2 text-[13px] text-neutral">
          These prices are out of date. Press <b>Scan now</b> before buying or selling anything.
        </div>
      ) : null}
    </div>
  );
}

function AccountStrip({ t }: { t: TodayPayload }) {
  const a = t.account;
  const total = a.equity - a.starting_balance;
  return (
    <Panel className="mt-4">
      <div className="grid grid-cols-2 divide-x divide-y divide-surface-border/60 sm:grid-cols-3 lg:grid-cols-5 lg:divide-y-0">
        <Figure
          label="Account value"
          value={usd(a.equity)}
          sub={
            <>
              <Gain value={total} /> since start
            </>
          }
        />
        <Figure
          label="Open profit / loss"
          value={<Gain value={a.unrealized_pnl} />}
          sub={`on ${a.open_positions} position${a.open_positions === 1 ? "" : "s"}`}
        />
        <Figure
          label="Cash"
          value={usd(a.cash)}
          sub={a.exposure_pct != null ? `${percent(a.exposure_pct, 0)} invested` : "nothing invested"}
        />
        <Figure
          label="Positions"
          value={`${a.open_positions} of ${a.max_positions}`}
          sub={`${a.slots_free} slot${a.slots_free === 1 ? "" : "s"} free`}
        />
        <Figure
          label="Lost if every stop hits"
          value={usd(a.risk_used)}
          sub={
            a.portfolio_heat_pct != null
              ? `${percent(a.portfolio_heat_pct, 1)} of the account`
              : "if every stop is hit"
          }
        />
      </div>
    </Panel>
  );
}

function AutopilotPanel({ t, onChanged }: { t: TodayPayload; onChanged: () => void }) {
  const bot = t.autopilot;
  return (
    <Panel className="mt-4">
      <div className="flex flex-wrap items-center justify-between gap-4 px-5 py-3.5">
        <div className="min-w-0 max-w-3xl text-[13px] leading-relaxed">
          <div className="font-semibold text-slate-100">
            {bot.enabled
              ? "Auto Pilot is trading these rules for you (paper money)"
              : "Auto Pilot is off — you place the trades"}
          </div>
          <div className="text-slate-400">
            {bot.enabled
              ? "It buys each day's signals when the market opens and sells at the stop or the trend exit. "
              : "Turn it on and the app buys each day's signals and sells at the stop or the trend exit by itself. "}
            <span className="text-slate-500">{bot.activity}</span>
          </div>
          {bot.last_error ? (
            <div className="mt-1 text-[12px] text-bear">Last problem: {bot.last_error}</div>
          ) : null}
        </div>
        <AutopilotSwitch enabled={bot.enabled} onChange={onChanged} />
      </div>
    </Panel>
  );
}

function ActivityFeed({ items }: { items: ActivityItem[] }) {
  if (items.length === 0) {
    return (
      <Empty>
        Nothing yet. Buys, sells and market changes will be listed here as they happen.
      </Empty>
    );
  }
  return (
    <Panel>
      <ul className="divide-y divide-surface-border/50">
        {items.map((a) => (
          <li key={a.id} className="flex gap-3 px-5 py-3">
            <span
              className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${ACTIVITY_TONE[a.severity] ?? "bg-slate-500"}`}
            />
            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline gap-x-2 text-[13px]">
                <span className="font-medium text-slate-100">{a.title}</span>
                <span className="text-[12px] text-slate-500">{dateTime(a.ts)}</span>
              </div>
              {a.description ? (
                <p className="mt-0.5 text-[13px] leading-snug text-slate-400">{a.description}</p>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

export default function Today() {
  const { data, error, loading, reload } = useApi<TodayPayload>("/today", { refreshMs: 30_000 });
  const navigate = useNavigate();
  const [showRules, setShowRules] = useState(false);

  if (loading && !data) return <Loading />;
  if (error && !data) {
    return (
      <div className="p-6">
        <ErrorBox message={error} />
      </div>
    );
  }
  if (!data) return null;
  const t = data;
  const openSignals = t.signals.filter((s) => !s.held);

  return (
    <div className="mx-auto max-w-[1180px] px-6 pb-12 pt-5">
      <MarketBanner t={t} onChanged={reload} />
      <AccountStrip t={t} />
      <AutopilotPanel t={t} onChanged={reload} />

      <Section
        title="Your positions"
        hint="Each one is sold automatically if it drops to its “sells below” price — the stop, or the 50-day low once that is higher."
        action={
          t.positions.length > 0 ? (
            <Link to="/positions" className="text-[13px] text-accent hover:underline">
              Details &amp; history →
            </Link>
          ) : null
        }
      >
        {t.positions.length === 0 ? (
          <Empty>
            You don&apos;t own anything yet.{" "}
            {openSignals.length > 0 && t.market.entries_allowed
              ? "Buy one of today's signals below, or switch on Auto Pilot to have the app do it."
              : "When a buy signal appears it will be listed below."}
          </Empty>
        ) : (
          <PositionsTable
            positions={t.positions}
            onChanged={reload}
            onSelect={() => navigate("/positions")}
          />
        )}
      </Section>

      <Section
        title={`Buy signals today${t.signals.length ? ` (${openSignals.length})` : ""}`}
        hint="Leading stocks in an uptrend that just made a new 50-day high, strongest first. “Risk” is what you lose if the stop is hit."
        action={
          t.signals.length > 8 ? (
            <Link to="/signals" className="text-[13px] text-accent hover:underline">
              All {t.signals.length} signals →
            </Link>
          ) : null
        }
      >
        {!t.data.has_scan ? (
          <Empty>
            Press <b>Scan now</b> (top right) to load today&apos;s prices and find the signals.
          </Empty>
        ) : t.signals.length === 0 ? (
          <Empty>
            No stock passes all the entry rules today. That is normal — the strategy waits for
            leaders making new highs and does nothing otherwise.
          </Empty>
        ) : (
          <>
            {!t.market.entries_allowed ? (
              <div className="mb-2.5 rounded-md border border-bear/30 bg-bear/10 px-4 py-2.5 text-[13px] text-bear">
                The market is in a downtrend, so the rules say <b>don&apos;t buy</b> right now. These
                stocks are shown for reference; Auto Pilot will not buy them.
              </div>
            ) : null}
            <SignalsTable
              signals={t.signals}
              market={t.market}
              slotsFree={t.account.slots_free}
              onChanged={reload}
              onSelect={(symbol) => navigate(`/signals?symbol=${symbol}`)}
              limit={8}
            />
          </>
        )}
        {t.watching.length > 0 ? (
          <p className="mt-2.5 text-[13px] leading-relaxed text-slate-400">
            <span className="text-slate-500">Next in line</span> — strong stocks waiting for a new
            high:{" "}
            {t.watching.map((s, i) => (
              <span key={s} className="font-medium text-slate-300">
                {s}
                {i < t.watching.length - 1 ? ", " : ""}
              </span>
            ))}
          </p>
        ) : null}
      </Section>

      <Section title="What happened" hint="Buys, sells and market changes — newest first.">
        <ActivityFeed items={t.activity} />
      </Section>

      <Section
        title="Does this work?"
        hint="The same rules, tested on years of real prices."
        action={
          <Link to="/results" className="text-[13px] text-accent hover:underline">
            Full results →
          </Link>
        }
      >
        <EvidenceCard evidence={t.evidence} onChanged={reload} compact />
      </Section>

      <Section
        title="How it works"
        action={
          <button className="btn-quiet" onClick={() => setShowRules((v) => !v)}>
            {showRules ? "Hide" : "Show the four rules"}
          </button>
        }
      >
        {showRules ? (
          <div className="grid gap-3 md:grid-cols-2">
            {t.rules.rules.map((rule, i) => (
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
        ) : (
          <p className="text-[13px] leading-relaxed text-slate-400">
            Buy leading stocks breaking out to new highs while the market is rising; risk{" "}
            {fraction(Number(t.rules.config["risk_per_trade_pct"] ?? 0.005), 1)} of the account per
            trade; sell at the stop or when the trend breaks. No predictions, no profit targets.
          </p>
        )}
      </Section>
    </div>
  );
}

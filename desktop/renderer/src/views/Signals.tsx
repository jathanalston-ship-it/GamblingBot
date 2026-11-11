import { useEffect, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import type { Signal, Today as TodayPayload } from "../api/today";
import { ErrorBox, Loading } from "../components/Page";
import { PriceChart, type Overlay } from "../components/PriceChart";
import { BuyButton, ScanButton } from "../components/simple/actions";
import { Empty, Panel, Section, price, usd } from "../components/simple/common";
import { SignalsTable } from "../components/simple/tables";
import { useApi } from "../hooks/useApi";

function Check({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <li className="flex gap-2.5 py-1 text-[13px] leading-snug">
      <span className={ok ? "text-bull" : "text-bear"} aria-hidden>
        {ok ? "✓" : "✕"}
      </span>
      <span className={ok ? "text-slate-300" : "text-slate-400"}>{children}</span>
    </li>
  );
}

function SignalDetail({
  signal,
  t,
  onChanged,
}: {
  signal: Signal;
  t: TodayPayload;
  onChanged: () => void;
}) {
  const overlays: Overlay[] = [];
  if (signal.stop != null) overlays.push({ label: "stop", price: signal.stop, kind: "stop" });
  if (signal.exit_level != null) {
    overlays.push({ label: "50-day low", price: signal.exit_level, kind: "exit" });
  }
  const cfg = t.rules.config;
  const within = Number(cfg["breakout_within"] ?? 10);
  const lookback = Number(cfg["breakout_lookback"] ?? 50);
  const top = Math.round((1 - Number(cfg["min_momentum_rank"] ?? 0.8)) * 100);
  return (
    <Panel>
      <div className="px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-baseline gap-2.5">
              <h2 className="text-xl font-semibold text-slate-50">{signal.symbol}</h2>
              <span className="text-[13px] text-slate-500">{signal.sector ?? ""}</span>
            </div>
            <div className="mt-0.5 text-[13px] text-slate-400">
              Last price {price(signal.price)} · ranked #{signal.rank} today
            </div>
          </div>
          <BuyButton
            signal={signal}
            market={t.market}
            slotsFree={t.account.slots_free}
            onDone={onChanged}
          />
        </div>

        <div className="mt-3">
          <PriceChart symbol={signal.symbol} overlays={overlays} days={260} height={240} />
        </div>

        <div className="mt-4 grid gap-6 md:grid-cols-2">
          <div>
            <div className="text-[12px] font-medium uppercase tracking-wide text-slate-500">
              Why it is a signal
            </div>
            <ul className="mt-1.5">
              <Check ok={t.market.entries_allowed}>
                {t.market.entries_allowed
                  ? "The market is in an uptrend"
                  : "The market is in a downtrend — the rules say wait"}
              </Check>
              <Check ok>
                A leader: stronger than {signal.momentum_pct ?? "?"}% of the stocks scanned (top{" "}
                {top}% required)
              </Check>
              <Check ok>Trading above its own 200-day average</Check>
              <Check ok>
                New {lookback}-day high{" "}
                {signal.bars_since_breakout === 0
                  ? "on the last session"
                  : `${signal.bars_since_breakout} session${signal.bars_since_breakout === 1 ? "" : "s"} ago`}{" "}
                (within {within} required)
              </Check>
            </ul>
          </div>
          <div>
            <div className="text-[12px] font-medium uppercase tracking-wide text-slate-500">
              The trade
            </div>
            <dl className="mt-1.5 text-[13px]">
              {[
                ["Buy", `${signal.shares ?? "—"} shares ≈ ${usd(signal.position_value)}`],
                [
                  "Stop (sold automatically)",
                  `${price(signal.stop)}${signal.stop_pct != null ? `  (−${signal.stop_pct.toFixed(1)}%)` : ""}`,
                ],
                ["You lose if stopped", usd(signal.risk_dollars)],
                ["Otherwise held until it closes below", `${price(signal.exit_level)} (50-day low)`],
              ].map(([k, v]) => (
                <div key={k} className="flex items-baseline justify-between gap-4 py-1">
                  <dt className="text-slate-400">{k}</dt>
                  <dd className="text-right tabular-nums text-slate-100">{v}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-2 text-[12px] leading-relaxed text-slate-500">
              There is no profit target. The 50-day low rises as the stock climbs, so a winner is
              held for as long as its trend lasts and sold when it breaks.
            </p>
          </div>
        </div>
      </div>
    </Panel>
  );
}

export default function Signals() {
  const { data, error, loading, reload } = useApi<TodayPayload>("/today", { refreshMs: 30_000 });
  const [params, setParams] = useSearchParams();
  const wanted = params.get("symbol");

  const selected = useMemo(() => {
    const list = data?.signals ?? [];
    return list.find((s) => s.symbol === wanted) ?? list[0] ?? null;
  }, [data, wanted]);

  useEffect(() => {
    if (selected && selected.symbol !== wanted) {
      setParams({ symbol: selected.symbol }, { replace: true });
    }
  }, [selected, wanted, setParams]);

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

  return (
    <div className="mx-auto max-w-[1180px] px-6 pb-12 pt-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-slate-50">Buy signals</h1>
          <p className="mt-0.5 text-[13px] text-slate-400">
            Every stock that passes all the entry rules today, strongest first. The list changes
            once a day, after the market closes.
          </p>
        </div>
        <ScanButton onDone={reload} />
      </div>

      {!t.market.entries_allowed && t.data.has_scan ? (
        <div className="mt-4 rounded-md border border-bear/30 bg-bear/10 px-4 py-2.5 text-[13px] text-bear">
          {t.market.headline}. {t.market.detail}
        </div>
      ) : null}

      {t.signals.length === 0 ? (
        <div className="mt-5">
          <Empty>
            {t.data.has_scan
              ? "No stock passes all the entry rules today. The strategy waits; so should you."
              : "Press Scan now to load today's prices and find the signals."}
          </Empty>
        </div>
      ) : (
        <>
          <div className="mt-5">
            <SignalsTable
              signals={t.signals}
              market={t.market}
              slotsFree={t.account.slots_free}
              onChanged={reload}
              onSelect={(symbol) => setParams({ symbol }, { replace: true })}
              selected={selected?.symbol ?? null}
            />
          </div>
          {selected ? (
            <Section title={`${selected.symbol} in detail`}>
              <SignalDetail signal={selected} t={t} onChanged={reload} />
            </Section>
          ) : null}
        </>
      )}

      {t.watching.length > 0 ? (
        <Section
          title="Next in line"
          hint="Leaders in an uptrend that have not made a new 50-day high in the last two weeks. They become signals when they do."
        >
          <Panel>
            <div className="flex flex-wrap gap-2 px-5 py-4">
              {t.watching.map((s) => (
                <span
                  key={s}
                  className="rounded-md border border-surface-edge/60 px-2.5 py-1 text-[13px] font-medium text-slate-300"
                >
                  {s}
                </span>
              ))}
            </div>
          </Panel>
        </Section>
      ) : null}
    </div>
  );
}

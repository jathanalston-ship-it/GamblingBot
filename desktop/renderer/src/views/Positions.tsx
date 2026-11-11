import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import type { Position, Today as TodayPayload } from "../api/today";
import type { Trade } from "../api/types";
import { ErrorBox, Loading } from "../components/Page";
import { PriceChart, type Overlay } from "../components/PriceChart";
import {
  Empty,
  Figure,
  Gain,
  GainPct,
  Panel,
  Section,
  TD,
  TD_R,
  TH,
  TH_R,
  price,
  usd,
} from "../components/simple/common";
import { PositionsTable } from "../components/simple/tables";
import { useApi } from "../hooks/useApi";
import { date as fmtDate } from "../lib/format";

const EXIT_WORDS: Record<string, string> = {
  stop: "Stop hit",
  trend_exit: "Trend broke",
  manual: "You sold",
  target: "Target",
  scale_out: "Partial sale",
  time_stop: "Time limit",
  trailing_stop: "Trailing stop",
};

function PositionDetail({ p }: { p: Position }) {
  const overlays: Overlay[] = [
    { label: "paid", price: p.entry_price, kind: "entry" },
    { label: "stop", price: p.stop, kind: "stop" },
  ];
  if (p.exit_level != null) overlays.push({ label: "50-day low", price: p.exit_level, kind: "exit" });
  const exitIsBinding = p.exit_level != null && p.exit_level > p.stop;
  return (
    <Panel>
      <div className="px-5 py-4">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div className="flex items-baseline gap-2.5">
            <h2 className="text-xl font-semibold text-slate-50">{p.symbol}</h2>
            <span className="text-[13px] text-slate-500">{p.sector ?? ""}</span>
          </div>
          <div className="text-[13px] text-slate-400">
            {p.shares} shares · worth {usd(p.value)} · <Gain value={p.pnl} /> (
            <GainPct value={p.pnl_pct} />
            {p.r != null ? `, ${p.r >= 0 ? "+" : ""}${p.r.toFixed(1)}R` : ""})
          </div>
        </div>
        <div className="mt-3">
          <PriceChart symbol={p.symbol} overlays={overlays} days={260} height={240} />
        </div>
        <p className="mt-3 text-[13px] leading-relaxed text-slate-400">
          {p.mode === "manual" ? (
            <>
              You manage this position yourself — the app will advise but not sell it. The rules
              would sell below <b className="text-slate-200">{price(p.sell_below)}</b>.
            </>
          ) : exitIsBinding ? (
            <>
              The app sells this position if it <b className="text-slate-200">closes</b> below{" "}
              <b className="text-slate-200">{price(p.exit_level)}</b> (its 50-day low), or
              immediately if it touches the stop at {price(p.stop)}. The 50-day low rises as the
              stock climbs, locking in more of the gain.
            </>
          ) : (
            <>
              The app sells this position if it touches the stop at{" "}
              <b className="text-slate-200">{price(p.stop)}</b>
              {p.exit_level != null ? (
                <>
                  , or if it closes below its 50-day low ({price(p.exit_level)}, currently beneath
                  the stop)
                </>
              ) : null}
              . If the stop is hit from here you give back about{" "}
              <b className="text-slate-200">{usd(p.risk_dollars)}</b>.
            </>
          )}
        </p>
      </div>
    </Panel>
  );
}

export default function Positions() {
  const today = useApi<TodayPayload>("/today", { refreshMs: 30_000 });
  const closed = useApi<Trade[]>("/trades?status=closed&limit=500");
  const [picked, setPicked] = useState<string | null>(null);

  const positions = today.data?.positions ?? [];
  const selected = useMemo(
    () => positions.find((p) => p.trade_uid === picked) ?? positions[0] ?? null,
    [positions, picked],
  );
  const history = useMemo(
    () =>
      [...(closed.data ?? [])].sort((a, b) =>
        String(b.exit_ts ?? "").localeCompare(String(a.exit_ts ?? "")),
      ),
    [closed.data],
  );

  if (today.loading && !today.data) return <Loading />;
  if (today.error && !today.data) {
    return (
      <div className="p-6">
        <ErrorBox message={today.error} />
      </div>
    );
  }
  if (!today.data) return null;
  const t = today.data;
  const a = t.account;
  const reload = (): void => {
    today.reload();
    closed.reload();
  };
  const wins = history.filter((h) => (h.net_pnl ?? 0) > 0).length;

  return (
    <div className="mx-auto max-w-[1180px] px-6 pb-12 pt-5">
      <h1 className="text-[22px] font-semibold tracking-tight text-slate-50">Positions</h1>
      <p className="mt-0.5 text-[13px] text-slate-400">
        What you own in the paper account, and every trade you have closed.
      </p>

      <Panel className="mt-4">
        <div className="grid grid-cols-2 divide-x divide-y divide-surface-border/60 sm:grid-cols-4 sm:divide-y-0">
          <Figure label="Invested" value={usd(a.exposure)} sub={`${a.open_positions} positions`} />
          <Figure label="Open profit / loss" value={<Gain value={a.unrealized_pnl} />} />
          <Figure
            label="Closed profit / loss"
            value={<Gain value={a.realized_pnl_total} />}
            sub={`${history.length} closed trade${history.length === 1 ? "" : "s"}`}
          />
          <Figure label="Lost if every stop hits" value={usd(a.risk_used)} />
        </div>
      </Panel>

      <Section title="Open positions" hint="Click a row to see its chart and exit levels.">
        {positions.length === 0 ? (
          <Empty>
            Nothing open.{" "}
            <Link to="/signals" className="text-accent hover:underline">
              See today&apos;s buy signals
            </Link>
            .
          </Empty>
        ) : (
          <>
            <PositionsTable
              positions={positions}
              onChanged={reload}
              onSelect={setPicked}
              selected={selected?.trade_uid ?? null}
            />
            {selected ? (
              <div className="mt-3">
                <PositionDetail p={selected} />
              </div>
            ) : null}
          </>
        )}
      </Section>

      <Section
        title="Closed trades"
        hint={
          history.length > 0
            ? `${wins} of ${history.length} made money. Expect most to be small losses — the strategy earns from a few large winners.`
            : undefined
        }
      >
        {history.length === 0 ? (
          <Empty>No closed trades yet.</Empty>
        ) : (
          <Panel>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] border-collapse">
                <thead className="border-b border-surface-border/70">
                  <tr>
                    <th className={TH}>Stock</th>
                    <th className={TH}>Bought</th>
                    <th className={TH}>Sold</th>
                    <th className={TH_R}>Shares</th>
                    <th className={TH_R}>Paid</th>
                    <th className={TH_R}>Sold at</th>
                    <th className={TH_R}>Result</th>
                    <th className={TH}>Why it was sold</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-border/50">
                  {history.map((h) => (
                    <tr key={String(h.id)} className="hover:bg-surface/60">
                      <td className={`${TD} font-semibold text-slate-100`}>{h.symbol}</td>
                      <td className={`${TD} text-slate-400`}>{fmtDate(h.entry_ts)}</td>
                      <td className={`${TD} text-slate-400`}>{fmtDate(h.exit_ts)}</td>
                      <td className={TD_R}>{h.quantity ?? "—"}</td>
                      <td className={TD_R}>{price(h.entry_price)}</td>
                      <td className={TD_R}>{price(h.exit_price)}</td>
                      <td className={TD_R}>
                        <Gain value={h.net_pnl} />
                        {h.r_multiple != null ? (
                          <span className="ml-1.5 text-slate-500">
                            {h.r_multiple >= 0 ? "+" : ""}
                            {h.r_multiple.toFixed(1)}R
                          </span>
                        ) : null}
                      </td>
                      <td className={`${TD} text-slate-400`}>
                        {EXIT_WORDS[h.exit_reason ?? ""] ?? h.exit_reason ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        )}
      </Section>
    </div>
  );
}

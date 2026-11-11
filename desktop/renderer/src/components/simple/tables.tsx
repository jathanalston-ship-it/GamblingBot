import type { MarketGate, Position, Signal } from "../../api/today";
import { BuyButton, SellButton } from "./actions";
import { Gain, GainPct, Panel, TD, TD_R, TH, TH_R, price, usd } from "./common";

function breakoutAge(bars: number | null): string {
  if (bars == null) return "—";
  if (bars === 0) return "today";
  return bars === 1 ? "1 day ago" : `${bars} days ago`;
}

/**
 * Today's buy signals. Each row is a complete trade: what to buy, how many,
 * where it is sold if wrong, and what that costs. Click a row to open it.
 */
export function SignalsTable({
  signals,
  market,
  slotsFree,
  onChanged,
  onSelect,
  selected,
  limit,
}: {
  signals: Signal[];
  market: MarketGate;
  slotsFree: number;
  onChanged: () => void;
  onSelect?: (symbol: string) => void;
  selected?: string | null;
  limit?: number;
}) {
  const rows = limit ? signals.slice(0, limit) : signals;
  return (
    <Panel>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse">
          <thead className="border-b border-surface-border/70">
            <tr>
              <th className={TH}>Stock</th>
              <th className={TH_R}>Price</th>
              <th className={TH}>New high</th>
              <th className={TH_R}>Buy</th>
              <th className={TH_R}>Stop</th>
              <th className={TH_R}>Risk</th>
              <th className={TH_R} aria-label="action" />
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-border/50">
            {rows.map((s) => (
              <tr
                key={s.symbol}
                onClick={() => onSelect?.(s.symbol)}
                className={`${onSelect ? "cursor-pointer" : ""} ${
                  selected === s.symbol ? "bg-accent-soft/10" : "hover:bg-surface/60"
                }`}
              >
                <td className={TD}>
                  <div className="flex items-baseline gap-2">
                    <span className="w-5 text-right text-[11px] tabular-nums text-slate-600">
                      {s.rank}
                    </span>
                    <span className="font-semibold text-slate-100">{s.symbol}</span>
                    <span className="truncate text-[12px] text-slate-500">{s.sector ?? ""}</span>
                  </div>
                </td>
                <td className={TD_R}>{price(s.price)}</td>
                <td className={`${TD} text-slate-400`}>{breakoutAge(s.bars_since_breakout)}</td>
                <td className={TD_R}>
                  {s.shares != null ? (
                    <>
                      <span className="text-slate-100">{s.shares} sh</span>{" "}
                      <span className="text-slate-500">≈ {usd(s.position_value)}</span>
                    </>
                  ) : (
                    "—"
                  )}
                </td>
                <td className={TD_R}>
                  {price(s.stop)}{" "}
                  <span className="text-slate-500">
                    {s.stop_pct != null ? `−${s.stop_pct.toFixed(1)}%` : ""}
                  </span>
                </td>
                <td className={`${TD_R} text-slate-300`}>{usd(s.risk_dollars)}</td>
                <td className={`${TD} text-right`} onClick={(e) => e.stopPropagation()}>
                  <BuyButton
                    signal={s}
                    market={market}
                    slotsFree={slotsFree}
                    onDone={onChanged}
                    size="sm"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

/** Open positions: what you paid, what it is worth, and exactly when it gets sold. */
export function PositionsTable({
  positions,
  onChanged,
  onSelect,
  selected,
}: {
  positions: Position[];
  onChanged: () => void;
  onSelect?: (uid: string) => void;
  selected?: string | null;
}) {
  return (
    <Panel>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse">
          <thead className="border-b border-surface-border/70">
            <tr>
              <th className={TH}>Stock</th>
              <th className={TH_R}>Shares</th>
              <th className={TH_R}>Paid</th>
              <th className={TH_R}>Now</th>
              <th className={TH_R}>Profit / loss</th>
              <th className={TH_R}>Sells below</th>
              <th className={TH_R}>Held</th>
              <th className={TH_R} aria-label="action" />
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-border/50">
            {positions.map((p) => (
              <tr
                key={p.trade_uid}
                onClick={() => onSelect?.(p.trade_uid)}
                className={`${onSelect ? "cursor-pointer" : ""} ${
                  selected === p.trade_uid ? "bg-accent-soft/10" : "hover:bg-surface/60"
                }`}
              >
                <td className={TD}>
                  <span className="font-semibold text-slate-100">{p.symbol}</span>{" "}
                  {p.mode === "manual" ? (
                    <span
                      className="ml-1 rounded border border-neutral/40 px-1 text-[10px] text-neutral"
                      title="You manage this one — the app will not sell it for you"
                    >
                      manual
                    </span>
                  ) : null}
                </td>
                <td className={TD_R}>{p.shares}</td>
                <td className={TD_R}>{price(p.entry_price)}</td>
                <td className={TD_R}>{price(p.last_price)}</td>
                <td className={TD_R}>
                  <Gain value={p.pnl} /> <span className="text-slate-600">·</span>{" "}
                  <GainPct value={p.pnl_pct} />
                </td>
                <td className={TD_R}>
                  {price(p.sell_below)}{" "}
                  <span className="text-slate-500">
                    {p.room_pct != null ? `${p.room_pct.toFixed(1)}% away` : ""}
                  </span>
                </td>
                <td className={`${TD_R} text-slate-400`}>
                  {p.days_held == null ? "—" : p.days_held === 0 ? "today" : `${p.days_held}d`}
                </td>
                <td className={`${TD} text-right`} onClick={(e) => e.stopPropagation()}>
                  <SellButton position={p} onDone={onChanged} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

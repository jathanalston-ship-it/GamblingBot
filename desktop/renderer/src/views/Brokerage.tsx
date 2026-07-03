import { useEffect, useRef, useState } from "react";

import { apiDelete, apiGet, apiPost } from "../api/client";
import { Card } from "../components/Card";
import type { Column } from "../components/DataTable";
import { DataTable } from "../components/DataTable";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { Stat } from "../components/Stat";
import { useApi } from "../hooks/useApi";
import { money, num, pct } from "../lib/format";

interface Account {
  account_id: string;
  cash: number;
  settled_cash: number;
  unsettled_cash: number;
  equity: number;
  portfolio_value: number;
  buying_power: number;
  used_buying_power: number;
  available_margin: number;
  open_risk: number;
  daily_pnl: number;
  total_pnl: number;
  max_drawdown: number;
  trade_count: number;
  win_rate: number | null;
  sharpe: number | null;
  expectancy_r: number | null;
}

interface Position extends Record<string, unknown> {
  symbol: string;
  quantity: number;
  avg_cost: number;
  last_price: number | null;
  market_value: number;
  unrealized_pnl: number;
  todays_gain: number;
  risk_multiple: number | null;
  mfe_price: number | null;
  mae_price: number | null;
  stop_price: number | null;
  days_held: number;
  is_open: boolean;
}

interface OrderEventRow {
  ts: string;
  from_status: string;
  to_status: string;
  reason: string;
}

interface Order extends Record<string, unknown> {
  order_id: string;
  symbol: string;
  side: string;
  quantity: number;
  order_type: string;
  status: string;
  limit_price: number | null;
  stop_price: number | null;
  trail_percent: number | null;
  filled_quantity: number;
  avg_fill_price: number | null;
  reject_reason: string | null;
  link_role: string | null;
  created_ts: string;
  events?: OrderEventRow[];
}

interface Suggestion {
  action: string;
  symbol: string | null;
  reason: string;
}

interface Analysis {
  exposure_pct: number;
  cash_pct: number;
  num_positions: number;
  max_position_symbol: string | null;
  max_position_pct: number;
  max_sector: string | null;
  max_sector_pct: number;
  avg_pairwise_correlation: number | null;
  portfolio_beta: number | null;
  open_risk: number;
  open_risk_pct: number;
  expected_downside: number;
  expected_downside_pct: number;
  capital_efficiency: number | null;
  suggestions: Suggestion[];
}

const OPEN_STATUSES = new Set(["submitted", "accepted", "working", "partially_filled"]);

function statusTone(status: string): string {
  if (status === "filled") return "text-bull";
  if (status === "rejected" || status === "expired") return "text-bear";
  if (status === "cancelled") return "text-slate-500";
  return "text-sky-400";
}

function AccountStrip({ account }: { account: Account }) {
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4 xl:grid-cols-6">
      <Stat label="Equity" value={money(account.equity)} />
      <Stat
        label="Cash"
        value={money(account.cash)}
        hint={`settled ${money(account.settled_cash)} · unsettled ${money(account.unsettled_cash)}`}
      />
      <Stat
        label="Buying Power"
        value={money(account.buying_power)}
        hint={`used ${money(account.used_buying_power)}`}
      />
      <Stat
        label="Daily P&L"
        value={
          <span className={account.daily_pnl >= 0 ? "text-bull" : "text-bear"}>
            {money(account.daily_pnl)}
          </span>
        }
      />
      <Stat
        label="Total P&L"
        value={
          <span className={account.total_pnl >= 0 ? "text-bull" : "text-bear"}>
            {money(account.total_pnl)}
          </span>
        }
        hint={`max drawdown ${pct(account.max_drawdown, 1)}`}
      />
      <Stat
        label="Trades"
        value={String(account.trade_count)}
        hint={`win ${account.win_rate != null ? pct(account.win_rate, 0) : "—"} · exp ${
          account.expectancy_r != null ? `${num(account.expectancy_r, 2)}R` : "—"
        } · sharpe ${account.sharpe != null ? num(account.sharpe, 2) : "—"}`}
      />
    </div>
  );
}

function PlaceOrderForm({ onDone }: { onDone: () => void }) {
  const [form, setForm] = useState({
    symbol: "",
    side: "long",
    quantity: "100",
    order_type: "market",
    limit_price: "",
    stop_price: "",
    trail_percent: "",
    take_profit: "",
    stop_loss: "",
  });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const field = (key: keyof typeof form, placeholder: string, width = "w-24") => (
    <input
      value={form[key]}
      onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
      placeholder={placeholder}
      className={`${width} rounded border border-surface-border bg-surface px-2 py-1 text-xs text-slate-200 outline-none focus:border-accent`}
    />
  );

  const submit = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const body: Record<string, unknown> = {
        symbol: form.symbol.trim().toUpperCase(),
        side: form.side,
        quantity: Number.parseInt(form.quantity, 10),
        order_type: form.order_type,
      };
      if (form.limit_price) body.limit_price = Number(form.limit_price);
      if (form.stop_price) body.stop_price = Number(form.stop_price);
      if (form.trail_percent) body.trail_percent = Number(form.trail_percent);
      if (form.take_profit || form.stop_loss) {
        body.bracket = {
          take_profit: form.take_profit ? Number(form.take_profit) : null,
          stop_loss: form.stop_loss ? Number(form.stop_loss) : null,
        };
      }
      const res = await apiPost<Order>("/brokerage/orders", body);
      setFailed(res.status === "rejected");
      setMessage(
        res.status === "rejected"
          ? `rejected: ${res.reject_reason}`
          : `order ${res.order_id} ${res.status}`,
      );
      onDone();
    } catch (err) {
      setFailed(true);
      setMessage(err instanceof Error ? err.message : "failed");
    } finally {
      setBusy(false);
    }
  };

  const needsLimit = form.order_type === "limit" || form.order_type === "stop_limit";
  const needsStop = form.order_type === "stop" || form.order_type === "stop_limit";
  const needsTrail = form.order_type === "trailing_stop";

  return (
    <div className="flex flex-wrap items-center gap-2">
      {field("symbol", "Symbol", "w-20")}
      <select
        value={form.side}
        onChange={(e) => setForm((f) => ({ ...f, side: e.target.value }))}
        className="rounded border border-surface-border bg-surface px-2 py-1 text-xs text-slate-200"
      >
        <option value="long">Buy</option>
        <option value="short">Sell</option>
      </select>
      {field("quantity", "Qty", "w-16")}
      <select
        value={form.order_type}
        onChange={(e) => setForm((f) => ({ ...f, order_type: e.target.value }))}
        className="rounded border border-surface-border bg-surface px-2 py-1 text-xs text-slate-200"
      >
        <option value="market">Market</option>
        <option value="limit">Limit</option>
        <option value="stop">Stop</option>
        <option value="stop_limit">Stop-Limit</option>
        <option value="trailing_stop">Trailing Stop</option>
      </select>
      {needsLimit ? field("limit_price", "Limit $") : null}
      {needsStop ? field("stop_price", "Stop $") : null}
      {needsTrail ? field("trail_percent", "Trail %") : null}
      <span className="text-[11px] text-slate-500">bracket:</span>
      {field("take_profit", "TP $")}
      {field("stop_loss", "SL $")}
      <button
        disabled={busy || !form.symbol.trim() || !Number.parseInt(form.quantity, 10)}
        onClick={() => void submit()}
        className="btn-primary px-3 py-1 text-xs"
      >
        {busy ? "Placing…" : "Place order"}
      </button>
      {message ? (
        <span className={`text-xs ${failed ? "text-bear" : "text-emerald-400"}`}>{message}</span>
      ) : null}
    </div>
  );
}

function OrderDetail({ orderId }: { orderId: string }) {
  const { data: detail } = useApi<Order>(`/brokerage/orders/${orderId}`);
  if (!detail?.events) return null;
  return (
    <div className="rounded border border-surface-border bg-surface p-3">
      <div className="overline mb-2">Lifecycle — {orderId}</div>
      <div className="space-y-1">
        {detail.events.map((e, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className="tabular-nums text-slate-500">
              {new Date(e.ts).toLocaleTimeString()}
            </span>
            <span className="text-slate-400">
              {e.from_status} → <span className={statusTone(e.to_status)}>{e.to_status}</span>
            </span>
            <span className="text-slate-500">{e.reason}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function OrderBlotter({ orders, onChanged }: { orders: Order[]; onChanged: () => void }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  const cancel = async (orderId: string) => {
    try {
      await apiDelete(`/brokerage/orders/${orderId}`);
      onChanged();
    } catch {
      // surfaced by the reload — the blotter shows the true state
    }
  };

  const cols: Column<Order>[] = [
    {
      key: "order_id",
      header: "Order",
      render: (o) => (
        <button
          className={`underline decoration-dotted ${expanded === o.order_id ? "text-sky-400" : "text-slate-300"}`}
          onClick={() => setExpanded(expanded === o.order_id ? null : o.order_id)}
        >
          {o.order_id.length > 22 ? `${o.order_id.slice(0, 22)}…` : o.order_id}
        </button>
      ),
    },
    { key: "symbol", header: "Symbol" },
    { key: "side", header: "Side", render: (o) => (o.side === "long" ? "Buy" : "Sell") },
    {
      key: "order_type",
      header: "Type",
      render: (o) => (
        <span>
          {o.order_type.replace(/_/g, " ")}
          {o.link_role ? <span className="text-slate-500"> · {o.link_role.replace(/_/g, " ")}</span> : null}
        </span>
      ),
    },
    { key: "quantity", header: "Qty", align: "right" },
    {
      key: "status",
      header: "Status",
      render: (o) => (
        <span className={statusTone(o.status)} title={o.reject_reason ?? undefined}>
          {o.status.replace(/_/g, " ")}
        </span>
      ),
    },
    {
      key: "filled_quantity",
      header: "Filled",
      align: "right",
      render: (o) =>
        o.filled_quantity > 0
          ? `${o.filled_quantity} @ ${o.avg_fill_price != null ? num(o.avg_fill_price, 2) : "—"}`
          : "—",
    },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (o) =>
        OPEN_STATUSES.has(o.status) ? (
          <button
            onClick={() => void cancel(o.order_id)}
            className="rounded border border-surface-border px-2 py-0.5 text-[11px] text-bear hover:bg-surface/60"
          >
            Cancel
          </button>
        ) : null,
    },
  ];

  return (
    <div className="space-y-3">
      <DataTable columns={cols} rows={orders} empty="No orders yet — place one above." />
      {expanded ? <OrderDetail orderId={expanded} /> : null}
    </div>
  );
}

function AnalysisPanel({ analysis }: { analysis: Analysis }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Exposure" value={pct(analysis.exposure_pct, 0)} hint={`cash ${pct(analysis.cash_pct, 0)}`} />
        <Stat
          label="Largest Position"
          value={analysis.max_position_symbol ?? "—"}
          hint={analysis.max_position_symbol ? pct(analysis.max_position_pct, 0) : undefined}
        />
        <Stat
          label="Top Sector"
          value={analysis.max_sector ?? "—"}
          hint={analysis.max_sector ? pct(analysis.max_sector_pct, 0) : undefined}
        />
        <Stat
          label="Open Risk"
          value={money(analysis.open_risk)}
          hint={`downside ${money(analysis.expected_downside)} (${pct(analysis.expected_downside_pct, 1)})`}
        />
        <Stat
          label="Correlation"
          value={
            analysis.avg_pairwise_correlation != null
              ? num(analysis.avg_pairwise_correlation, 2)
              : "—"
          }
        />
        <Stat
          label="Beta"
          value={analysis.portfolio_beta != null ? num(analysis.portfolio_beta, 2) : "—"}
        />
        <Stat
          label="Capital Efficiency"
          value={
            analysis.capital_efficiency != null ? `${num(analysis.capital_efficiency, 1)}×` : "—"
          }
          hint="deployed $ per $ of defined risk"
        />
        <Stat label="Positions" value={String(analysis.num_positions)} />
      </div>
      {analysis.suggestions.length > 0 ? (
        <div className="space-y-2">
          <div className="overline">Suggestions</div>
          {analysis.suggestions.map((s, i) => (
            <div key={i} className="flex items-start gap-2 text-sm">
              <span
                className={`mt-0.5 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                  s.action === "close" || s.action === "reduce"
                    ? "bg-bear/15 text-bear"
                    : s.action === "diversify"
                      ? "bg-amber-500/15 text-amber-400"
                      : "bg-bull/15 text-bull"
                }`}
              >
                {s.action}
              </span>
              <span className="text-slate-300">
                {s.symbol ? <span className="font-medium">{s.symbol}: </span> : null}
                {s.reason}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-xs text-slate-500">No portfolio-level concerns detected.</div>
      )}
    </div>
  );
}

interface ReplayStamp {
  ts: string;
  event: string;
  equity: number;
}

interface ReplayState {
  ts: string;
  account: { equity: number; cash: number; buying_power: number; daily_pnl: number } | null;
  positions: { symbol: string; quantity: number; avg_cost: number; realized_pnl: number }[];
  orders: { order_id: string; symbol: string; status: string }[];
  fills: unknown[];
}

/** Portfolio time machine: play / pause / step / jump through every recorded
 *  venue state — reconstructed from the immutable history, never recomputed. */
function ReplayPanel() {
  const { data: stamps } = useApi<ReplayStamp[]>("/brokerage/replay/timestamps");
  const [index, setIndex] = useState<number | null>(null);
  const [state, setState] = useState<ReplayState | null>(null);
  const [playing, setPlaying] = useState(false);
  const timer = useRef<number | null>(null);

  const count = stamps?.length ?? 0;
  const current = index ?? (count > 0 ? count - 1 : 0);

  useEffect(() => {
    if (!stamps || count === 0) return;
    const stamp = stamps[Math.min(current, count - 1)];
    let cancelled = false;
    apiGet<ReplayState>(`/brokerage/replay/state?ts=${encodeURIComponent(stamp.ts)}`)
      .then((s) => {
        if (!cancelled) setState(s);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [stamps, current, count]);

  useEffect(() => {
    if (!playing) {
      if (timer.current !== null) window.clearInterval(timer.current);
      return;
    }
    timer.current = window.setInterval(() => {
      setIndex((i) => {
        const next = (i ?? 0) + 1;
        if (next >= count) {
          setPlaying(false);
          return count - 1;
        }
        return next;
      });
    }, 800);
    return () => {
      if (timer.current !== null) window.clearInterval(timer.current);
    };
  }, [playing, count]);

  if (!stamps || count === 0) {
    return <div className="text-xs text-slate-500">No history yet — trade something first.</div>;
  }

  const stamp = stamps[Math.min(current, count - 1)];
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <button
          onClick={() => setPlaying((p) => !p)}
          className="btn-ghost px-2.5 py-1 text-xs"
          title={playing ? "Pause" : "Play"}
        >
          {playing ? "⏸ Pause" : "▶ Play"}
        </button>
        <button
          onClick={() => setIndex(Math.max(current - 1, 0))}
          className="btn-quiet px-2 py-1 text-xs"
        >
          ◀ Step
        </button>
        <button
          onClick={() => setIndex(Math.min(current + 1, count - 1))}
          className="btn-quiet px-2 py-1 text-xs"
        >
          Step ▶
        </button>
        <button onClick={() => setIndex(0)} className="btn-quiet px-2 py-1 text-xs">
          ⇤ Start
        </button>
        <button onClick={() => setIndex(count - 1)} className="btn-quiet px-2 py-1 text-xs">
          Now ⇥
        </button>
        <span className="text-xs text-slate-500">
          {new Date(stamp.ts).toLocaleString()} · {stamp.event} · {current + 1}/{count}
        </span>
      </div>
      <input
        type="range"
        min={0}
        max={count - 1}
        value={current}
        onChange={(e) => {
          setPlaying(false);
          setIndex(Number(e.target.value));
        }}
        className="w-full accent-[#4f8ef7]"
      />
      {state?.account ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Equity (then)" value={money(state.account.equity)} />
          <Stat label="Cash (then)" value={money(state.account.cash)} />
          <Stat label="Buying Power (then)" value={money(state.account.buying_power)} />
          <Stat
            label="Open / Orders"
            value={`${state.positions.length} / ${state.orders.filter((o) => ["working", "partially_filled", "accepted", "submitted"].includes(o.status)).length}`}
            hint={`${state.fills.length} fills to date`}
          />
        </div>
      ) : null}
      {state && state.positions.length > 0 ? (
        <div className="text-xs text-slate-400">
          Held then:{" "}
          {state.positions
            .map((p) => `${p.symbol} ×${p.quantity} @ ${num(p.avg_cost, 2)}`)
            .join(" · ")}
        </div>
      ) : null}
    </div>
  );
}

export default function Brokerage() {
  const account = useApi<Account>("/brokerage/account");
  const positions = useApi<Position[]>("/brokerage/positions");
  const orders = useApi<Order[]>("/brokerage/orders?limit=50");
  const analysis = useApi<Analysis>("/brokerage/portfolio-analysis");
  const [ticking, setTicking] = useState(false);

  const reloadAll = () => {
    account.reload();
    positions.reload();
    orders.reload();
    analysis.reload();
  };

  const tick = async () => {
    setTicking(true);
    try {
      await apiPost("/brokerage/tick", {});
      reloadAll();
    } finally {
      setTicking(false);
    }
  };

  const close = async (symbol: string) => {
    try {
      await apiPost(`/brokerage/positions/${symbol}/close`, {});
      await apiPost("/brokerage/tick", {});
      reloadAll();
    } catch {
      reloadAll();
    }
  };

  const positionCols: Column<Position>[] = [
    { key: "symbol", header: "Symbol" },
    { key: "quantity", header: "Qty", align: "right" },
    { key: "avg_cost", header: "Avg Cost", align: "right", render: (p) => num(p.avg_cost, 2) },
    {
      key: "last_price",
      header: "Last",
      align: "right",
      render: (p) => (p.last_price != null ? num(p.last_price, 2) : "—"),
    },
    { key: "market_value", header: "Value", align: "right", render: (p) => money(p.market_value) },
    {
      key: "unrealized_pnl",
      header: "Unrealized",
      align: "right",
      render: (p) => (
        <span className={p.unrealized_pnl >= 0 ? "text-emerald-400" : "text-bear"}>
          {money(p.unrealized_pnl)}
        </span>
      ),
    },
    {
      key: "todays_gain",
      header: "Today",
      align: "right",
      render: (p) => (
        <span className={p.todays_gain >= 0 ? "text-emerald-400" : "text-bear"}>
          {money(p.todays_gain)}
        </span>
      ),
    },
    {
      key: "risk_multiple",
      header: "R",
      align: "right",
      render: (p) => (p.risk_multiple != null ? num(p.risk_multiple, 2) : "—"),
    },
    {
      key: "stop_price",
      header: "Stop",
      align: "right",
      render: (p) => (p.stop_price != null ? num(p.stop_price, 2) : "—"),
    },
    { key: "days_held", header: "Days", align: "right", render: (p) => num(p.days_held, 1) },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (p) => (
        <button
          onClick={() => void close(p.symbol)}
          className="rounded border border-surface-border px-2 py-0.5 text-[11px] text-bear hover:bg-surface/60"
        >
          Close
        </button>
      ),
    },
  ];

  return (
    <div className="space-y-5 p-5">
      <PageTitle
        title="Brokerage"
        subtitle="The simulated venue: account, orders, positions and the portfolio manager"
      >
        <button onClick={() => void tick()} disabled={ticking} className="btn-ghost px-3 py-1.5 text-xs">
          {ticking ? "Ticking…" : "Process market tick"}
        </button>
      </PageTitle>

      {account.loading ? (
        <Loading />
      ) : account.error ? (
        <ErrorBox message={account.error} />
      ) : account.data ? (
        <AccountStrip account={account.data} />
      ) : null}

      <Card title="Place Order">
        <PlaceOrderForm onDone={reloadAll} />
      </Card>

      <Card title="Open Positions">
        {positions.loading ? (
          <Loading />
        ) : (
          <DataTable
            columns={positionCols}
            rows={positions.data ?? []}
            empty="No open positions."
          />
        )}
      </Card>

      <Card title="Orders">
        {orders.loading ? (
          <Loading />
        ) : (
          <OrderBlotter orders={orders.data ?? []} onChanged={reloadAll} />
        )}
      </Card>

      <Card title="Portfolio Manager">
        {analysis.loading ? (
          <Loading />
        ) : analysis.error ? (
          <ErrorBox message={analysis.error} />
        ) : analysis.data ? (
          <AnalysisPanel analysis={analysis.data} />
        ) : null}
      </Card>

      <Card title="Portfolio Replay">
        <ReplayPanel />
      </Card>
    </div>
  );
}

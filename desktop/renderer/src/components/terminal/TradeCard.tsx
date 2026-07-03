import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiPost } from "../../api/client";
import { money, num } from "../../lib/format";

/**
 * One active-trade card in the Command Center: entry vs price, P/L, stop /
 * targets, risk remaining, health, conviction, the management state and the
 * WHY line — plus the full user-control surface (close, move stop, move
 * target, add, reduce, manual/managed toggle). Every override posts to
 * /trade-lifecycle/{uid}/override, is audited backend-side, and the bot
 * adapts on its next cycle.
 */

export interface TrackedTradeRow {
  trade_uid: string;
  symbol: string;
  status: string;
  management_mode: string;
  instrument: string;
  quantity: number | null;
  entry_price: number;
  stop_price: number;
  targets: { label?: string; price: number; hit?: boolean; user_set?: boolean }[] | null;
  conviction_score: number | null;
  conviction_band: string | null;
  current_health_score: number | null;
  trade_health: string | null;
  recommended_at: string | null;
  last_evaluated_at: string | null;
  last_price?: number | null;
  unrealized_r?: number | null;
  unrealized_pnl?: number | null;
  distance_to_stop_pct?: number | null;
  journal_trade_id: number | null;
  latest_action?: string | null;
  latest_reason?: string | null;
}

const HEALTH_TONE: Record<string, string> = {
  Strong: "text-emerald-400 border-emerald-500/40 bg-emerald-500/10",
  Stable: "text-sky-300 border-sky-500/40 bg-sky-500/10",
  Weakening: "text-amber-300 border-amber-400/40 bg-amber-400/10",
  Broken: "text-rose-400 border-rose-500/40 bg-rose-500/10",
};

function daysHeld(recommendedAt: string | null): number | null {
  if (!recommendedAt) return null;
  const ms = Date.now() - new Date(recommendedAt).getTime();
  return Math.max(Math.round(ms / 86_400_000), 0);
}

type DialogKind = "move_stop" | "move_target" | "reduce" | "add" | "close" | null;

export function TradeCard({
  trade,
  onChanged,
}: {
  trade: TrackedTradeRow;
  onChanged: () => void;
}) {
  const navigate = useNavigate();
  const [dialog, setDialog] = useState<DialogKind>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const price = trade.last_price ?? trade.entry_price;
  const qty = trade.quantity ?? 0;
  const pnl = trade.unrealized_pnl ?? null;
  const nextTarget = (trade.targets ?? []).find((t) => !t.hit) ?? null;
  const riskRemaining = Math.max(price - trade.stop_price, 0) * qty;
  const held = daysHeld(trade.recommended_at);
  const manual = trade.management_mode === "manual";
  const managementState = manual
    ? "Manual (bot advises only)"
    : (trade.latest_action ?? "Holding");

  const override = async (action: string, body: Record<string, unknown> = {}) => {
    setBusy(action);
    setError(null);
    try {
      const result = await apiPost<{ ok: boolean; error?: string; summary?: string }>(
        `/trade-lifecycle/${trade.trade_uid}/override`,
        { action, ...body },
      );
      if (!result.ok) {
        setError(result.error ?? "override refused");
      } else {
        setFlash(result.summary ?? "Applied — logged to the audit trail.");
        window.setTimeout(() => setFlash(null), 3_500);
        onChanged();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
      setDialog(null);
    }
  };

  const controlBtn =
    "rounded border border-surface-border px-2 py-1 text-[11px] text-slate-300 hover:bg-surface/70 disabled:opacity-40";

  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised p-4 shadow-card">
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <button
          onClick={() => navigate(`/trades?symbol=${trade.symbol}`)}
          className="text-lg font-bold tracking-wide text-slate-100 hover:text-accent"
        >
          {trade.symbol}
        </button>
        <span
          className={`rounded border px-2 py-0.5 text-[11px] font-medium ${
            HEALTH_TONE[trade.trade_health ?? ""] ?? "border-surface-border text-slate-400"
          }`}
        >
          {trade.trade_health ?? "unrated"}
          {trade.current_health_score != null ? ` ${Math.round(trade.current_health_score)}` : ""}
        </span>
        <span className="text-[11px] text-slate-500">
          conviction {trade.conviction_score != null ? Math.round(trade.conviction_score) : "—"}
          {trade.conviction_band ? ` (${trade.conviction_band})` : ""}
        </span>
        <span
          className={`ml-auto rounded px-2 py-0.5 text-[11px] font-medium ${
            manual ? "bg-amber-400/15 text-amber-300" : "bg-sky-500/15 text-sky-300"
          }`}
        >
          {manual ? "MANUAL" : "MANAGED"}
        </span>
      </div>

      <div className="mb-2 grid grid-cols-3 gap-x-4 gap-y-1 text-xs sm:grid-cols-6">
        <Cell label="Entry" value={num(trade.entry_price)} />
        <Cell label="Price" value={num(price)} tone={price >= trade.entry_price ? "up" : "down"} />
        <Cell label={`Size (${trade.instrument})`} value={String(qty)} />
        <Cell
          label="P/L"
          value={pnl != null ? money(pnl) : "—"}
          tone={pnl != null ? (pnl >= 0 ? "up" : "down") : undefined}
        />
        <Cell label="Stop" value={num(trade.stop_price)} />
        <Cell
          label="Target"
          value={nextTarget ? num(nextTarget.price) : "—"}
        />
        <Cell label="Risk remaining" value={money(riskRemaining)} />
        <Cell
          label="R"
          value={trade.unrealized_r != null ? `${trade.unrealized_r.toFixed(2)}R` : "—"}
          tone={
            trade.unrealized_r != null ? (trade.unrealized_r >= 0 ? "up" : "down") : undefined
          }
        />
        <Cell label="Days held" value={held != null ? String(held) : "—"} />
        <Cell label="State" value={managementState} wide />
      </div>

      {trade.latest_reason ? (
        <p className="mb-2 text-[11px] leading-relaxed text-slate-400">
          <span className="text-slate-500">Why:</span> {trade.latest_reason}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-1.5">
        <button disabled={!!busy} onClick={() => setDialog("move_stop")} className={controlBtn}>
          Move stop
        </button>
        <button disabled={!!busy} onClick={() => setDialog("move_target")} className={controlBtn}>
          Move target
        </button>
        <button disabled={!!busy} onClick={() => setDialog("add")} className={controlBtn}>
          Add
        </button>
        <button disabled={!!busy} onClick={() => setDialog("reduce")} className={controlBtn}>
          Reduce
        </button>
        <button
          disabled={!!busy}
          onClick={() => void override(manual ? "convert_managed" : "convert_manual")}
          className={controlBtn}
        >
          {busy === "convert_manual" || busy === "convert_managed"
            ? "Switching…"
            : manual
              ? "Return to managed"
              : "Convert to manual"}
        </button>
        <button
          disabled={!!busy}
          onClick={() => setDialog("close")}
          className="rounded border border-rose-500/50 px-2 py-1 text-[11px] text-rose-300 hover:bg-rose-500/10 disabled:opacity-40"
        >
          Close position
        </button>
      </div>

      {flash ? <p className="mt-2 text-[11px] text-emerald-400">{flash}</p> : null}
      {error ? <p className="mt-2 text-[11px] text-rose-400">{error}</p> : null}

      {dialog ? (
        <OverrideDialog
          kind={dialog}
          trade={trade}
          defaultPrice={
            dialog === "move_stop"
              ? trade.stop_price
              : dialog === "move_target" && nextTarget
                ? nextTarget.price
                : price
          }
          busy={!!busy}
          onCancel={() => setDialog(null)}
          onSubmit={(priceValue, quantityValue) =>
            void override(dialog, {
              price: priceValue,
              ...(dialog === "reduce" || dialog === "add" ? { quantity: quantityValue } : {}),
            })
          }
        />
      ) : null}
    </div>
  );
}

function Cell({
  label,
  value,
  tone,
  wide,
}: {
  label: string;
  value: string;
  tone?: "up" | "down";
  wide?: boolean;
}) {
  return (
    <div className={wide ? "col-span-2" : undefined}>
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div
        className={`tabular-nums ${
          tone === "up" ? "text-emerald-400" : tone === "down" ? "text-rose-400" : "text-slate-200"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

const DIALOG_TITLES: Record<string, string> = {
  move_stop: "Move stop — the bot will respect your stop exactly",
  move_target: "Move the next target",
  reduce: "Reduce position",
  add: "Add shares",
  close: "Close position at price",
};

function OverrideDialog({
  kind,
  trade,
  defaultPrice,
  busy,
  onCancel,
  onSubmit,
}: {
  kind: Exclude<DialogKind, null>;
  trade: TrackedTradeRow;
  defaultPrice: number;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (price: number, quantity: number) => void;
}) {
  const [price, setPrice] = useState(String(Math.round(defaultPrice * 100) / 100));
  const [quantity, setQuantity] = useState(
    String(kind === "reduce" ? Math.max(Math.floor((trade.quantity ?? 0) / 2), 1) : 10),
  );
  const needsQty = kind === "reduce" || kind === "add";
  const valid = Number(price) > 0 && (!needsQty || Number(quantity) > 0);

  return (
    <div className="mt-3 rounded border border-surface-border bg-surface/60 p-3">
      <div className="mb-2 text-xs font-medium text-slate-200">{DIALOG_TITLES[kind]}</div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-[10px] uppercase tracking-wide text-slate-500">
          Price
          <input
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            className="mt-1 block w-24 rounded border border-surface-border bg-surface px-2 py-1 text-xs text-slate-200"
          />
        </label>
        {needsQty ? (
          <label className="text-[10px] uppercase tracking-wide text-slate-500">
            Shares
            <input
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              className="mt-1 block w-20 rounded border border-surface-border bg-surface px-2 py-1 text-xs text-slate-200"
            />
          </label>
        ) : null}
        <button
          disabled={busy || !valid}
          onClick={() => onSubmit(Number(price), Number(quantity))}
          className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
        >
          {busy ? "Applying…" : "Apply (logged)"}
        </button>
        <button
          onClick={onCancel}
          className="rounded border border-surface-border px-3 py-1.5 text-xs text-slate-300"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

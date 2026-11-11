import { useEffect, useState } from "react";

import { apiPost, apiPut } from "../../api/client";
import type { MarketGate, Position, Signal } from "../../api/today";
import { useAction } from "../../hooks/useAction";
import { price, usd } from "./common";

interface TakeResult {
  ok: boolean;
  error?: string;
  shares?: number;
  entry_price?: number;
  stop_price?: number;
}

interface CloseResult {
  ok: boolean;
  error?: string;
  exit_price?: number;
  realized_pnl?: number | null;
}

/** "Scan now": pull fresh prices and rebuild today's signals, with live progress. */
export function ScanButton({ onDone, label = "Scan now" }: { onDone?: () => void; label?: string }) {
  const { job, running, start } = useAction("/actions/scan", () => onDone?.());
  return (
    <span className="inline-flex items-center gap-2.5">
      {job && running ? (
        <span className="text-xs text-slate-400">
          {Math.round((job.progress ?? 0) * 100)}% · {job.message}
        </span>
      ) : null}
      {job && !running && job.status === "failed" ? (
        <span className="max-w-xs truncate text-xs text-bear" title={job.error ?? ""}>
          Scan failed: {job.error}
        </span>
      ) : null}
      <button className="btn-ghost" disabled={running} onClick={() => void start({})}>
        {running ? (
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white" />
        ) : null}
        {running ? "Scanning…" : label}
      </button>
    </span>
  );
}

/**
 * The Auto Pilot switch. ON = the app buys each day's signals and sells at the
 * stop / trend exit by itself (paper money). Turning it on runs the backend's
 * preflight; a refusal is shown verbatim rather than silently ignored.
 */
export function AutopilotSwitch({ enabled, onChange }: { enabled: boolean; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toggle = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await apiPut("/settings/autopilot", { enabled: !enabled });
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "could not change Auto Pilot");
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="inline-flex flex-col items-end gap-1">
      <button
        role="switch"
        aria-checked={enabled}
        disabled={busy}
        onClick={() => void toggle()}
        className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[13px] font-medium transition-colors disabled:opacity-60 ${
          enabled
            ? "border-bull/40 bg-bull/10 text-bull hover:bg-bull/20"
            : "border-surface-edge/70 text-slate-300 hover:bg-surface-raised"
        }`}
      >
        <span
          className={`relative h-4 w-7 rounded-full transition-colors ${enabled ? "bg-bull/70" : "bg-surface-edge"}`}
        >
          <span
            className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all ${enabled ? "left-3.5" : "left-0.5"}`}
          />
        </span>
        Auto Pilot {enabled ? "on" : "off"}
      </button>
      {error ? <span className="max-w-xs text-right text-[11px] text-bear">{error}</span> : null}
    </span>
  );
}

function Modal({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-md cursor-default rounded-card border border-surface-edge bg-surface-raised p-5 text-left shadow-pop">
        {children}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5 text-[13px]">
      <span className="text-slate-400">{label}</span>
      <span className="tabular-nums text-slate-100">{value}</span>
    </div>
  );
}

/**
 * Buy a signal on paper. Opens a confirmation that spells out the whole trade
 * in dollars — what is bought, where it is sold if wrong, and what that costs —
 * with the share count editable (risk recomputed live).
 */
export function BuyButton({
  signal,
  market,
  slotsFree,
  onDone,
  size = "md",
}: {
  signal: Signal;
  market: MarketGate;
  slotsFree: number;
  onDone: () => void;
  size?: "sm" | "md";
}) {
  const [open, setOpen] = useState(false);
  const [shares, setShares] = useState<string>(String(signal.shares ?? ""));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (signal.held) {
    return <span className="text-[12px] text-slate-500">You own it</span>;
  }
  const blocked = !market.entries_allowed
    ? "The market is in a downtrend — the rules say don't buy."
    : slotsFree <= 0
      ? "Your book is full."
      : signal.entry == null || signal.stop == null
        ? "No plan yet — scan again."
        : null;

  const qty = Number.parseInt(shares, 10);
  const valid = Number.isFinite(qty) && qty > 0;
  const entry = signal.entry ?? 0;
  const stop = signal.stop ?? 0;
  const cost = valid ? qty * entry : null;
  const risk = valid ? qty * (entry - stop) : null;

  const confirm = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const result = await apiPost<TakeResult>("/actions/take-trade", {
        symbol: signal.symbol,
        quantity: valid ? qty : undefined,
      });
      if (!result.ok) {
        setError(result.error ?? "the trade was refused");
        return;
      }
      setOpen(false);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "request failed");
    } finally {
      setBusy(false);
    }
  };

  const cls =
    size === "sm"
      ? "btn bg-accent-soft px-2.5 py-1 text-xs text-white hover:bg-accent"
      : "btn-primary";
  return (
    <>
      <button
        className={cls}
        onClick={() => {
          setShares(String(signal.shares ?? ""));
          setError(null);
          setOpen(true);
        }}
      >
        Buy
      </button>
      {open ? (
        <Modal onClose={() => setOpen(false)}>
          <h3 className="text-base font-semibold text-slate-100">Buy {signal.symbol} (paper)</h3>
          <p className="mt-1 text-[13px] leading-snug text-slate-400">{signal.why}.</p>
          {blocked ? (
            <div className="mt-3 rounded-md border border-neutral/30 bg-neutral/10 px-3 py-2 text-[13px] text-neutral">
              {blocked} You can still buy manually, but this trade is outside the tested rules.
            </div>
          ) : null}
          <div className="mt-4 divide-y divide-surface-border/60">
            <div className="flex items-center justify-between gap-4 py-1.5 text-[13px]">
              <label htmlFor="buy-shares" className="text-slate-400">
                Shares
              </label>
              <input
                id="buy-shares"
                type="number"
                min={1}
                value={shares}
                onChange={(e) => setShares(e.target.value)}
                className="field w-28 text-right"
                autoFocus
              />
            </div>
            <Row label="Price (about)" value={price(signal.entry)} />
            <Row label="Cost" value={usd(cost)} />
            <Row
              label="Stop — sold automatically at"
              value={
                <>
                  {price(signal.stop)}{" "}
                  <span className="text-slate-500">
                    ({signal.stop_pct != null ? `−${signal.stop_pct.toFixed(1)}%` : "—"})
                  </span>
                </>
              }
            />
            <Row
              label="If the stop is hit you lose about"
              value={<span className="text-bear">{usd(risk)}</span>}
            />
            <Row
              label="Otherwise held until it closes below"
              value={
                <>
                  {price(signal.exit_level)} <span className="text-slate-500">(50-day low)</span>
                </>
              }
            />
          </div>
          {signal.shares != null && valid && qty !== signal.shares ? (
            <p className="mt-2 text-[12px] text-slate-500">
              The rules suggest {signal.shares} shares (0.5% of the account at risk).
            </p>
          ) : null}
          {error ? <p className="mt-3 text-[13px] text-bear">{error}</p> : null}
          <div className="mt-5 flex justify-end gap-2">
            <button className="btn-ghost" disabled={busy} onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button className="btn-primary" disabled={busy || !valid} onClick={() => void confirm()}>
              {busy ? "Buying…" : `Buy ${valid ? qty : ""} shares`}
            </button>
          </div>
        </Modal>
      ) : null}
    </>
  );
}

/** Sell an open paper position at the last known price (asks first). */
export function SellButton({ position, onDone }: { position: Position; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const confirm = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const result = await apiPost<CloseResult>("/actions/close-trade", {
        trade_uid: position.trade_uid,
      });
      if (!result.ok) {
        setError(result.error ?? "the sale was refused");
        return;
      }
      setOpen(false);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "request failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        className="btn border border-surface-edge/60 px-2.5 py-1 text-xs text-slate-300 hover:border-bear/50 hover:text-bear"
        onClick={() => {
          setError(null);
          setOpen(true);
        }}
      >
        Sell
      </button>
      {open ? (
        <Modal onClose={() => setOpen(false)}>
          <h3 className="text-base font-semibold text-slate-100">
            Sell {position.shares} {position.symbol} now?
          </h3>
          <p className="mt-1 text-[13px] leading-snug text-slate-400">
            This closes the paper position at the last known price, about{" "}
            {price(position.last_price)}. The rules would keep holding until a close below{" "}
            {price(position.sell_below)} — selling early is your call.
          </p>
          <div className="mt-4 divide-y divide-surface-border/60">
            <Row label="Bought at" value={price(position.entry_price)} />
            <Row
              label="Result if sold now"
              value={
                <span className={position.pnl >= 0 ? "text-bull" : "text-bear"}>
                  {position.pnl >= 0 ? "+" : "−"}
                  {usd(Math.abs(position.pnl))}
                </span>
              }
            />
          </div>
          {error ? <p className="mt-3 text-[13px] text-bear">{error}</p> : null}
          <div className="mt-5 flex justify-end gap-2">
            <button className="btn-ghost" disabled={busy} onClick={() => setOpen(false)}>
              Keep holding
            </button>
            <button
              className="btn border border-bear/50 bg-bear/10 text-bear hover:bg-bear/20"
              disabled={busy}
              onClick={() => void confirm()}
            >
              {busy ? "Selling…" : "Sell position"}
            </button>
          </div>
        </Modal>
      ) : null}
    </>
  );
}

import { useEffect, useState } from "react";

import { apiGet, apiPost } from "../api/client";

interface ActionResult {
  ok: boolean;
  error?: string;
  symbol?: string;
  shares?: number;
  entry_price?: number;
  stop_price?: number;
  exit_price?: number;
  realized_r?: number | null;
  created?: boolean;
  trade_uid?: string;
}

interface PlanSizing {
  entry: number;
  stop: number;
  suggested_shares: number;
}

/**
 * A small confirm step before taking a paper trade: shares prefilled from the
 * plan's suggested size, editable, with the dollar risk recomputed live so an
 * override is an informed choice rather than a blind number.
 */
function TakeSizeDialog({
  symbol,
  onConfirm,
  onCancel,
  busy,
}: {
  symbol: string;
  onConfirm: (quantity: number | null) => void;
  onCancel: () => void;
  busy: boolean;
}) {
  const [plan, setPlan] = useState<PlanSizing | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [shares, setShares] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    apiGet<PlanSizing>(`/tradeplan/${symbol}`)
      .then((p) => {
        if (cancelled) return;
        setPlan(p);
        setShares(String(p.suggested_shares));
      })
      .catch((e: unknown) => {
        if (!cancelled) setPlanError(e instanceof Error ? e.message : "no plan available");
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  const qty = Number.parseInt(shares, 10);
  const valid = Number.isFinite(qty) && qty > 0;
  const riskPerShare = plan ? plan.entry - plan.stop : null;
  const risk = valid && riskPerShare != null ? qty * riskPerShare : null;

  return (
    <span className="inline-flex flex-wrap items-center gap-2 rounded border border-surface-border bg-surface-raised px-2 py-1.5">
      <span className="text-xs text-slate-400">Shares</span>
      <input
        type="number"
        min={1}
        value={shares}
        onChange={(e) => setShares(e.target.value)}
        className="w-20 rounded border border-surface-border bg-surface px-2 py-0.5 text-xs text-slate-200 outline-none focus:border-accent"
        autoFocus
      />
      {plan ? (
        <span className="text-[11px] text-slate-500">
          suggested {plan.suggested_shares} · entry {plan.entry.toFixed(2)} · stop{" "}
          {plan.stop.toFixed(2)}
          {risk != null ? (
            <>
              {" "}
              · risk <span className="text-slate-300">${risk.toFixed(0)}</span>
            </>
          ) : null}
        </span>
      ) : planError ? (
        <span className="text-[11px] text-amber-400">plan sizing unavailable — using default</span>
      ) : (
        <span className="text-[11px] text-slate-500">loading plan…</span>
      )}
      <button
        disabled={busy || (!valid && plan != null)}
        onClick={() => onConfirm(valid ? qty : null)}
        className="btn border border-bull/40 bg-bull/10 px-2.5 py-1 text-xs text-bull hover:bg-bull/20"
      >
        {busy ? "Taking…" : "Confirm"}
      </button>
      <button disabled={busy} onClick={onCancel} className="btn-quiet px-2 py-1 text-xs">
        Cancel
      </button>
    </span>
  );
}

/**
 * The "do something with this recommendation" buttons: take the trade on paper
 * (opens a journal trade from the plan, tracks + links it) or track the thesis
 * only. Paper only — no live orders exist anywhere in the app.
 */
export function TradeActions({
  symbol,
  onDone,
  compact = false,
}: {
  symbol: string;
  onDone?: () => void;
  compact?: boolean;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [sizing, setSizing] = useState(false);

  const run = async (path: string, label: string, quantity?: number | null): Promise<void> => {
    setBusy(label);
    setMessage(null);
    try {
      const body: Record<string, unknown> = { symbol };
      if (quantity != null) body.quantity = quantity;
      const result = await apiPost<ActionResult>(path, body);
      setFailed(!result.ok);
      if (!result.ok) {
        setMessage(result.error ?? "failed");
      } else if (path.includes("take-trade")) {
        setSizing(false);
        setMessage(
          `Paper trade opened: ${result.shares} sh @ ${result.entry_price} (stop ${result.stop_price})`,
        );
      } else {
        setMessage(result.created ? "Now tracking the thesis" : "Already tracked");
      }
      onDone?.();
    } catch (err) {
      setFailed(true);
      setMessage(err instanceof Error ? err.message : "request failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={`flex items-center gap-2 ${compact ? "" : "flex-wrap"}`}>
      {sizing ? (
        <TakeSizeDialog
          symbol={symbol}
          busy={busy === "take"}
          onConfirm={(quantity) => void run("/actions/take-trade", "take", quantity)}
          onCancel={() => setSizing(false)}
        />
      ) : (
        <button
          disabled={busy != null}
          onClick={() => {
            setMessage(null);
            setSizing(true);
          }}
          className="btn border border-bull/40 bg-bull/10 px-2.5 py-1 text-xs text-bull hover:bg-bull/20"
        >
          Take paper trade
        </button>
      )}
      <button
        disabled={busy != null}
        onClick={() => void run("/actions/track-trade", "track")}
        className="btn-quiet border border-surface-border px-2.5 py-1"
      >
        {busy === "track" ? "Tracking…" : "Track only"}
      </button>
      {message ? (
        <span className={`text-xs ${failed ? "text-bear" : "text-emerald-400"}`}>{message}</span>
      ) : null}
    </div>
  );
}

/** Close an open paper trade at the last known price (realizes the outcome). */
export function CloseTradeButton({
  tradeUid,
  onDone,
}: {
  tradeUid: string;
  onDone?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const run = async (): Promise<void> => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await apiPost<ActionResult>("/actions/close-trade", {
        trade_uid: tradeUid,
      });
      setFailed(!result.ok);
      setMessage(
        result.ok
          ? `Closed @ ${result.exit_price}${result.realized_r != null ? ` (${result.realized_r >= 0 ? "+" : ""}${result.realized_r.toFixed(2)}R)` : ""}`
          : (result.error ?? "failed"),
      );
      onDone?.();
    } catch (err) {
      setFailed(true);
      setMessage(err instanceof Error ? err.message : "request failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="flex items-center gap-2">
      <button
        disabled={busy}
        onClick={() => void run()}
        className="btn-danger px-2.5 py-1 text-xs"
      >
        {busy ? "Closing…" : "Close paper trade"}
      </button>
      {message ? (
        <span className={`text-xs ${failed ? "text-bear" : "text-emerald-400"}`}>{message}</span>
      ) : null}
    </span>
  );
}

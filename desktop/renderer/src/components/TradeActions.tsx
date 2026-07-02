import { useState } from "react";

import { apiPost } from "../api/client";

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

  const run = async (path: string, label: string): Promise<void> => {
    setBusy(label);
    setMessage(null);
    try {
      const result = await apiPost<ActionResult>(path, { symbol });
      setFailed(!result.ok);
      if (!result.ok) {
        setMessage(result.error ?? "failed");
      } else if (path.includes("take-trade")) {
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
      <button
        disabled={busy != null}
        onClick={() => void run("/actions/take-trade", "take")}
        className="btn border border-bull/40 bg-bull/10 px-2.5 py-1 text-xs text-bull hover:bg-bull/20"
      >
        {busy === "take" ? "Taking…" : "Take paper trade"}
      </button>
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

import { useEffect, useRef, useState } from "react";

import { useApi } from "../hooks/useApi";
import { useSystemTimezone } from "../hooks/useSystemTimezone";
import { countdown, timeInZone } from "../lib/format";

const MARKET_TZ = "America/New_York";

interface Clock {
  state: string;
  utc: string;
  market_time: string;
  market_tz: string;
  next_market_open: string;
  next_market_close: string;
  next_premarket: string;
  seconds_to_market_open: number;
  seconds_to_market_close: number;
  seconds_to_premarket: number;
  seconds_to_next_scan: number | null;
  daemon_running: boolean;
}

const STATE_LABEL: Record<string, string> = {
  premarket: "Premarket",
  regular: "Open",
  after_hours: "After Hours",
  closed: "Closed",
};

const STATE_CLASS: Record<string, string> = {
  premarket: "bg-neutral/20 text-neutral",
  regular: "bg-bull/20 text-bull",
  after_hours: "bg-amber-500/20 text-amber-300",
  closed: "bg-slate-600/30 text-slate-400",
};

/**
 * Live clock + market status: local time (OS timezone + locale), market time
 * (America/New_York), the market state, and ticking countdowns. Updates every
 * second; follows OS timezone changes live (no restart).
 */
export function LiveClock() {
  const localTz = useSystemTimezone();
  const clock = useApi<Clock>("/daemon/clock", { refreshMs: 30_000 });
  const [now, setNow] = useState<Date>(() => new Date());
  // Seconds elapsed since the last /daemon/clock payload — drives the countdowns
  // between polls without drifting from the backend's authoritative numbers.
  const fetchedAt = useRef<number>(Date.now());

  useEffect(() => {
    fetchedAt.current = Date.now();
  }, [clock.data]);

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1_000);
    return () => window.clearInterval(id);
  }, []);

  const data = clock.data;
  const elapsed = (now.getTime() - fetchedAt.current) / 1000;
  const remaining = (seconds: number | null | undefined): number | null =>
    seconds == null ? null : Math.max(0, seconds - elapsed);

  const state = data?.state ?? "closed";

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-surface-border bg-surface/40 px-3 py-1.5 text-xs">
      <span
        className={`rounded px-1.5 py-0.5 font-medium ${STATE_CLASS[state] ?? STATE_CLASS["closed"]}`}
      >
        {STATE_LABEL[state] ?? state}
      </span>
      <span className="text-slate-400">
        Local{" "}
        <span className="font-medium tabular-nums text-slate-100">
          {timeInZone(now, localTz)}
        </span>
      </span>
      <span className="text-slate-400">
        Market{" "}
        <span className="font-medium tabular-nums text-slate-100">
          {timeInZone(now, MARKET_TZ)}
        </span>
      </span>
      {data ? (
        <>
          {data.seconds_to_next_scan != null && data.daemon_running ? (
            <span className="text-slate-500">
              Next scan{" "}
              <span className="tabular-nums text-slate-300">
                {countdown(remaining(data.seconds_to_next_scan))}
              </span>
            </span>
          ) : null}
          {state === "regular" ? (
            <span className="text-slate-500">
              Close{" "}
              <span className="tabular-nums text-slate-300">
                {countdown(remaining(data.seconds_to_market_close))}
              </span>
            </span>
          ) : (
            <>
              <span className="text-slate-500">
                Open{" "}
                <span className="tabular-nums text-slate-300">
                  {countdown(remaining(data.seconds_to_market_open))}
                </span>
              </span>
              {state === "closed" ? (
                <span className="text-slate-500">
                  Premarket{" "}
                  <span className="tabular-nums text-slate-300">
                    {countdown(remaining(data.seconds_to_premarket))}
                  </span>
                </span>
              ) : null}
            </>
          )}
        </>
      ) : null}
      <span className="text-slate-600">{localTz}</span>
    </div>
  );
}

import type { PortfolioSnapshot } from "../api/types";
import { useApi } from "../hooks/useApi";
import { date } from "../lib/format";
import { useWorkspace } from "../state/workspace";

interface Health {
  status: string;
}

interface MarketSession {
  label: string;
  tone: string;
}

/** Classify the current US market session (computed client-side in America/New_York). */
function marketSession(now: Date): MarketSession {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour12: false,
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).formatToParts(now);

  const get = (type: Intl.DateTimeFormatPartTypes): string =>
    parts.find((p) => p.type === type)?.value ?? "";

  const weekday = get("weekday");
  if (weekday === "Sat" || weekday === "Sun") return { label: "Closed", tone: "text-slate-500" };

  // "24" can appear for midnight in some environments; normalise to 0.
  const hour = Number(get("hour")) % 24;
  const minute = Number(get("minute"));
  const mins = hour * 60 + minute;

  const open = 9 * 60 + 30; // 09:30
  const close = 16 * 60; // 16:00
  const preOpen = 4 * 60; // 04:00
  const afterClose = 20 * 60; // 20:00

  if (mins >= open && mins < close) return { label: "Open", tone: "text-bull" };
  if (mins >= preOpen && mins < open) return { label: "Pre-open", tone: "text-neutral" };
  if (mins >= close && mins < afterClose) return { label: "After-hours", tone: "text-neutral" };
  return { label: "Closed", tone: "text-slate-500" };
}

export function StatusBar() {
  const { runId, symbol } = useWorkspace();
  const health = useApi<Health>("/health");
  const snaps = useApi<PortfolioSnapshot[]>("/portfolio/snapshots?limit=400");
  const ok = health.data?.status === "ok";

  const session = marketSession(new Date());
  const latest =
    snaps.data && snaps.data.length > 0 ? snaps.data[snaps.data.length - 1] : null;

  return (
    <footer className="flex h-7 items-center gap-4 border-t border-surface-border bg-surface-sunken px-4 text-[11px] text-slate-500">
      <span className="flex items-center gap-1.5">
        <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-bull" : "bg-bear"}`} />
        backend {ok ? "connected" : "down"}
      </span>
      <span className="flex items-center gap-1.5">
        <span className={session.tone}>●</span>
        market {session.label.toLowerCase()}
      </span>
      <span>data {latest ? date(latest.session_date) : "—"}</span>
      {runId ? <span>run {runId}</span> : null}
      {symbol ? <span>focus {symbol}</span> : null}
      <span className="ml-auto text-slate-600">
        <kbd className="rounded border border-surface-border px-1">⌘K</kbd> search ·{" "}
        <kbd className="rounded border border-surface-border px-1">?</kbd> shortcuts
      </span>
    </footer>
  );
}

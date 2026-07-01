import { useEffect, useMemo, useState } from "react";

import type {
  ActivityEntry,
  DaemonStatus,
  LiveAlert,
  ScanDelta,
  ScanStatRow,
} from "../api/types";
import { apiPost } from "../api/client";
import { Card } from "../components/Card";
import { DeltaValue } from "../components/DeltaValue";
import { useApi } from "../hooks/useApi";
import { fmtTime, num, signed } from "../lib/format";

const SEVERITY_CLASS: Record<string, string> = {
  info: "bg-slate-600/30 text-slate-300",
  warning: "bg-amber-500/20 text-amber-300",
  critical: "bg-bear/20 text-bear",
};

/** The live strip + panels: daemon status, movers, alerts, activity, performance. */
export function LivePulse() {
  const daemon = useApi<DaemonStatus>("/daemon/status", { refreshMs: 3_000 });
  const deltas = useApi<ScanDelta[]>("/deltas?since_hours=48&limit=300", { refreshMs: 5_000 });
  const alerts = useApi<LiveAlert[]>("/alerts?limit=8", { refreshMs: 10_000 });
  const activity = useApi<ActivityEntry[]>("/activity?limit=12", { refreshMs: 10_000 });
  const stats = useApi<ScanStatRow[]>("/scan-stats?limit=1", { refreshMs: 10_000 });

  const rows = deltas.data ?? [];
  const top = (metric: string, n = 5): ScanDelta[] =>
    rows
      .filter((d) => d.metric === metric && d.delta != null)
      .sort((a, b) => Math.abs(b.delta ?? 0) - Math.abs(a.delta ?? 0))
      .slice(0, n);
  const gainers = useMemo(
    () =>
      rows
        .filter((d) => d.metric === "price" && d.delta != null && (d.previous_value ?? 0) > 0)
        .map((d) => ({ ...d, pct: ((d.delta ?? 0) / (d.previous_value ?? 1)) * 100 }))
        .sort((a, b) => b.pct - a.pct),
    [rows],
  );
  const movers = rows
    .filter((d) => d.metric.startsWith("watchlist_rank"))
    .slice(0, 5);
  const stat = stats.data?.[0] ?? null;

  return (
    <div className="space-y-4">
      <DaemonStrip status={daemon.data} error={daemon.error} />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card title="Top gainers / losers">
          <MoverList rows={gainers.slice(0, 3)} suffix="%" />
          <div className="my-1 border-t border-surface-border/40" />
          <MoverList rows={gainers.slice(-3).reverse()} suffix="%" />
          {gainers.length === 0 ? <Empty /> : null}
        </Card>
        <Card title="Conviction changes">
          <DeltaList rows={top("conviction")} />
        </Card>
        <Card title="Health changes">
          <DeltaList rows={top("health")} warn />
        </Card>
        <Card title="Watchlist movers">
          {movers.length === 0 ? (
            <Empty />
          ) : (
            <ul className="space-y-1 text-xs">
              {movers.map((d, i) => (
                <li key={i} className="flex justify-between text-slate-300">
                  <span>{d.symbol}</span>
                  <span className="text-slate-400">{d.reason}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <Card title="Recent alerts">
          {(alerts.data ?? []).length === 0 ? (
            <Empty />
          ) : (
            <ul className="space-y-1.5 text-xs">
              {(alerts.data ?? []).map((a) => (
                <li key={a.id} className="flex items-start gap-2">
                  <span
                    className={`mt-0.5 rounded px-1 py-0.5 text-[10px] font-medium ${SEVERITY_CLASS[a.severity] ?? ""}`}
                  >
                    {a.severity}
                  </span>
                  <span className="flex-1">
                    <span className="text-slate-200">{a.title}</span>
                    <span className="ml-1 text-slate-500">{a.description}</span>
                  </span>
                  <span className="text-slate-600">{fmtTime(a.ts)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Activity feed">
          {(activity.data ?? []).length === 0 ? (
            <Empty />
          ) : (
            <ul className="space-y-1.5 text-xs">
              {(activity.data ?? []).map((a) => (
                <li key={a.id} className="flex items-start gap-2 text-slate-300">
                  <span className="rounded bg-surface-border/60 px-1 py-0.5 text-[10px] text-slate-400">
                    {a.category}
                  </span>
                  <span className="flex-1">{a.text}</span>
                  <span className="text-slate-600">{fmtTime(a.ts)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Scan performance">
          {stat == null ? (
            <Empty />
          ) : (
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-300">
              <span>Duration</span>
              <span className={`text-right tabular-nums ${stat.degraded ? "text-amber-400" : ""}`}>
                {num(stat.duration_ms / 1000, 1)}s{stat.degraded ? " (degraded)" : ""}
              </span>
              <span>Symbols</span>
              <span className="text-right tabular-nums">
                {stat.symbols_processed} ({stat.symbols_failed} failed)
              </span>
              <span>Skipped / recomputed</span>
              <span className="text-right tabular-nums">
                {stat.symbols_skipped ?? "—"} / {stat.symbols_recomputed ?? "—"}
              </span>
              <span>Cache hit rate</span>
              <span className="text-right tabular-nums">
                {stat.cache_hit_rate != null ? `${num(stat.cache_hit_rate * 100, 0)}%` : "—"}
              </span>
              <span>Provider latency</span>
              <span className="text-right tabular-nums">
                {stat.provider_latency_ms != null ? `${num(stat.provider_latency_ms, 0)}ms` : "—"}
              </span>
              <span>Memory</span>
              <span className="text-right tabular-nums">
                {stat.memory_mb != null ? `${num(stat.memory_mb, 0)} MB` : "—"}
              </span>
              <span>DB writes / alerts</span>
              <span className="text-right tabular-nums">
                {stat.db_writes} / {stat.alerts_generated}
              </span>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

function Empty() {
  return <div className="py-3 text-center text-xs text-slate-600">nothing yet</div>;
}

function MoverList({ rows, suffix }: { rows: (ScanDelta & { pct: number })[]; suffix: string }) {
  return (
    <ul className="space-y-1 text-xs">
      {rows.map((d, i) => (
        <li key={i} className="flex justify-between text-slate-300">
          <span>{d.symbol}</span>
          <span className={`tabular-nums ${d.pct >= 0 ? "text-emerald-400" : "text-bear"}`}>
            {signed(d.pct, 2)}
            {suffix}
          </span>
        </li>
      ))}
    </ul>
  );
}

function DeltaList({ rows, warn = false }: { rows: ScanDelta[]; warn?: boolean }) {
  if (rows.length === 0) return <Empty />;
  return (
    <ul className="space-y-1 text-xs">
      {rows.map((d, i) => (
        <li key={i} className="flex items-center justify-between gap-2 text-slate-300">
          <span>{d.symbol}</span>
          <DeltaValue
            value={d.new_value}
            previous={d.previous_value}
            digits={0}
            warn={warn && (d.delta ?? 0) < 0}
          />
        </li>
      ))}
    </ul>
  );
}

/** Worker status + countdown + controls (pause/resume/scan now). */
function DaemonStrip({ status, error }: { status: DaemonStatus | null; error: string | null }) {
  const [countdown, setCountdown] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setCountdown(status?.seconds_to_next_wake ?? null);
    const id = window.setInterval(
      () => setCountdown((s) => (s != null && s > 0 ? s - 1 : s)),
      1_000,
    );
    return () => window.clearInterval(id);
  }, [status?.seconds_to_next_wake, status?.version]);

  const control = async (path: string): Promise<void> => {
    setBusy(true);
    try {
      await apiPost(path, {});
    } finally {
      setBusy(false);
    }
  };

  if (error && !status) {
    return (
      <div className="rounded-lg border border-surface-border px-3 py-2 text-xs text-slate-500">
        Market daemon is not running (start the app with MRP_DAEMON_AUTOSTART=1).
      </div>
    );
  }
  if (!status) return null;

  const stateLabel = status.paused
    ? "paused"
    : status.scanning_now
      ? "scanning…"
      : status.running
        ? "idle"
        : "stopped";
  const dot = status.paused
    ? "bg-amber-400"
    : status.scanning_now
      ? "bg-accent animate-pulse"
      : status.running
        ? "bg-emerald-400"
        : "bg-bear";

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border border-surface-border bg-surface/40 px-3 py-2 text-xs">
      <span className="flex items-center gap-1.5 font-medium text-slate-200">
        <span className={`h-2 w-2 rounded-full ${dot}`} />
        Daemon {stateLabel}
      </span>
      <span className="text-slate-400">
        Market: <span className="text-slate-200">{status.market_state}</span>
      </span>
      <span className="text-slate-400">
        Last scan: <span className="text-slate-200">{fmtTime(status.last_scan_at)}</span>
      </span>
      <span className="text-slate-400">
        Next in:{" "}
        <span className="tabular-nums text-slate-200">
          {countdown != null ? `${Math.max(0, Math.round(countdown))}s` : "—"}
        </span>
      </span>
      <span className="text-slate-400">
        Cycles: <span className="tabular-nums text-slate-200">{status.cycles}</span>
      </span>
      {status.last_error ? (
        <span className="max-w-[24rem] truncate text-bear" title={status.last_error}>
          {status.last_error}
        </span>
      ) : null}
      <span className="ml-auto flex items-center gap-1.5">
        <button
          disabled={busy}
          onClick={() => void control(status.paused ? "/daemon/resume" : "/daemon/pause")}
          className="rounded border border-surface-border px-2 py-0.5 text-slate-300 hover:bg-surface disabled:opacity-50"
        >
          {status.paused ? "Resume" : "Pause"}
        </button>
        <button
          disabled={busy}
          onClick={() => void control("/daemon/scan-now")}
          className="rounded border border-accent/50 px-2 py-0.5 text-accent hover:bg-accent/10 disabled:opacity-50"
        >
          Scan now
        </button>
      </span>
    </div>
  );
}

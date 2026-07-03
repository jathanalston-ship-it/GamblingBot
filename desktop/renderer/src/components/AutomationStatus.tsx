import { useEffect, useState } from "react";

import { Stat } from "./Stat";
import { useApi } from "../hooks/useApi";

interface AutopilotSettings {
  enabled: boolean;
  prevent_sleep: boolean;
}

interface DaemonStatus {
  running: boolean;
  paused: boolean;
  market_state: string;
  last_scan_at: string | null;
  next_wake_at: string | null;
  seconds_to_next_wake: number | null;
}

interface HealthCheck {
  name: string;
  status: string; // healthy | warning | critical
  detail: string;
}

interface AutomationHealth {
  overall: string;
  checks: HealthCheck[];
}

interface RecoveryRecord {
  recovered_at: string;
  downtime_seconds: number;
  missed_scans: number;
}

interface RecoveryOut {
  recovered_this_startup: boolean;
  last_recovery: RecoveryRecord | null;
}

interface BlockerStatus {
  sleepPrevented: boolean;
}

function tone(status: string): string {
  if (status === "healthy") return "text-bull";
  if (status === "warning") return "text-amber-400";
  return "text-bear";
}

function dot(status: string): string {
  if (status === "healthy") return "bg-bull";
  if (status === "warning") return "bg-amber-400";
  return "bg-bear";
}

/**
 * The Command Center automation strip: Automation Status, Sleep Prevention,
 * Backend Status, Last Scan, Next Scan — plus the per-subsystem Automation
 * Health grades and the crash-recovery banner ("Recovered after restart —
 * missed N scans — resuming").
 */
export function AutomationStatus() {
  const autopilot = useApi<AutopilotSettings>("/settings/autopilot", { refreshMs: 60_000 });
  const daemon = useApi<DaemonStatus>("/daemon/status", { refreshMs: 15_000 });
  const health = useApi<AutomationHealth>("/automation/health", { refreshMs: 120_000 });
  const recovery = useApi<RecoveryOut>("/automation/recovery");
  const [blocker, setBlocker] = useState<BlockerStatus | null>(null);
  const [expanded, setExpanded] = useState(false);

  // The live power-save blocker is owned by the Electron shell.
  useEffect(() => {
    let cancelled = false;
    const read = () => {
      window.mrp?.automation
        ?.status()
        .then((s) => {
          if (!cancelled) setBlocker(s);
        })
        .catch(() => undefined);
    };
    read();
    const timer = window.setInterval(read, 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const active = autopilot.data?.enabled === true;
  const sleepLabel = !active
    ? "OS default"
    : blocker
      ? blocker.sleepPrevented
        ? "Sleep Prevented"
        : autopilot.data?.prevent_sleep === false
          ? "Disabled by setting"
          : "Not held"
      : autopilot.data?.prevent_sleep === false
        ? "Disabled by setting"
        : "Prevented (desktop app)";

  const rec = recovery.data?.recovered_this_startup ? recovery.data?.last_recovery : null;

  return (
    <div className="space-y-3">
      {rec ? (
        <div className="flex flex-wrap items-center gap-2 rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-300">
          <span className="font-semibold">Recovered After Restart</span>
          <span className="text-amber-400/90">
            Recovered successfully — down {Math.round(rec.downtime_seconds / 60)} min, missed{" "}
            {rec.missed_scans} scan{rec.missed_scans === 1 ? "" : "s"}. Resuming…
          </span>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat
          label="Automation Status"
          value={
            <span className={active ? "text-bull" : "text-slate-400"}>
              {active ? "Automation Mode Active" : "Off"}
            </span>
          }
        />
        <Stat
          label="Sleep Prevention"
          value={
            <span className={active && sleepLabel.startsWith("Sleep") ? "text-bull" : "text-slate-300"}>
              {sleepLabel}
            </span>
          }
          hint="display sleep / screen saver / lock stay allowed"
        />
        <Stat
          label="Backend Status"
          value={
            daemon.error ? (
              <span className="text-bear">unreachable</span>
            ) : (
              <span className="text-bull">running</span>
            )
          }
          hint={
            daemon.data
              ? `daemon ${daemon.data.running ? (daemon.data.paused ? "paused" : "running") : "stopped"} · ${daemon.data.market_state}`
              : undefined
          }
        />
        <Stat
          label="Last Scan"
          value={
            daemon.data?.last_scan_at
              ? new Date(daemon.data.last_scan_at).toLocaleTimeString()
              : "—"
          }
        />
        <Stat
          label="Next Scan"
          value={
            daemon.data?.seconds_to_next_wake != null
              ? `${Math.max(Math.round(daemon.data.seconds_to_next_wake), 0)}s`
              : "—"
          }
          hint={
            daemon.data?.next_wake_at
              ? new Date(daemon.data.next_wake_at).toLocaleTimeString()
              : undefined
          }
        />
      </div>

      <div>
        <button
          onClick={() => setExpanded((e) => !e)}
          className="flex items-center gap-2 text-xs text-slate-400 hover:text-slate-200"
        >
          <span
            className={`inline-block h-2 w-2 rounded-full ${dot(health.data?.overall ?? "warning")}`}
          />
          Automation Health:{" "}
          <span className={tone(health.data?.overall ?? "warning")}>
            {(health.data?.overall ?? "checking…").toUpperCase()}
          </span>
          <span className="text-slate-600">{expanded ? "▾ hide" : "▸ subsystems"}</span>
        </button>
        {expanded && health.data ? (
          <div className="mt-2 grid gap-1.5 md:grid-cols-2">
            {health.data.checks.map((c) => (
              <div key={c.name} className="flex items-start gap-2 text-xs">
                <span className={`mt-1 inline-block h-2 w-2 shrink-0 rounded-full ${dot(c.status)}`} />
                <span className="text-slate-300">
                  <span className="font-medium text-slate-200">
                    {c.name.replace(/_/g, " ")}
                  </span>{" "}
                  — <span className={tone(c.status)}>{c.status}</span>: {c.detail}
                </span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

import { NavLink } from "react-router-dom";

import { useUpdateStatus } from "../state/updates";

const STAGES: { to: string; n: string; label: string; end?: boolean }[] = [
  { to: "/scan", n: "1", label: "Scan", end: true },
  { to: "/candidates", n: "2", label: "Candidates" },
  { to: "/conviction", n: "3", label: "Conviction" },
  { to: "/analogs", n: "4", label: "Analogs" },
  { to: "/backtest", n: "5", label: "Backtest" },
  { to: "/replay", n: "6", label: "Replay" },
  { to: "/paper", n: "7", label: "Paper" },
  { to: "/live", n: "8", label: "Live 🔒" },
];

const UTILITIES: { to: string; label: string }[] = [
  { to: "/portfolio", label: "Portfolio" },
  { to: "/analytics", label: "Analytics" },
  { to: "/settings", label: "Settings" },
  { to: "/updates", label: "Updates" },
];

function itemClass({ isActive }: { isActive: boolean }): string {
  return `flex items-center gap-2 rounded px-2 py-1.5 text-sm transition-colors ${
    isActive ? "bg-accent/15 text-accent" : "text-slate-300 hover:bg-surface/60"
  }`;
}

export function StageRail() {
  const update = useUpdateStatus();
  return (
    <nav className="flex w-48 shrink-0 flex-col gap-0.5 border-r border-surface-border bg-surface-raised px-2 py-2">
      {STAGES.map((s) => (
        <NavLink key={s.to} to={s.to} end={s.end} className={itemClass}>
          <span className="w-4 text-right text-xs text-slate-500">{s.n}</span>
          {s.label}
        </NavLink>
      ))}
      <div className="my-2 border-t border-surface-border" />
      {UTILITIES.map((u) => (
        <NavLink key={u.to} to={u.to} className={itemClass}>
          <span className="w-4" />
          {u.label}
          {u.to === "/updates" && update.available ? (
            <span
              className="ml-auto h-2 w-2 rounded-full bg-accent"
              title={
                update.downloaded
                  ? "Update downloaded — restart to install"
                  : `Update available${update.version ? ` (v${update.version})` : ""}`
              }
            />
          ) : null}
        </NavLink>
      ))}
    </nav>
  );
}

import { NavLink } from "react-router-dom";

import { useUpdateStatus } from "../state/updates";
import { Icon } from "./icons";

interface Item {
  to: string;
  label: string;
  icon: string;
  end?: boolean;
  key?: string; // keyboard hint shown on the right
}

/**
 * Grouped navigation, organized by what the user is doing — not by internal
 * pipeline stage. "Today" is the daily loop; everything else is depth.
 */
const SECTIONS: { title: string; items: Item[] }[] = [
  {
    title: "Today",
    items: [
      { to: "/", label: "Command Center", icon: "home", end: true },
      { to: "/watchlists", label: "Watchlists", icon: "list" },
      { to: "/trades", label: "My Trades", icon: "heart" },
      { to: "/paper", label: "Paper Account", icon: "briefcase", key: "7" },
    ],
  },
  {
    title: "Research",
    items: [
      { to: "/scan", label: "Scanner", icon: "radar", end: true, key: "1" },
      { to: "/candidates", label: "Candidates", icon: "crosshair", key: "2" },
      { to: "/conviction", label: "Conviction", icon: "gauge", key: "3" },
      { to: "/tradeplan", label: "Trade Plan", icon: "target" },
      { to: "/analogs", label: "Analogs", icon: "layers", key: "4" },
      { to: "/lifecycle", label: "Lifecycle", icon: "pulse" },
      { to: "/timeline", label: "Timeline", icon: "clock" },
    ],
  },
  {
    title: "Performance",
    items: [
      { to: "/portfolio", label: "Portfolio", icon: "chart" },
      { to: "/analytics", label: "Analytics", icon: "scale" },
      { to: "/backtest", label: "Backtesting", icon: "flask", key: "5" },
      { to: "/replay", label: "Replay", icon: "replay", key: "6" },
      { to: "/signal-eval", label: "Signal Eval", icon: "check" },
      { to: "/signal-audit", label: "Signal Audit", icon: "audit" },
      { to: "/watchlist-performance", label: "WL Performance", icon: "list" },
    ],
  },
  {
    title: "System",
    items: [
      { to: "/data-health", label: "Data Health", icon: "pulse" },
      { to: "/settings", label: "Settings", icon: "gear" },
      { to: "/updates", label: "Updates", icon: "download" },
    ],
  },
];

function itemClass({ isActive }: { isActive: boolean }): string {
  return [
    "group relative flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[13px] leading-none",
    "transition-colors",
    isActive
      ? "bg-accent-soft/15 font-medium text-slate-100"
      : "text-slate-400 hover:bg-surface-raised hover:text-slate-200",
  ].join(" ");
}

function ActiveBar({ isActive }: { isActive: boolean }) {
  if (!isActive) return null;
  return (
    <span className="absolute -left-2 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-full bg-accent" />
  );
}

export function StageRail() {
  const update = useUpdateStatus();
  return (
    <nav className="flex w-52 shrink-0 flex-col overflow-y-auto border-r border-surface-border bg-surface-sunken px-3 py-3">
      {SECTIONS.map((section, i) => (
        <div key={section.title} className={i === 0 ? "" : "mt-4"}>
          <div className="overline mb-1.5 px-2.5">{section.title}</div>
          <div className="flex flex-col gap-px">
            {section.items.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end} className={itemClass}>
                {({ isActive }) => (
                  <>
                    <ActiveBar isActive={isActive} />
                    <Icon
                      name={item.icon}
                      className={isActive ? "text-accent" : "text-slate-500 group-hover:text-slate-400"}
                    />
                    <span className="truncate">{item.label}</span>
                    {item.to === "/updates" && update.available ? (
                      <span
                        className="ml-auto h-1.5 w-1.5 rounded-full bg-accent"
                        title={
                          update.downloaded
                            ? "Update downloaded — restart to install"
                            : `Update available${update.version ? ` (v${update.version})` : ""}`
                        }
                      />
                    ) : item.key ? (
                      <kbd className="ml-auto hidden rounded border border-surface-border px-1 text-[9px] text-slate-600 group-hover:inline">
                        {item.key}
                      </kbd>
                    ) : null}
                  </>
                )}
              </NavLink>
            ))}
          </div>
        </div>
      ))}

      {window.mrp?.dev ? (
        <div className="mt-4">
          <div className="overline mb-1.5 px-2.5 text-amber-500/80">Developer</div>
          <div className="flex flex-col gap-px">
            <NavLink to="/developer" className={itemClass}>
              <Icon name="wrench" className="text-amber-500/80" />
              <span className="text-amber-200/90">Dev Panel</span>
            </NavLink>
            <NavLink to="/verification" className={itemClass}>
              <Icon name="check" className="text-amber-500/80" />
              <span className="text-amber-200/90">Verification</span>
            </NavLink>
          </div>
        </div>
      ) : null}

      <div className="mt-auto pt-4">
        <div className="rounded-md border border-surface-border/60 px-2.5 py-2 text-[10px] leading-relaxed text-slate-600">
          Paper trading only.
          <br />
          Live execution stays locked until the research proves out.
        </div>
      </div>
    </nav>
  );
}

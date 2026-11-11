import { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

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
 * Navigation. Four screens cover the whole daily routine; everything else —
 * the research and diagnostic tools — lives under a collapsed "Advanced" group
 * so it is there when wanted and out of the way when not.
 */
const MAIN: Item[] = [
  { to: "/", label: "Today", icon: "home", end: true, key: "1" },
  { to: "/signals", label: "Buy signals", icon: "crosshair", key: "2" },
  { to: "/positions", label: "Positions", icon: "briefcase", key: "3" },
  { to: "/results", label: "Results", icon: "chart", key: "4" },
];

const SYSTEM: Item[] = [
  { to: "/settings", label: "Settings", icon: "gear" },
  { to: "/updates", label: "Updates", icon: "download" },
];

const ADVANCED: { title: string; items: Item[] }[] = [
  {
    title: "Research",
    items: [
      { to: "/command-center", label: "Command Center", icon: "home" },
      { to: "/scan", label: "Scanner", icon: "radar", end: true },
      { to: "/tradeplan", label: "Trade Plan", icon: "target" },
      { to: "/conviction", label: "Conviction", icon: "gauge" },
      { to: "/watchlists", label: "Watchlists", icon: "list" },
      { to: "/analogs", label: "Analogs", icon: "layers" },
      { to: "/lifecycle", label: "Lifecycle", icon: "pulse" },
      { to: "/timeline", label: "Timeline", icon: "clock" },
    ],
  },
  {
    title: "Accounts",
    items: [
      { to: "/trades", label: "Trade Health", icon: "heart" },
      { to: "/paper", label: "Paper Account", icon: "briefcase" },
      { to: "/brokerage", label: "Brokerage", icon: "briefcase" },
      { to: "/portfolio", label: "Portfolio", icon: "chart" },
    ],
  },
  {
    title: "Analysis",
    items: [
      { to: "/backtest", label: "Backtesting", icon: "flask" },
      { to: "/analytics", label: "Analytics", icon: "scale" },
      { to: "/replay", label: "Replay", icon: "replay" },
      { to: "/signal-eval", label: "Signal Eval", icon: "check" },
      { to: "/signal-audit", label: "Signal Audit", icon: "audit" },
      { to: "/watchlist-performance", label: "WL Performance", icon: "list" },
    ],
  },
  {
    title: "Diagnostics",
    items: [
      { to: "/data-health", label: "Data Health", icon: "pulse" },
      { to: "/certification", label: "Certification", icon: "shield" },
      { to: "/shadow", label: "Shadow Mode", icon: "crosshair" },
    ],
  },
];

/** Every route that belongs to the Advanced group (drives auto-expand). */
export const ADVANCED_PATHS: string[] = ADVANCED.flatMap((g) => g.items.map((i) => i.to));

const ADVANCED_KEY = "mrp:nav:advanced";

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

function NavItem({ item, badge }: { item: Item; badge?: React.ReactNode }) {
  return (
    <NavLink to={item.to} end={item.end} className={itemClass}>
      {({ isActive }) => (
        <>
          <ActiveBar isActive={isActive} />
          <Icon
            name={item.icon}
            className={isActive ? "text-accent" : "text-slate-500 group-hover:text-slate-400"}
          />
          <span className="truncate">{item.label}</span>
          {badge ??
            (item.key ? (
              <kbd className="ml-auto hidden rounded border border-surface-border px-1 text-[9px] text-slate-600 group-hover:inline">
                {item.key}
              </kbd>
            ) : null)}
        </>
      )}
    </NavLink>
  );
}

export function StageRail() {
  const update = useUpdateStatus();
  const location = useLocation();
  const onAdvanced = ADVANCED_PATHS.some(
    (p) => location.pathname === p || location.pathname.startsWith(`${p}/`),
  );
  const [open, setOpen] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem(ADVANCED_KEY) === "1";
    } catch {
      return false;
    }
  });
  const expanded = open || onAdvanced;
  const toggle = (): void => {
    const next = !expanded;
    setOpen(next);
    try {
      window.localStorage.setItem(ADVANCED_KEY, next ? "1" : "0");
    } catch {
      /* storage unavailable — the group still toggles for this session */
    }
  };

  return (
    <nav className="flex w-52 shrink-0 flex-col overflow-y-auto border-r border-surface-border bg-surface-sunken px-3 py-3">
      <div className="flex flex-col gap-px">
        {MAIN.map((item) => (
          <NavItem key={item.to} item={item} />
        ))}
      </div>

      <div className="mt-4 flex flex-col gap-px">
        {SYSTEM.map((item) => (
          <NavItem
            key={item.to}
            item={item}
            badge={
              item.to === "/updates" && update.available ? (
                <span
                  className="ml-auto h-1.5 w-1.5 rounded-full bg-accent"
                  title={
                    update.downloaded
                      ? "Update downloaded — restart to install"
                      : `Update available${update.version ? ` (v${update.version})` : ""}`
                  }
                />
              ) : undefined
            }
          />
        ))}
      </div>

      <button
        onClick={toggle}
        aria-expanded={expanded}
        className="mt-4 flex items-center justify-between rounded-md px-2.5 py-1.5 text-left text-[11px] font-medium uppercase tracking-wide text-slate-500 hover:bg-surface-raised hover:text-slate-300"
      >
        Advanced
        <span aria-hidden className="text-slate-600">
          {expanded ? "−" : "+"}
        </span>
      </button>
      {expanded
        ? ADVANCED.map((section) => (
            <div key={section.title} className="mt-2">
              <div className="overline mb-1 px-2.5">{section.title}</div>
              <div className="flex flex-col gap-px">
                {section.items.map((item) => (
                  <NavItem key={item.to} item={item} />
                ))}
              </div>
            </div>
          ))
        : null}

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
          Paper trading only — no real money is ever traded.
        </div>
      </div>
    </nav>
  );
}

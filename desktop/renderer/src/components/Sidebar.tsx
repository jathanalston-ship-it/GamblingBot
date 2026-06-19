import { NavLink } from "react-router-dom";

const NAV: { to: string; label: string; end?: boolean }[] = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/scanner", label: "Scanner" },
  { to: "/journal", label: "Trade Journal" },
  { to: "/regime", label: "Market Regime" },
  { to: "/portfolio", label: "Portfolio" },
  { to: "/backtesting", label: "Backtesting" },
  { to: "/analytics", label: "Analytics" },
  { to: "/settings", label: "Settings" },
];

export function Sidebar() {
  return (
    <nav className="flex w-56 shrink-0 flex-col border-r border-surface-border bg-surface-raised">
      <div className="px-4 py-4">
        <div className="text-sm font-semibold text-slate-100">Momentum RP</div>
        <div className="text-xs text-slate-500">Research Platform</div>
      </div>
      <div className="flex flex-col gap-0.5 px-2">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `rounded px-3 py-2 text-sm transition-colors ${
                isActive ? "bg-accent/15 text-accent" : "text-slate-300 hover:bg-surface/60"
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}

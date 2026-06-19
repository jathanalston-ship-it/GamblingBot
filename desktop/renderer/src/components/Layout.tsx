import { Outlet } from "react-router-dom";

import { apiBaseUrl } from "../api/client";
import { Sidebar } from "./Sidebar";

export function Layout() {
  return (
    <div className="flex h-full">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-surface-border px-6 py-3">
          <div className="text-sm text-slate-400">US Equities · Momentum Breakout</div>
          <div className="text-xs text-slate-500">{apiBaseUrl()}</div>
        </header>
        <main className="min-h-0 flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

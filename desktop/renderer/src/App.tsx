import { useEffect } from "react";
import { Route, Routes, useNavigate } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { BackendGate } from "./components/BackendGate";
import { Placeholder } from "./components/Placeholder";
import Analogs from "./views/Analogs";
import CommandCenter from "./views/CommandCenter";
import Analytics from "./views/Analytics";
import Backtesting from "./views/Backtesting";
import Conviction from "./views/Conviction";
import Lifecycle from "./views/Lifecycle";
import Paper from "./views/Paper";
import Portfolio from "./views/Portfolio";
import Replay from "./views/Replay";
import Scan from "./views/Scan";
import Settings from "./views/Settings";
import SignalAudit from "./views/SignalAudit";
import SignalEvaluation from "./views/SignalEvaluation";
import TradePlan from "./views/TradePlan";
import Updates from "./views/Updates";
import WatchlistPerformance from "./views/WatchlistPerformance";
import Watchlists from "./views/Watchlists";

export default function App() {
  const navigate = useNavigate();

  // The Electron menu ("Check for Updates…") asks the renderer to navigate.
  useEffect(() => {
    const off = window.mrp?.onNavigate?.((path) => navigate(path));
    return () => off?.();
  }, [navigate]);

  return (
    <BackendGate>
      <Routes>
        <Route element={<AppShell />}>
        <Route index element={<CommandCenter />} />
        <Route path="command-center" element={<CommandCenter />} />
        <Route path="scan" element={<Scan />} />
        <Route path="candidates" element={<Scan shortlist />} />
        <Route path="conviction" element={<Conviction />} />
        <Route path="analogs" element={<Analogs />} />
        <Route path="backtest" element={<Backtesting />} />
        <Route path="replay" element={<Replay />} />
        <Route path="paper" element={<Paper />} />
        <Route
          path="live"
          element={
            <Placeholder
              stage="8 · Live Execution"
              note="Gated behind a deliberate enablement (broker connect + typed confirmation + kill-switch). Locked until paper results justify it."
            />
          }
        />
        <Route path="tradeplan" element={<TradePlan />} />
        <Route path="lifecycle" element={<Lifecycle />} />
        <Route path="watchlists" element={<Watchlists />} />
        <Route path="watchlist-performance" element={<WatchlistPerformance />} />
        <Route path="portfolio" element={<Portfolio />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="signal-eval" element={<SignalEvaluation />} />
        <Route path="signal-audit" element={<SignalAudit />} />
        <Route path="settings" element={<Settings />} />
        <Route path="updates" element={<Updates />} />
        </Route>
      </Routes>
    </BackendGate>
  );
}

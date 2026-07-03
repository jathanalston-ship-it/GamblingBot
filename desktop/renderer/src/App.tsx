import { Suspense, lazy, useEffect } from "react";
import { Route, Routes, useNavigate } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { BackendGate } from "./components/BackendGate";
import { Loading } from "./components/Page";
import { Placeholder } from "./components/Placeholder";

// The landing page loads eagerly (first paint); every other view is a lazy
// chunk fetched on first visit — smaller initial parse, faster startup.
import CommandCenter from "./views/CommandCenter";

const Analogs = lazy(() => import("./views/Analogs"));
const Analytics = lazy(() => import("./views/Analytics"));
const Backtesting = lazy(() => import("./views/Backtesting"));
const Brokerage = lazy(() => import("./views/Brokerage"));
const Conviction = lazy(() => import("./views/Conviction"));
const DataHealth = lazy(() => import("./views/DataHealth"));
const Certification = lazy(() => import("./views/Certification"));
const Developer = lazy(() => import("./views/Developer"));
const Lifecycle = lazy(() => import("./views/Lifecycle"));
const Paper = lazy(() => import("./views/Paper"));
const Portfolio = lazy(() => import("./views/Portfolio"));
const Replay = lazy(() => import("./views/Replay"));
const Scan = lazy(() => import("./views/Scan"));
const Settings = lazy(() => import("./views/Settings"));
const SignalAudit = lazy(() => import("./views/SignalAudit"));
const SignalEvaluation = lazy(() => import("./views/SignalEvaluation"));
const TradePlan = lazy(() => import("./views/TradePlan"));
const Timeline = lazy(() => import("./views/Timeline"));
const Trades = lazy(() => import("./views/Trades"));
const Updates = lazy(() => import("./views/Updates"));
const Verification = lazy(() => import("./views/Verification"));
const WatchlistPerformance = lazy(() => import("./views/WatchlistPerformance"));
const Watchlists = lazy(() => import("./views/Watchlists"));

export default function App() {
  const navigate = useNavigate();

  // The Electron menu ("Check for Updates…") asks the renderer to navigate.
  useEffect(() => {
    const off = window.mrp?.onNavigate?.((path) => navigate(path));
    return () => off?.();
  }, [navigate]);

  return (
    <BackendGate>
      <Suspense fallback={<Loading />}>
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
            <Route path="brokerage" element={<Brokerage />} />
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
            <Route path="trades" element={<Trades />} />
            <Route path="timeline" element={<Timeline />} />
            <Route path="lifecycle" element={<Lifecycle />} />
            <Route path="watchlists" element={<Watchlists />} />
            <Route path="watchlist-performance" element={<WatchlistPerformance />} />
            <Route path="portfolio" element={<Portfolio />} />
            <Route path="analytics" element={<Analytics />} />
            <Route path="signal-eval" element={<SignalEvaluation />} />
            <Route path="signal-audit" element={<SignalAudit />} />
            <Route path="data-health" element={<DataHealth />} />
            <Route path="certification" element={<Certification />} />
            <Route path="verification" element={<Verification />} />
            <Route path="settings" element={<Settings />} />
            <Route path="updates" element={<Updates />} />
            <Route path="developer" element={<Developer />} />
          </Route>
        </Routes>
      </Suspense>
    </BackendGate>
  );
}

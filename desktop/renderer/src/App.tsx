import { Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { Placeholder } from "./components/Placeholder";
import Analogs from "./views/Analogs";
import Analytics from "./views/Analytics";
import Backtesting from "./views/Backtesting";
import Conviction from "./views/Conviction";
import Portfolio from "./views/Portfolio";
import Scan from "./views/Scan";
import Settings from "./views/Settings";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Scan />} />
        <Route path="scan" element={<Scan />} />
        <Route path="candidates" element={<Scan />} />
        <Route path="conviction" element={<Conviction />} />
        <Route path="analogs" element={<Analogs />} />
        <Route path="backtest" element={<Backtesting />} />
        <Route path="replay" element={<Placeholder stage="6 · Trade Replay" />} />
        <Route path="paper" element={<Placeholder stage="7 · Paper Trading" />} />
        <Route
          path="live"
          element={
            <Placeholder
              stage="8 · Live Execution"
              note="Gated behind a deliberate enablement (broker connect + typed confirmation + kill-switch). Locked until paper results justify it."
            />
          }
        />
        <Route path="portfolio" element={<Portfolio />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}

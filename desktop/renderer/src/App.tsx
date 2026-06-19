import { Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import Analytics from "./views/Analytics";
import Backtesting from "./views/Backtesting";
import Dashboard from "./views/Dashboard";
import Portfolio from "./views/Portfolio";
import Regime from "./views/Regime";
import Scanner from "./views/Scanner";
import Settings from "./views/Settings";
import TradeJournal from "./views/TradeJournal";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="scanner" element={<Scanner />} />
        <Route path="journal" element={<TradeJournal />} />
        <Route path="regime" element={<Regime />} />
        <Route path="portfolio" element={<Portfolio />} />
        <Route path="backtesting" element={<Backtesting />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}

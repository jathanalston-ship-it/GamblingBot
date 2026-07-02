import { useState } from "react";
import { Outlet } from "react-router-dom";

import { useSystemTimezone } from "../hooks/useSystemTimezone";

import { useAlertNotifications } from "../hooks/useAlertNotifications";
import { useGlobalKeys } from "../hooks/useGlobalKeys";
import { UpdateStatusProvider } from "../state/updates";
import { CommandPalette } from "./CommandPalette";
import { ContextBar } from "./ContextBar";
import { DevBanner } from "./DevBanner";
import { ShortcutsOverlay } from "./ShortcutsOverlay";
import { StageRail } from "./StageRail";
import { StatusBar } from "./StatusBar";

export function AppShell() {
  // OS timezone changes remount the routed view: every timestamp re-renders live.
  const tz = useSystemTimezone();

  // Important alerts (trade managed, stop/target hit, regime change) become
  // OS notifications even while the window is in the background.
  useAlertNotifications();

  const [palette, setPalette] = useState(false);
  const [shortcuts, setShortcuts] = useState(false);

  useGlobalKeys({
    onPalette: () => setPalette(true),
    onShortcuts: () => setShortcuts((s) => !s),
  });

  return (
    <UpdateStatusProvider>
      <div className="flex h-full flex-col">
        <DevBanner />
        <ContextBar onOpenPalette={() => setPalette(true)} />
        <div className="flex min-h-0 flex-1">
          <StageRail />
          <main key={tz} className="min-w-0 flex-1 overflow-auto">
            <Outlet />
          </main>
        </div>
        <StatusBar />
        {palette ? <CommandPalette onClose={() => setPalette(false)} /> : null}
        {shortcuts ? <ShortcutsOverlay onClose={() => setShortcuts(false)} /> : null}
      </div>
    </UpdateStatusProvider>
  );
}

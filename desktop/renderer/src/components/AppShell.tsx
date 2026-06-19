import { useState } from "react";
import { Outlet } from "react-router-dom";

import { useGlobalKeys } from "../hooks/useGlobalKeys";
import { CommandPalette } from "./CommandPalette";
import { ContextBar } from "./ContextBar";
import { ShortcutsOverlay } from "./ShortcutsOverlay";
import { StageRail } from "./StageRail";
import { StatusBar } from "./StatusBar";

export function AppShell() {
  const [palette, setPalette] = useState(false);
  const [shortcuts, setShortcuts] = useState(false);

  useGlobalKeys({
    onPalette: () => setPalette(true),
    onShortcuts: () => setShortcuts((s) => !s),
  });

  return (
    <div className="flex h-full flex-col">
      <ContextBar onOpenPalette={() => setPalette(true)} />
      <div className="flex min-h-0 flex-1">
        <StageRail />
        <main className="min-w-0 flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
      <StatusBar />
      {palette ? <CommandPalette onClose={() => setPalette(false)} /> : null}
      {shortcuts ? <ShortcutsOverlay onClose={() => setShortcuts(false)} /> : null}
    </div>
  );
}

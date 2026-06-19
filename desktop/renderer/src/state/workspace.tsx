import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

/** The persistent research context: a selected run/workspace and a selected symbol
 *  that flow through every pipeline stage so you never re-navigate. */
interface Workspace {
  runId: string | null;
  symbol: string | null;
  setRunId: (r: string | null) => void;
  setSymbol: (s: string | null) => void;
}

const Ctx = createContext<Workspace | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [runId, setRunId] = useState<string | null>(null);
  const [symbol, setSymbol] = useState<string | null>(null);
  const value = useMemo<Workspace>(() => ({ runId, symbol, setRunId, setSymbol }), [runId, symbol]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useWorkspace(): Workspace {
  const v = useContext(Ctx);
  if (!v) throw new Error("useWorkspace must be used within <WorkspaceProvider>");
  return v;
}

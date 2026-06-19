import { apiBaseUrl } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useWorkspace } from "../state/workspace";

interface Health {
  status: string;
}

export function StatusBar() {
  const { runId, symbol } = useWorkspace();
  const health = useApi<Health>("/health");
  const ok = health.data?.status === "ok";

  return (
    <footer className="flex items-center gap-4 border-t border-surface-border bg-surface-raised px-4 py-1 text-xs text-slate-500">
      <span className="flex items-center gap-1.5">
        <span className={ok ? "text-bull" : "text-bear"}>●</span>
        backend {ok ? "ok" : "down"}
      </span>
      <span>{apiBaseUrl()}</span>
      <span>run {runId ?? "—"}</span>
      <span>symbol {symbol ?? "—"}</span>
      <span className="ml-auto">⌘K palette · ? shortcuts · 1–8 stages</span>
    </footer>
  );
}

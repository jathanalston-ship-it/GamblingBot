import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import type { ScanResult } from "../api/types";
import { Badge } from "../components/Badge";
import { Inspector } from "../components/Inspector";
import { useApi } from "../hooks/useApi";
import { num, pct } from "../lib/format";
import { useWorkspace } from "../state/workspace";

export default function Scan() {
  const { runId, symbol, setSymbol } = useWorkspace();
  const [passedOnly, setPassedOnly] = useState(false);
  const navigate = useNavigate();

  const path = `/universe/scans?limit=300${passedOnly ? "&passed_only=true" : ""}${
    runId ? `&run_id=${runId}` : ""
  }`;
  const { data, error, loading } = useApi<ScanResult[]>(path);
  const rows = data ?? [];
  const idx = Math.max(0, rows.findIndex((r) => r.symbol === symbol));

  useEffect(() => {
    if (!symbol && rows.length > 0) setSymbol(rows[0].symbol);
  }, [symbol, rows, setSymbol]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
      if (rows.length === 0) return;
      if (e.key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        setSymbol(rows[Math.min(idx + 1, rows.length - 1)].symbol);
      } else if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        setSymbol(rows[Math.max(idx - 1, 0)].symbol);
      } else if (e.key === "Enter") {
        navigate("/conviction");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, idx, setSymbol, navigate]);

  return (
    <div className="grid h-full grid-cols-[1fr_22rem]">
      <div className="flex min-w-0 flex-col border-r border-surface-border">
        <div className="flex items-center gap-3 border-b border-surface-border px-3 py-2 text-sm">
          <button
            disabled
            title="Planned: POST /scans/run (Phase 3 command endpoint)"
            className="cursor-not-allowed rounded bg-accent/30 px-2 py-1 text-xs text-slate-300"
          >
            Run scan ⏎
          </button>
          <span className="text-slate-500">
            {rows.length} candidates{passedOnly ? " · passed" : ""}
          </span>
          <label className="ml-auto flex items-center gap-1.5 text-slate-400">
            <input
              type="checkbox"
              checked={passedOnly}
              onChange={(e) => setPassedOnly(e.target.checked)}
            />
            passed only
          </label>
        </div>

        <div className="min-h-0 flex-1 overflow-auto">
          {loading ? (
            <div className="p-6 text-sm text-slate-500">Loading…</div>
          ) : error ? (
            <div className="p-6 text-sm text-bear">Failed: {error}</div>
          ) : rows.length === 0 ? (
            <div className="p-6 text-sm text-slate-500">No scan results — run `mrp scan`.</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface-raised text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  <th className="px-3 py-2 text-right font-medium">#</th>
                  <th className="px-3 py-2 text-left font-medium">Sym</th>
                  <th className="px-3 py-2 text-right font-medium">Score</th>
                  <th className="px-3 py-2 text-right font-medium">RVol</th>
                  <th className="px-3 py-2 text-right font-medium">ΔATH</th>
                  <th className="px-3 py-2 text-left font-medium">Sector</th>
                  <th className="px-3 py-2 text-left font-medium">Gate</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.symbol}
                    onClick={() => setSymbol(r.symbol)}
                    className={`cursor-pointer border-b border-surface-border/40 ${
                      r.symbol === symbol ? "bg-accent/15" : "hover:bg-surface/40"
                    }`}
                  >
                    <td className="px-3 py-1.5 text-right tabular-nums text-slate-400">
                      {num(r.rank, 0)}
                    </td>
                    <td className="px-3 py-1.5 font-medium text-slate-100">{r.symbol}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{num(r.momentum_score, 3)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {num(r.relative_volume, 2)}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {pct(r.distance_from_ath)}
                    </td>
                    <td className="px-3 py-1.5 text-slate-400">{r.sector ?? "—"}</td>
                    <td className="px-3 py-1.5">
                      {r.passed ? <Badge tone="bull">pass</Badge> : <Badge tone="bear">fail</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <Inspector symbol={symbol} />
    </div>
  );
}

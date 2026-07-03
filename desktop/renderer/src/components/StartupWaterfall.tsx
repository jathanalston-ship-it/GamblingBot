import { useEffect, useState } from "react";

import { Card } from "./Card";

/**
 * Settings → Diagnostics: the measured startup waterfall. Every stage of the
 * latest launch (Electron trace + backend boot timings + renderer marks) as a
 * bar chart with the responsiveness tiers highlighted, plus per-stage
 * avg / median / p95 / worst across the rolling launch history. Measured
 * timings only — the panel says so when there is nothing measured yet.
 */

const TIER_COLOR: Record<string, string> = {
  ok: "bg-emerald-500/70",
  over100: "bg-sky-500/80",
  over250: "bg-amber-400/80",
  over500: "bg-orange-500/80",
  over1000: "bg-rose-500/80",
};

const TIER_TEXT: Record<string, string> = {
  ok: "text-slate-400",
  over100: "text-sky-300",
  over250: "text-amber-300",
  over500: "text-orange-300",
  over1000: "text-rose-300",
};

const TIER_LABEL: Record<string, string> = {
  over100: "> 100ms",
  over250: "> 250ms",
  over500: "> 500ms",
  over1000: "> 1s",
};

export function StartupWaterfall() {
  const [perf, setPerf] = useState<StartupPerf | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    const bridge = window.mrp?.perf?.startup;
    if (!bridge) {
      setUnavailable(true);
      return;
    }
    bridge()
      .then(setPerf)
      .catch(() => setUnavailable(true));
  }, []);

  if (unavailable) {
    return (
      <Card title="Startup Performance">
        <p className="text-sm text-slate-500">
          Startup timings are recorded by the desktop shell — open this panel in the
          desktop app to see the measured waterfall.
        </p>
      </Card>
    );
  }
  if (!perf) return null;

  const total = perf.waterfall.reduce((sum, row) => sum + row.durationMs, 0);
  const scale = Math.max(total, 1);

  return (
    <Card title={`Startup Performance — measured over ${perf.launches} launch${perf.launches === 1 ? "" : "es"}`}>
      {perf.waterfall.length === 0 ? (
        <p className="text-sm text-slate-500">No launches measured yet.</p>
      ) : (
        <div className="space-y-4">
          <div>
            <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
              <span>Latest launch waterfall ({(total / 1000).toFixed(2)}s to ready)</span>
              <span className="flex gap-3">
                {Object.entries(TIER_LABEL).map(([tier, label]) => (
                  <span key={tier} className="flex items-center gap-1">
                    <span className={`inline-block h-2 w-2 rounded-sm ${TIER_COLOR[tier]}`} />
                    {label}
                  </span>
                ))}
              </span>
            </div>
            <div className="space-y-1">
              {perf.waterfall.map((row, index) => (
                <div key={`${row.stage}-${index}`} className="flex items-center gap-2 text-xs">
                  <span className="w-44 shrink-0 truncate text-slate-400">{row.stage}</span>
                  <div className="relative h-3.5 flex-1 rounded bg-surface/50">
                    <div
                      className={`absolute h-full rounded ${TIER_COLOR[row.tier] ?? TIER_COLOR.ok}`}
                      style={{
                        left: `${(row.startMs / scale) * 100}%`,
                        width: `${Math.max((row.durationMs / scale) * 100, 0.5)}%`,
                      }}
                    />
                  </div>
                  <span className={`w-16 shrink-0 text-right tabular-nums ${TIER_TEXT[row.tier] ?? ""}`}>
                    {row.durationMs}ms
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-surface-border uppercase tracking-wide text-slate-500">
                  <th className="py-1.5 pr-3">Stage</th>
                  <th className="py-1.5 pr-3 text-right">Last</th>
                  <th className="py-1.5 pr-3 text-right">Avg</th>
                  <th className="py-1.5 pr-3 text-right">Median</th>
                  <th className="py-1.5 pr-3 text-right">p95</th>
                  <th className="py-1.5 pr-3 text-right">Worst</th>
                  <th className="py-1.5 text-right">n</th>
                </tr>
              </thead>
              <tbody>
                {perf.stats.map((s) => (
                  <tr key={s.stage} className="border-b border-surface-border/50">
                    <td className={`py-1 pr-3 ${TIER_TEXT[s.tier] ?? "text-slate-300"}`}>
                      {s.stage}
                    </td>
                    <td className="py-1 pr-3 text-right tabular-nums">{s.lastMs}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{s.avgMs}</td>
                    <td className={`py-1 pr-3 text-right tabular-nums ${TIER_TEXT[s.tier] ?? ""}`}>
                      {s.medianMs}
                    </td>
                    <td className="py-1 pr-3 text-right tabular-nums">{s.p95Ms}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{s.worstMs}</td>
                    <td className="py-1 text-right tabular-nums text-slate-500">{s.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}

import { Card } from "./Card";
import { useApi } from "../hooks/useApi";

interface ProviderRequest {
  symbol: string;
  provider: string;
  request_timestamp: string;
  bar_timestamp: string | null;
  bar_count: number;
  request_duration_ms: number | null;
  cache_hit: boolean;
  source: "LIVE" | "CACHE";
  run_id: string | null;
}

function fmt(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

/** The last N provider requests — every fetch is shown LIVE or CACHE, no hidden cache. */
export function ProviderRequestsPanel({ limit = 20 }: { limit?: number }) {
  const { data, error, loading } = useApi<ProviderRequest[]>(
    `/market-data/provenance?limit=${limit}`,
    { refreshMs: 30_000 },
  );

  return (
    <Card title={`Last ${limit} Provider Requests`}>
      {loading && !data ? (
        <p className="text-xs text-slate-500">Loading…</p>
      ) : error ? (
        <p className="text-xs text-rose-400">{error}</p>
      ) : !data || data.length === 0 ? (
        <p className="text-xs text-slate-500">No provider requests recorded yet — run a scan.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wide text-slate-500">
              <tr className="border-b border-surface-border text-left">
                <th className="px-2 py-1 font-medium">Symbol</th>
                <th className="px-2 py-1 font-medium">Provider</th>
                <th className="px-2 py-1 font-medium">Requested</th>
                <th className="px-2 py-1 text-right font-medium">Bars</th>
                <th className="px-2 py-1 font-medium">Newest bar</th>
                <th className="px-2 py-1 text-right font-medium">ms</th>
                <th className="px-2 py-1 font-medium">Source</th>
              </tr>
            </thead>
            <tbody className="tabular-nums text-slate-300">
              {data.map((r, i) => (
                <tr key={i} className="border-b border-surface-border/40">
                  <td className="px-2 py-1 font-medium text-slate-100">{r.symbol}</td>
                  <td className="px-2 py-1 text-slate-400">{r.provider}</td>
                  <td className="px-2 py-1 text-slate-400">{fmt(r.request_timestamp)}</td>
                  <td className="px-2 py-1 text-right">{r.bar_count}</td>
                  <td className="px-2 py-1 text-slate-400">{fmt(r.bar_timestamp)}</td>
                  <td className="px-2 py-1 text-right text-slate-400">
                    {r.request_duration_ms == null ? "—" : r.request_duration_ms.toFixed(0)}
                  </td>
                  <td className="px-2 py-1">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                        r.source === "LIVE"
                          ? "bg-emerald-500/20 text-emerald-300"
                          : "bg-amber-500/20 text-amber-300"
                      }`}
                    >
                      {r.source}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

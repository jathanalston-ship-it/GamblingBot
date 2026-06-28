import type { ScanMetadata } from "../api/types";
import { useApi } from "../hooks/useApi";
import { fmtAge, fmtTime } from "../lib/format";

/**
 * Prominent warning shown when the latest scan's market data is stale. When the
 * data is too old the backend withholds conviction & watchlist data, so screens
 * relying on it would otherwise look mysteriously empty — this explains why.
 *
 * Renders nothing when there is no scan metadata or the data is fresh.
 */
export function StaleBanner() {
  const { data: meta } = useApi<ScanMetadata | null>("/universe/scan-metadata");

  if (!meta || !meta.stale) return null;

  return (
    <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-bear/40 bg-bear/10 px-3 py-2 text-xs text-bear">
      <span className="rounded bg-bear px-1.5 py-0.5 text-[10px] font-bold uppercase text-white">
        Stale Data
      </span>
      <span>
        Market data is {fmtAge(meta.data_age_minutes)} old (newest bar{" "}
        {fmtTime(meta.bar_timestamp)}). Conviction &amp; watchlists are withheld until a fresher
        scan.
      </span>
      <span className="ml-auto flex items-center gap-3 text-bear/80">
        <Stat label="provider" value={meta.provider} />
        <Stat label="data age" value={fmtAge(meta.data_age_minutes)} />
        <Stat label="last pull" value={fmtTime(meta.pull_timestamp)} />
      </span>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex items-baseline gap-1">
      <span className="uppercase tracking-wide opacity-70">{label}</span>
      <span className="tabular-nums">{value}</span>
    </span>
  );
}

import { useApi } from "../hooks/useApi";
import { dateTime } from "../lib/format";

interface ScreenProvenance {
  rows: number | null;
  generation_timestamp: string | null;
}

interface Provenance {
  run_id: string | null;
  mode: "live" | "demo" | "none";
  source_provider: string | null;
  fetch_timestamp: string | null;
  bar_timestamp: string | null;
  data_age_minutes: number | null;
  stale: boolean | null;
  screens: Record<string, ScreenProvenance>;
}

function fmtTime(iso: string | null): string {
  return dateTime(iso); // UTC → local timezone, OS locale (see lib/format)
}

function fmtAge(mins: number | null): string {
  if (mins == null) return "unknown";
  if (mins < 60) return `${mins.toFixed(0)} min`;
  if (mins < 24 * 60) return `${(mins / 60).toFixed(1)} h`;
  return `${(mins / (24 * 60)).toFixed(1)} d`;
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <span className="whitespace-nowrap">
      <span className="text-slate-500">{label}:</span> <span className="text-slate-300">{value}</span>
    </span>
  );
}

/**
 * Data-provenance strip — shows, for the data on this screen, where it came from,
 * when it was fetched + generated, the run id, its age, and whether it is demo or
 * live. No hidden fallback: the demo/live badge is always explicit.
 */
export function ProvenancePanel({ screen }: { screen: string }) {
  const { data } = useApi<Provenance>("/provenance", { refreshMs: 60_000 });
  if (!data || data.mode === "none") return null;
  const s = data.screens[screen];
  const isDemo = data.mode === "demo";

  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 rounded border border-surface-border bg-surface/40 px-3 py-2 text-xs">
      <span
        className={`rounded px-1.5 py-0.5 font-semibold ${
          isDemo ? "bg-amber-500/20 text-amber-300" : "bg-emerald-500/20 text-emerald-300"
        }`}
        title={isDemo ? "Sample/demo data" : "Live data from the configured provider"}
      >
        {isDemo ? "DEMO DATA" : "LIVE"}
      </span>
      <Field label="Source" value={data.source_provider ?? "—"} />
      <Field label="Run" value={data.run_id ?? "—"} />
      <Field label="Fetched" value={fmtTime(data.fetch_timestamp)} />
      <Field label="Generated" value={fmtTime(s?.generation_timestamp ?? null)} />
      <Field label="Data age" value={fmtAge(data.data_age_minutes)} />
      {s?.rows != null ? <Field label="Rows" value={String(s.rows)} /> : null}
      {data.stale ? (
        <span className="rounded bg-rose-500/20 px-1.5 py-0.5 font-semibold text-rose-300">
          STALE
        </span>
      ) : null}
    </div>
  );
}

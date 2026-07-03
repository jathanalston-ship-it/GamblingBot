import { Card } from "../components/Card";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { Stat } from "../components/Stat";
import { useApi } from "../hooks/useApi";
import { dateTime } from "../lib/format";

interface Requirement {
  key: string;
  label: string;
  passed: boolean;
  measured: string;
  threshold: string;
  detail: string;
}

interface CertificationOut {
  status: "certified" | "in_progress" | "failing";
  certified: boolean;
  window_start: string;
  window_end: string;
  streak_days: number;
  required_days: number;
  uptime_pct: number;
  scans_completed: number;
  trades_opened: number;
  trades_closed: number;
  alerts_generated: number;
  errors: number;
  warnings: number;
  api_failures: number;
  provider_failures: number;
  missed_scan_minutes: number;
  max_session_gap_seconds: number;
  memory_growth_mb: number | null;
  p95_scan_duration_ms: number | null;
  requirements: Requirement[];
  generated_at: string | null;
}

const STATUS_BADGE: Record<string, string> = {
  certified: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  in_progress: "bg-amber-400/15 text-amber-200 border-amber-400/40",
  failing: "bg-rose-500/15 text-rose-300 border-rose-500/40",
};

const STATUS_LABEL: Record<string, string> = {
  certified: "CERTIFIED",
  in_progress: "IN PROGRESS",
  failing: "FAILING",
};

function RequirementRow({ r }: { r: Requirement }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-surface-border py-2 last:border-0">
      <div className="flex items-start gap-3">
        <span
          className={`mt-1 inline-block h-2.5 w-2.5 shrink-0 rounded-full ${
            r.passed ? "bg-emerald-500" : "bg-rose-500"
          }`}
        />
        <div>
          <div className="text-sm text-slate-200">{r.label}</div>
          <div className="text-xs text-slate-500">{r.detail}</div>
        </div>
      </div>
      <div className="text-right">
        <div className={`text-sm ${r.passed ? "text-emerald-400" : "text-rose-400"}`}>
          {r.measured}
        </div>
        <div className="text-xs text-slate-500">requires {r.threshold}</div>
      </div>
    </div>
  );
}

export default function Certification() {
  const { data, error, loading, reload } = useApi<CertificationOut>("/certification", {
    refreshMs: 60_000,
  });

  return (
    <div className="p-5">
      <PageTitle
        title="Paper Certification"
        subtitle="30 consecutive clean days before live trading is even a conversation"
      >
        <button
          onClick={reload}
          className="rounded border border-surface-border px-3 py-1.5 text-sm text-slate-300 hover:bg-surface/60"
        >
          Refresh
        </button>
      </PageTitle>

      {loading && !data ? <Loading /> : null}
      {error ? <ErrorBox message={error} /> : null}

      {data ? (
        <div className="grid gap-4">
          <Card title="Certification Status">
            <div className="flex flex-wrap items-center gap-4">
              <span
                className={`rounded border px-3 py-1 text-sm font-semibold tracking-wide ${
                  STATUS_BADGE[data.status] ?? ""
                }`}
              >
                {STATUS_LABEL[data.status] ?? data.status}
              </span>
              <span className="text-sm text-slate-300">
                Day {Math.min(data.streak_days, data.required_days)} of {data.required_days}
              </span>
              <span className="text-xs text-slate-500">
                {data.generated_at ? `evaluated ${dateTime(data.generated_at)}` : null}
              </span>
            </div>
            <div className="mt-3 h-2 w-full overflow-hidden rounded bg-surface/70">
              <div
                className={`h-full ${data.status === "failing" ? "bg-rose-500" : "bg-emerald-500"}`}
                style={{
                  width: `${Math.min((data.streak_days / data.required_days) * 100, 100)}%`,
                }}
              />
            </div>
          </Card>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Uptime (scan coverage)" value={`${(data.uptime_pct * 100).toFixed(2)}%`} />
            <Stat label="Scans completed" value={String(data.scans_completed)} />
            <Stat label="Trades opened" value={String(data.trades_opened)} />
            <Stat label="Trades closed" value={String(data.trades_closed)} />
            <Stat label="Alerts generated" value={String(data.alerts_generated)} />
            <Stat label="Errors" value={String(data.errors)} />
            <Stat label="Warnings" value={String(data.warnings)} />
            <Stat label="Provider failures" value={String(data.provider_failures)} />
          </div>

          <Card title="Requirements (every one must pass)">
            {data.requirements.map((r) => (
              <RequirementRow key={r.key} r={r} />
            ))}
          </Card>
        </div>
      ) : null}
    </div>
  );
}

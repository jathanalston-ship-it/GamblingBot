import { useState } from "react";

import { apiGet } from "../api/client";
import { Card } from "../components/Card";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { useApi } from "../hooks/useApi";

interface HealthMetric {
  key: string;
  label: string;
  value: string | null;
  status: "green" | "yellow" | "red";
  detail: string | null;
}

interface DataHealthOut {
  status: "green" | "yellow" | "red";
  data_mode: string;
  provider: string;
  generated_at: string;
  metrics: HealthMetric[];
}

const DOT: Record<string, string> = {
  green: "bg-emerald-500",
  yellow: "bg-amber-400",
  red: "bg-rose-500",
};

const TEXT: Record<string, string> = {
  green: "text-emerald-400",
  yellow: "text-amber-300",
  red: "text-rose-400",
};

function StatusDot({ status }: { status: string }) {
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${DOT[status] ?? "bg-slate-500"}`} />;
}

function MetricRow({ m }: { m: HealthMetric }) {
  return (
    <div className="flex items-center justify-between border-b border-surface-border py-2 last:border-0">
      <div className="flex items-center gap-3">
        <StatusDot status={m.status} />
        <div>
          <div className="text-sm text-slate-200">{m.label}</div>
          {m.detail ? <div className="text-xs text-slate-500">{m.detail}</div> : null}
        </div>
      </div>
      <div className={`text-right text-sm ${TEXT[m.status] ?? "text-slate-300"}`}>
        {m.value ?? "—"}
      </div>
    </div>
  );
}

function RawDiagnostics() {
  const [open, setOpen] = useState(false);
  const [raw, setRaw] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && raw === null) {
      apiGet<Record<string, unknown>>("/data-health/diagnostics")
        .then(setRaw)
        .catch((e) => setErr(String(e)));
    }
  };

  return (
    <Card title="Raw Diagnostics">
      <button
        onClick={toggle}
        className="rounded border border-surface-border px-3 py-1.5 text-xs text-slate-300 hover:bg-surface/60"
      >
        {open ? "Hide Raw Diagnostics" : "View Raw Diagnostics"}
      </button>
      {open ? (
        err ? (
          <p className="mt-3 text-xs text-rose-400">{err}</p>
        ) : raw === null ? (
          <p className="mt-3 text-xs text-slate-500">Loading…</p>
        ) : (
          <pre className="mt-3 overflow-x-auto rounded bg-surface/60 p-3 text-xs text-slate-300">
            {JSON.stringify(raw, null, 2)}
          </pre>
        )
      ) : null}
    </Card>
  );
}

export default function DataHealth() {
  const { data, error, loading, reload } = useApi<DataHealthOut>("/data-health", {
    refreshMs: 30_000,
  });

  return (
    <div>
      <PageTitle title="Data Health" subtitle="Is the data pipeline flowing?">
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
          <Card
            title="Overall Status"
            action={
              <span className={`flex items-center gap-2 text-sm ${TEXT[data.status]}`}>
                <StatusDot status={data.status} />
                {data.status.toUpperCase()}
              </span>
            }
          >
            <div className="flex flex-wrap gap-x-8 gap-y-1 text-sm text-slate-400">
              <span>
                Provider: <span className="text-slate-200">{data.provider}</span>
              </span>
              <span>
                Data mode: <span className="text-slate-200">{data.data_mode}</span>
              </span>
              <span className="text-xs text-slate-500">
                as of {new Date(data.generated_at).toLocaleString()}
              </span>
            </div>
          </Card>

          <Card title="Pipeline Metrics">
            <div className="flex flex-col">
              {data.metrics.map((m) => (
                <MetricRow key={m.key} m={m} />
              ))}
            </div>
          </Card>

          <RawDiagnostics />
        </div>
      ) : null}
    </div>
  );
}

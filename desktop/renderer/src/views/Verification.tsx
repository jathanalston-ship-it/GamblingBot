import { useState } from "react";
import { dateTime } from "../lib/format";

import { apiPost } from "../api/client";
import { Card } from "../components/Card";
import { PageTitle } from "../components/Page";
import { ProviderRequestsPanel } from "../components/ProviderRequestsPanel";
import { useApi } from "../hooks/useApi";

interface Status {
  backend: string;
  provider_status: string;
  current_provider: string | null;
  last_yahoo_request: string | null;
  last_successful_scan: string | null;
  current_run_id: string | null;
  latest_conviction_count: number;
  latest_analog_count: number;
  latest_watchlist_count: number;
  latest_trade_plan_count: number;
}

interface Stage {
  name: string;
  status: "PASS" | "FAIL";
  detail: string;
  duration_ms: number;
}

interface VerifyResult {
  symbol: string;
  provider: string;
  overall: "PASS" | "FAIL";
  stages: Stage[];
}

function fmt(iso: string | null): string {
  return dateTime(iso); // UTC → local timezone, OS locale (see lib/format)
}

function Row({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between border-b border-surface-border py-1.5 text-sm last:border-0">
      <span className="text-slate-400">{label}</span>
      <span className="text-slate-200">{value}</span>
    </div>
  );
}

export default function Verification() {
  const { data: status, reload } = useApi<Status>("/verification/status", { refreshMs: 15_000 });
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<VerifyResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const verify = async () => {
    setRunning(true);
    setError(null);
    try {
      setResult(await apiPost<VerifyResult>("/verification/verify-pipeline"));
      reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="p-5">
      <PageTitle title="Runtime Verification" subtitle="Diagnostics — live pipeline, no mocks or demo data">
        <button
          onClick={verify}
          disabled={running}
          className="rounded bg-accent/15 px-3 py-1.5 text-sm font-medium text-accent hover:bg-accent/25 disabled:opacity-50"
        >
          {running ? "Verifying…" : "Verify Pipeline"}
        </button>
      </PageTitle>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Runtime Status">
          {status ? (
            <div className="flex flex-col">
              <Row label="Backend status" value={status.backend} />
              <Row label="Provider status" value={status.provider_status} />
              <Row label="Current provider" value={status.current_provider ?? "—"} />
              <Row label="Last Yahoo request" value={fmt(status.last_yahoo_request)} />
              <Row label="Last successful scan" value={fmt(status.last_successful_scan)} />
              <Row label="Current run_id" value={status.current_run_id ?? "—"} />
              <Row label="Latest conviction count" value={status.latest_conviction_count} />
              <Row label="Latest analog count" value={status.latest_analog_count} />
              <Row label="Latest watchlist count" value={status.latest_watchlist_count} />
              <Row label="Latest trade plan count" value={status.latest_trade_plan_count} />
            </div>
          ) : (
            <p className="text-xs text-slate-500">Loading…</p>
          )}
        </Card>

        <Card
          title="Verify Pipeline"
          action={
            result ? (
              <span
                className={`rounded px-2 py-0.5 text-xs font-semibold ${
                  result.overall === "PASS"
                    ? "bg-emerald-500/20 text-emerald-300"
                    : "bg-rose-500/20 text-rose-300"
                }`}
              >
                {result.overall}
              </span>
            ) : null
          }
        >
          {error ? <p className="mb-2 text-xs text-rose-400">{error}</p> : null}
          {!result ? (
            <p className="text-sm text-slate-500">
              Click <b className="text-slate-300">Verify Pipeline</b> to pull one live symbol and
              run it through the real engines.
            </p>
          ) : (
            <div className="flex flex-col">
              <p className="mb-2 text-xs text-slate-500">
                {result.symbol} · {result.provider}
              </p>
              {result.stages.map((s) => (
                <div
                  key={s.name}
                  className="flex items-center gap-3 border-b border-surface-border py-1.5 text-sm last:border-0"
                >
                  <span
                    className={`w-12 rounded px-1.5 py-0.5 text-center text-[10px] font-semibold ${
                      s.status === "PASS"
                        ? "bg-emerald-500/20 text-emerald-300"
                        : "bg-rose-500/20 text-rose-300"
                    }`}
                  >
                    {s.status}
                  </span>
                  <span className="font-medium text-slate-200">{s.name}</span>
                  <span className="flex-1 truncate text-xs text-slate-500">{s.detail}</span>
                  <span className="text-xs text-slate-600">{s.duration_ms.toFixed(0)}ms</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <div className="mt-4">
        <ProviderRequestsPanel limit={20} />
      </div>
    </div>
  );
}

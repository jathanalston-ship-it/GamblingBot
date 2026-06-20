import { useState } from "react";

import { apiPost } from "../api/client";
import type { ReplayResult } from "../api/types";
import { Card } from "../components/Card";
import { ErrorBox, PageTitle } from "../components/Page";

export default function Replay() {
  const [runId, setRunId] = useState("");
  const [data, setData] = useState<ReplayResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function run() {
    setLoading(true);
    setError(null);
    try {
      const body = runId.trim() ? { run_id: runId.trim() } : {};
      setData(await apiPost<ReplayResult>("/actions/replay", body));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  const trades = data ? [...data.open_trades, ...data.closed_trades] : [];

  return (
    <div className="p-5">
      <PageTitle title="Replay" subtitle="Reconstruct a stored session — run, trades and audit trail">
        <div className="flex items-center gap-2">
          <input
            value={runId}
            onChange={(e) => setRunId(e.target.value)}
            placeholder="run id (blank = latest)"
            className="w-56 rounded border border-surface-border bg-surface px-2 py-1 text-sm text-slate-200"
          />
          <button
            onClick={() => void run()}
            disabled={loading}
            className="rounded bg-accent px-3 py-1.5 text-sm text-white hover:bg-accent/90 disabled:opacity-50"
          >
            {loading ? "Replaying…" : "Replay"}
          </button>
        </div>
      </PageTitle>

      {error ? <ErrorBox message={error} /> : null}

      {data ? (
        <div className="grid max-w-3xl gap-5">
          <Card title={`Run · ${String(data.run.run_id ?? "")}`}>
            <pre className="overflow-auto rounded bg-surface p-3 text-xs text-slate-300">
              {JSON.stringify(data.run, null, 2)}
            </pre>
          </Card>
          <Card
            title={`Trades · ${data.open_trades.length} open / ${data.closed_trades.length} closed`}
          >
            {trades.length === 0 ? (
              <div className="text-sm text-slate-500">No trades for this run.</div>
            ) : (
              <ul className="flex flex-col gap-1 text-sm text-slate-300">
                {trades.map((t, i) => (
                  <li key={i}>
                    {String(t.symbol)} · {String(t.status)} · qty {String(t.quantity)} · net{" "}
                    {String(t.net_pnl ?? "—")}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title={`Audit trail · ${data.events.length} events`}>
            <ul className="flex flex-col gap-0.5 text-xs text-slate-400">
              {data.events.map((e, i) => (
                <li key={i}>
                  {String(e.ts)} · {String(e.event_type)} · {String(e.summary)}
                </li>
              ))}
            </ul>
          </Card>
        </div>
      ) : !error && !loading ? (
        <div className="text-sm text-slate-500">
          Enter a run id (or leave it blank for the latest) and click Replay.
        </div>
      ) : null}
    </div>
  );
}

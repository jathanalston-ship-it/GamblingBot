import { Fragment, useState } from "react";

import type { Lifecycle as Row, LifecycleSummary } from "../api/types";
import { ActionButton } from "../components/ActionButton";
import { Card } from "../components/Card";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { useApi } from "../hooks/useApi";
import { date, num } from "../lib/format";
import { useWorkspace } from "../state/workspace";

const STATE_CLASS: Record<string, string> = {
  Building: "bg-slate-600/30 text-slate-300",
  Ready: "bg-accent/20 text-accent",
  Triggered: "bg-indigo-500/20 text-indigo-300",
  Active: "bg-bull/20 text-bull",
  Extended: "bg-amber-500/20 text-amber-300",
  Completed: "bg-emerald-500/20 text-emerald-300",
  Failed: "bg-bear/20 text-bear",
};
const FLOW = ["Building", "Ready", "Triggered", "Active", "Extended"];
const TERMINAL = ["Completed", "Failed"];

function StateBadge({ state }: { state: string }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${STATE_CLASS[state] ?? "bg-surface-border text-slate-300"}`}>
      {state}
    </span>
  );
}

export default function Lifecycle() {
  const { runId } = useWorkspace();
  const runQ = runId ? `&run_id=${runId}` : "";
  const runQ1 = runId ? `?run_id=${runId}` : "";
  const [filter, setFilter] = useState<string | null>(null);

  const summary = useApi<LifecycleSummary>(`/lifecycles/summary${runQ1}`);
  const rows = useApi<Row[]>(`/lifecycles?1=1${runQ}${filter ? `&state=${filter}` : ""}`);

  const countFor = (state: string): number =>
    summary.data?.states.find((s) => s.state === state)?.count ?? 0;

  const chip = (state: string) => {
    const active = filter === state;
    return (
      <button
        key={state}
        onClick={() => setFilter(active ? null : state)}
        className={`flex min-w-[5.5rem] flex-col items-center gap-1 rounded-lg border px-3 py-2 ${
          active ? "border-accent ring-1 ring-accent/40" : "border-surface-border hover:bg-surface/50"
        }`}
      >
        <StateBadge state={state} />
        <span className="text-lg font-semibold tabular-nums text-slate-100">{countFor(state)}</span>
      </button>
    );
  };

  return (
    <div className="space-y-5 p-5">
      <PageTitle title="Setup Lifecycle" subtitle="Every candidate in one state — auto-derived & tracked">
        <div className="flex items-center gap-2">
          {filter ? (
            <button
              onClick={() => setFilter(null)}
              className="rounded border border-surface-border px-2.5 py-1 text-xs text-slate-400 hover:text-slate-200"
            >
              Clear filter
            </button>
          ) : null}
          <ActionButton
            label="Refresh"
            path="/actions/refresh-lifecycles"
            body={runId ? { run_id: runId } : undefined}
            onDone={() => {
              summary.reload();
              rows.reload();
            }}
          />
        </div>
      </PageTitle>

      {/* pipeline */}
      {summary.loading ? (
        <Loading />
      ) : summary.error ? (
        <ErrorBox message={summary.error} />
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {FLOW.map((s, i) => (
            <Fragment key={s}>
              {chip(s)}
              {i < FLOW.length - 1 ? <span className="text-slate-600">→</span> : null}
            </Fragment>
          ))}
          <span className="mx-2 h-8 w-px bg-surface-border" />
          {TERMINAL.map(chip)}
        </div>
      )}

      {/* table */}
      <Card title={filter ? `${filter} · ${rows.data?.length ?? 0}` : `All candidates · ${rows.data?.length ?? 0}`}>
        {rows.loading ? (
          <Loading />
        ) : rows.error ? (
          <ErrorBox message={rows.error} />
        ) : (rows.data ?? []).length === 0 ? (
          <div className="py-8 text-center text-sm text-slate-500">
            No setups{filter ? ` in ${filter}` : ""} yet — run a scan / paper session, or load sample
            data, then Refresh.
          </div>
        ) : (
          <LifecycleTable rows={rows.data ?? []} />
        )}
      </Card>
    </div>
  );
}

function LifecycleTable({ rows }: { rows: Row[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <table className="w-full text-sm">
      <thead className="text-xs uppercase tracking-wide text-slate-400">
        <tr className="border-b border-surface-border text-left">
          <th className="px-2 py-1.5 font-medium">Ticker</th>
          <th className="px-2 py-1.5 font-medium">State</th>
          <th className="px-2 py-1.5 font-medium">Since</th>
          <th className="px-2 py-1.5 font-medium">Sector</th>
          <th className="px-2 py-1.5 text-right font-medium">Conviction</th>
          <th className="px-2 py-1.5 font-medium">Reason</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <Fragment key={r.id}>
            <tr
              onClick={() => setOpen(open === r.id ? null : r.id)}
              className="cursor-pointer border-b border-surface-border/40 hover:bg-surface/40"
              title="Show transition history"
            >
              <td className="px-2 py-1.5 font-medium text-slate-100">{r.symbol}</td>
              <td className="px-2 py-1.5">
                <StateBadge state={r.state} />
                {r.previous_state ? (
                  <span className="ml-1 text-[10px] text-slate-500">← {r.previous_state}</span>
                ) : null}
              </td>
              <td className="px-2 py-1.5 text-slate-400">{date(r.state_since)}</td>
              <td className="px-2 py-1.5 text-slate-400">{r.sector ?? "—"}</td>
              <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                {r.conviction != null ? num(r.conviction, 0) : "—"}
              </td>
              <td className="px-2 py-1.5 text-slate-400">{r.reason ?? "—"}</td>
            </tr>
            {open === r.id && r.history && r.history.length > 0 ? (
              <tr className="bg-surface/30">
                <td colSpan={6} className="px-4 py-2">
                  <ol className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                    {r.history.map((h, i) => (
                      <Fragment key={i}>
                        {i > 0 ? <span className="text-slate-600">→</span> : null}
                        <span className="flex items-center gap-1.5">
                          <StateBadge state={h.state} />
                          <span className="text-slate-500">{date(h.at)}</span>
                        </span>
                      </Fragment>
                    ))}
                  </ol>
                </td>
              </tr>
            ) : null}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

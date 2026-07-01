import { useState } from "react";

import type { ScanDelta, ScanSnapshotDetail, ScanSnapshotHeader } from "../api/types";
import { Card } from "../components/Card";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { useApi } from "../hooks/useApi";
import { fmtTime, num, signed } from "../lib/format";

/** Scan timeline: immutable snapshots — replay any one, diff any two. */
export default function Timeline() {
  const snapshots = useApi<ScanSnapshotHeader[]>("/timeline?limit=200", { refreshMs: 15_000 });
  const [selected, setSelected] = useState<number[]>([]);

  const toggle = (id: number): void =>
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev.slice(-1), id],
    );

  const [a, b] = [...selected].sort((x, y) => x - y);

  return (
    <div className="space-y-5 p-5">
      <PageTitle
        title="Scan Timeline"
        subtitle="Every completed scan is an immutable snapshot — replay one, or select two to diff"
      />

      {snapshots.loading && !snapshots.data ? (
        <Loading />
      ) : snapshots.error && !snapshots.data ? (
        <ErrorBox message={snapshots.error} />
      ) : (snapshots.data ?? []).length === 0 ? (
        <Card title="Snapshots">
          <div className="py-8 text-center text-sm text-slate-500">
            No snapshots yet — every completed scan creates one automatically.
          </div>
        </Card>
      ) : (
        <Card title={`Snapshots · ${snapshots.data?.length ?? 0}`}>
          <div className="flex flex-wrap gap-1.5">
            {(snapshots.data ?? []).map((s) => (
              <button
                key={s.id}
                onClick={() => toggle(s.id)}
                className={`rounded border px-2 py-1 text-xs tabular-nums ${
                  selected.includes(s.id)
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-surface-border text-slate-400 hover:text-slate-200"
                }`}
                title={`${s.candidates} candidates · ${s.market_state ?? "?"}`}
              >
                {fmtTime(s.scan_ts)}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-slate-600">
            Click one snapshot to replay it; click a second to diff the pair.
          </p>
        </Card>
      )}

      {selected.length === 2 && a != null && b != null ? <DiffPanel a={a} b={b} /> : null}
      {selected.length === 1 && selected[0] != null ? <ReplayPanel id={selected[0]} /> : null}
    </div>
  );
}

function DiffPanel({ a, b }: { a: number; b: number }) {
  const diff = useApi<ScanDelta[]>(`/timeline/diff?a=${a}&b=${b}`);
  return (
    <Card title={`Diff · snapshot #${a} → #${b}`}>
      {diff.loading ? (
        <Loading />
      ) : diff.error ? (
        <ErrorBox message={diff.error} />
      ) : (diff.data ?? []).length === 0 ? (
        <div className="py-4 text-center text-sm text-slate-500">
          Identical — nothing changed between these scans.
        </div>
      ) : (
        <DeltaTable rows={diff.data ?? []} />
      )}
    </Card>
  );
}

function DeltaTable({ rows }: { rows: ScanDelta[] }) {
  return (
    <table className="w-full text-xs">
      <thead className="text-[10px] uppercase tracking-wide text-slate-500">
        <tr className="border-b border-surface-border text-left">
          <th className="px-1.5 py-1 font-medium">Symbol</th>
          <th className="px-1.5 py-1 font-medium">Metric</th>
          <th className="px-1.5 py-1 font-medium">Direction</th>
          <th className="px-1.5 py-1 text-right font-medium">Δ</th>
          <th className="px-1.5 py-1 font-medium">Change</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((d, i) => (
          <tr key={i} className="border-b border-surface-border/40 last:border-0">
            <td className="px-1.5 py-1 text-slate-200">{d.symbol ?? "market"}</td>
            <td className="px-1.5 py-1 text-slate-400">{d.metric}</td>
            <td
              className={`px-1.5 py-1 ${d.direction === "UPGRADE" ? "text-emerald-400" : "text-bear"}`}
            >
              {d.direction}
            </td>
            <td className="px-1.5 py-1 text-right tabular-nums text-slate-300">
              {d.delta != null ? signed(d.delta, 2) : "—"}
            </td>
            <td className="px-1.5 py-1 text-slate-400">{d.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ReplayPanel({ id }: { id: number }) {
  const snapshot = useApi<ScanSnapshotDetail>(`/timeline/${id}`);
  if (snapshot.loading) return <Loading />;
  if (snapshot.error) return <ErrorBox message={snapshot.error} />;
  const payload = snapshot.data?.payload as
    | {
        regime?: { regime?: string | null; breadth?: number | null };
        candidates?: Record<string, Record<string, number | string | null>>;
        watchlists?: Record<string, string[]>;
        sectors?: Record<string, number>;
      }
    | undefined;
  if (!payload) return null;

  const candidates = Object.entries(payload.candidates ?? {})
    .sort((x, y) => Number(x[1]["rank"] ?? 999) - Number(y[1]["rank"] ?? 999))
    .slice(0, 15);

  return (
    <Card
      title={`Replay · snapshot #${id} · ${fmtTime(snapshot.data?.scan_ts ?? null)} · ${snapshot.data?.market_state ?? ""}`}
    >
      <div className="grid gap-4 md:grid-cols-[2fr,1fr]">
        <table className="w-full text-xs">
          <thead className="text-[10px] uppercase tracking-wide text-slate-500">
            <tr className="border-b border-surface-border text-left">
              <th className="px-1.5 py-1 font-medium">#</th>
              <th className="px-1.5 py-1 font-medium">Symbol</th>
              <th className="px-1.5 py-1 text-right font-medium">Price</th>
              <th className="px-1.5 py-1 text-right font-medium">Conviction</th>
              <th className="px-1.5 py-1 text-right font-medium">Momentum</th>
              <th className="px-1.5 py-1 font-medium">Sector</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map(([symbol, c]) => (
              <tr key={symbol} className="border-b border-surface-border/40 last:border-0">
                <td className="px-1.5 py-1 text-slate-500">{String(c["rank"] ?? "—")}</td>
                <td className="px-1.5 py-1 text-slate-200">{symbol}</td>
                <td className="px-1.5 py-1 text-right tabular-nums text-slate-300">
                  {c["price"] != null ? num(Number(c["price"]), 2) : "—"}
                </td>
                <td className="px-1.5 py-1 text-right tabular-nums text-slate-300">
                  {c["conviction"] != null ? num(Number(c["conviction"]), 0) : "—"}
                </td>
                <td className="px-1.5 py-1 text-right tabular-nums text-slate-300">
                  {c["momentum"] != null ? num(Number(c["momentum"]), 1) : "—"}
                </td>
                <td className="px-1.5 py-1 text-slate-400">{String(c["sector"] ?? "—")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="space-y-3 text-xs">
          <div>
            <div className="mb-0.5 text-[10px] uppercase tracking-wide text-slate-500">Regime</div>
            <span className="text-slate-200">{payload.regime?.regime ?? "—"}</span>
            {payload.regime?.breadth != null ? (
              <span className="ml-2 text-slate-400">
                breadth {num(payload.regime.breadth * 100, 0)}%
              </span>
            ) : null}
          </div>
          {Object.entries(payload.watchlists ?? {}).map(([horizon, symbols]) => (
            <div key={horizon}>
              <div className="mb-0.5 text-[10px] uppercase tracking-wide text-slate-500">
                {horizon} watchlist
              </div>
              <span className="text-slate-300">{symbols.slice(0, 5).join(", ") || "—"}</span>
            </div>
          ))}
          <div>
            <div className="mb-0.5 text-[10px] uppercase tracking-wide text-slate-500">Sectors</div>
            {Object.entries(payload.sectors ?? {})
              .sort((x, y) => y[1] - x[1])
              .slice(0, 5)
              .map(([sector, score]) => (
                <div key={sector} className="flex justify-between text-slate-300">
                  <span>{sector}</span>
                  <span className="tabular-nums">{num(score, 2)}</span>
                </div>
              ))}
          </div>
        </div>
      </div>
    </Card>
  );
}

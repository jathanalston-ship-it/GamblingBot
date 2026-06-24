import { useEffect, useState } from "react";
import { ProvenancePanel } from "../components/ProvenancePanel";

import { apiGet } from "../api/client";
import type { WatchlistComparison, WatchlistEntry, WatchlistSet } from "../api/types";
import { ActionButton } from "../components/ActionButton";
import { Badge, type Tone } from "../components/Badge";
import { Card } from "../components/Card";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { useApi } from "../hooks/useApi";
import { num, pct, signed } from "../lib/format";
import { useWorkspace } from "../state/workspace";

function riskTone(rating: string): Tone {
  if (rating === "Low") return "bull";
  if (rating === "High") return "bear";
  if (rating === "Medium") return "neutral";
  return "default";
}

export default function Watchlists() {
  const { runId } = useWorkspace();
  const runQ = runId ? `&run_id=${runId}` : "";
  const runQ1 = runId ? `?run_id=${runId}` : "";

  const [horizon, setHorizon] = useState("daily");
  const [date, setDate] = useState<string>(""); // "" = latest
  const [compare, setCompare] = useState(false);

  const dates = useApi<string[]>(`/watchlists/dates${runQ1}`);
  const set = useApi<WatchlistSet>(`/watchlists?1=1${runQ}${date ? `&as_of=${date}` : ""}`);

  const horizons = set.data?.horizons ?? [];
  const active = horizons.find((h) => h.horizon === horizon) ?? horizons[0];

  // keep the active horizon valid as data loads
  useEffect(() => {
    if (horizons.length > 0 && !horizons.some((h) => h.horizon === horizon)) {
      setHorizon(horizons[0].horizon);
    }
  }, [horizons, horizon]);

  return (
    <div className="p-5">
      <ProvenancePanel screen="watchlists" />
      <PageTitle
        title="Watchlists"
        subtitle="Actionable multi-horizon watchlists — Today · This Week · This Month"
      >
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-slate-400">
            date
            <select
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="rounded border border-surface-border bg-surface px-2 py-1 text-slate-200"
            >
              <option value="">latest</option>
              {(dates.data ?? []).map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={() => setCompare((c) => !c)}
            className={`rounded border px-2.5 py-1 text-xs ${
              compare
                ? "border-accent/40 bg-accent/10 text-accent"
                : "border-surface-border text-slate-400 hover:text-slate-200"
            }`}
          >
            Compare
          </button>
          <ActionButton
            label="Generate"
            path="/actions/generate-watchlists"
            body={runId ? { run_id: runId } : undefined}
            onDone={() => {
              set.reload();
              dates.reload();
            }}
          />
        </div>
      </PageTitle>

      {/* horizon tabs */}
      <div className="mb-4 flex gap-1">
        {horizons.map((h) => (
          <button
            key={h.horizon}
            onClick={() => setHorizon(h.horizon)}
            className={`rounded px-3 py-1.5 text-sm ${
              h.horizon === active?.horizon
                ? "bg-accent/15 text-accent"
                : "text-slate-300 hover:bg-surface/60"
            }`}
          >
            {h.label}
            <span className="ml-1.5 text-xs text-slate-500">{h.entries.length}</span>
          </button>
        ))}
      </div>

      {set.loading ? (
        <Loading />
      ) : set.error ? (
        <ErrorBox message={set.error} />
      ) : compare ? (
        <ComparePanel horizon={active?.horizon ?? "daily"} dates={dates.data ?? []} runId={runId} />
      ) : active && active.entries.length > 0 ? (
        <WatchlistTable entries={active.entries} />
      ) : (
        <div className="rounded-lg border border-surface-border bg-surface-raised p-8 text-center text-sm text-slate-500">
          <div className="mb-1 font-medium text-slate-400">No live conviction data available</div>
          Watchlists rank the latest live conviction scores. Click{" "}
          <b className="text-slate-300">Generate</b> after running a scan (Settings → Scanner) so
          live conviction exists — watchlists never fall back to demo data.
        </div>
      )}
    </div>
  );
}

function WatchlistTable({ entries }: { entries: WatchlistEntry[] }) {
  return (
    <Card title={`${entries[0]?.horizon_label ?? ""} · ${entries.length} names · ${entries[0]?.horizon_days ?? 0}d horizon`}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs uppercase tracking-wide text-slate-400">
            <tr className="border-b border-surface-border text-left">
              <th className="px-2 py-1.5 text-right font-medium">#</th>
              <th className="px-2 py-1.5 font-medium">Ticker</th>
              <th className="px-2 py-1.5 text-right font-medium">Conviction</th>
              <th className="px-2 py-1.5 font-medium">Sector</th>
              <th className="px-2 py-1.5 font-medium">Risk</th>
              <th className="px-2 py-1.5 text-right font-medium">Move %</th>
              <th className="px-2 py-1.5 text-right font-medium">Risk %</th>
              <th className="px-2 py-1.5 text-right font-medium">R/R</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id} className="border-b border-surface-border/40 hover:bg-surface/40">
                <td className="px-2 py-1.5 text-right tabular-nums text-slate-500">{e.rank}</td>
                <td className="px-2 py-1.5 font-medium text-slate-100">{e.symbol}</td>
                <td className="px-2 py-1.5 text-right tabular-nums">
                  <span className="text-slate-100">{num(e.conviction, 0)}</span>
                  {e.band ? <span className="ml-1 text-[10px] uppercase text-slate-500">{e.band}</span> : null}
                </td>
                <td className="px-2 py-1.5 text-slate-400">{e.sector ?? "—"}</td>
                <td className="px-2 py-1.5">
                  <Badge tone={riskTone(e.risk_rating)}>{e.risk_rating}</Badge>
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                  {e.expected_move_pct == null ? "—" : pct(e.expected_move_pct, 1)}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                  {e.expected_risk_pct == null ? "—" : pct(e.expected_risk_pct, 1)}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">
                  <span className={(e.reward_risk ?? 0) >= 1 ? "text-bull" : "text-slate-300"}>
                    {e.reward_risk == null ? "—" : `${num(e.reward_risk, 2)}x`}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function ComparePanel({
  horizon,
  dates,
  runId,
}: {
  horizon: string;
  dates: string[];
  runId: string | null;
}) {
  const [base, setBase] = useState("");
  const [against, setAgainst] = useState("");
  const [data, setData] = useState<WatchlistComparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // default to the two most recent generations
  useEffect(() => {
    if (dates.length >= 2 && !base && !against) {
      setAgainst(dates[0]);
      setBase(dates[1]);
    }
  }, [dates, base, against]);

  useEffect(() => {
    if (!base || !against || base === against) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    const runQ = runId ? `&run_id=${runId}` : "";
    apiGet<WatchlistComparison>(
      `/watchlists/compare?horizon=${horizon}&base=${base}&against=${against}${runQ}`,
    )
      .then((d) => !cancelled && setData(d))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [horizon, base, against, runId]);

  const picker = (value: string, onChange: (v: string) => void, label: string) => (
    <label className="flex items-center gap-1.5 text-xs text-slate-400">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-surface-border bg-surface px-2 py-1 text-slate-200"
      >
        <option value="">—</option>
        {dates.map((d) => (
          <option key={d} value={d}>
            {d}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        {picker(base, setBase, "from")}
        {picker(against, setAgainst, "to")}
        <span className="text-xs text-slate-500">comparing the {horizon} watchlist</span>
      </div>

      {dates.length < 2 ? (
        <div className="text-sm text-slate-500">Generate the watchlists on at least two dates to compare.</div>
      ) : loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} />
      ) : !data ? (
        <div className="text-sm text-slate-500">Pick two different dates.</div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Card title={`Entered (${data.added.length})`}>
            <SymbolList rows={data.added.map((e) => ({ symbol: e.symbol, note: `#${e.rank}` }))} tone="bull" empty="No new names." />
          </Card>
          <Card title={`Dropped (${data.removed.length})`}>
            <SymbolList rows={data.removed.map((e) => ({ symbol: e.symbol, note: `was #${e.rank}` }))} tone="bear" empty="Nothing dropped." />
          </Card>
          <Card title={`Held (${data.moved.length})`}>
            {data.moved.length === 0 ? (
              <div className="py-4 text-center text-sm text-slate-500">No overlap.</div>
            ) : (
              <ul className="flex flex-col gap-1 text-sm">
                {data.moved.map((m) => (
                  <li key={m.symbol} className="flex items-center justify-between gap-2 border-b border-surface-border/40 py-1">
                    <span className="font-medium text-slate-200">{m.symbol}</span>
                    <span className="flex items-center gap-3 text-xs tabular-nums">
                      <span className="text-slate-400">
                        #{m.base_rank} → #{m.against_rank}
                      </span>
                      <span className={m.rank_change > 0 ? "text-bull" : m.rank_change < 0 ? "text-bear" : "text-slate-500"}>
                        {m.rank_change > 0 ? "▲" : m.rank_change < 0 ? "▼" : "—"}
                        {m.rank_change !== 0 ? Math.abs(m.rank_change) : ""}
                      </span>
                      <span className={m.conviction_change >= 0 ? "text-bull" : "text-bear"}>
                        {signed(m.conviction_change, 0)}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

function SymbolList({
  rows,
  tone,
  empty,
}: {
  rows: { symbol: string; note: string }[];
  tone: "bull" | "bear";
  empty: string;
}) {
  if (rows.length === 0) return <div className="py-4 text-center text-sm text-slate-500">{empty}</div>;
  return (
    <ul className="flex flex-col gap-1 text-sm">
      {rows.map((r) => (
        <li key={r.symbol} className="flex items-center justify-between gap-2 border-b border-surface-border/40 py-1">
          <span className={`font-medium ${tone === "bull" ? "text-bull" : "text-bear"}`}>{r.symbol}</span>
          <span className="text-xs tabular-nums text-slate-500">{r.note}</span>
        </li>
      ))}
    </ul>
  );
}

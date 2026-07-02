import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ProvenancePanel } from "../components/ProvenancePanel";

import type { Job, ScanMetadata, ScanResult } from "../api/types";
import { ActionButton } from "../components/ActionButton";
import { Badge } from "../components/Badge";
import { Inspector } from "../components/Inspector";
import { useApi } from "../hooks/useApi";
import { fmtAge, fmtTime, num, pct } from "../lib/format";
import { useWorkspace } from "../state/workspace";

type SortKey = "rank" | "momentum_score" | "relative_volume" | "distance_from_ath";

const SORTABLE: { key: SortKey; defaultDir: 1 | -1 }[] = [
  { key: "rank", defaultDir: 1 },
  { key: "momentum_score", defaultDir: -1 },
  { key: "relative_volume", defaultDir: -1 },
  { key: "distance_from_ath", defaultDir: -1 },
];

/**
 * Stage 1 (Scan) — the full ranked universe. With `shortlist`, it becomes
 * Stage 2 (Candidates): the passed-gate tradeable set only.
 */
export default function Scan({ shortlist = false }: { shortlist?: boolean }) {
  const { runId, symbol, setSymbol } = useWorkspace();
  const [passedOnly, setPassedOnly] = useState(shortlist);
  const [sector, setSector] = useState<string>("all");
  const [scanStats, setScanStats] = useState<Record<string, unknown> | null>(null);
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "rank", dir: 1 });
  const navigate = useNavigate();

  const effectivePassed = shortlist || passedOnly;
  // The API caps at 2000, which also equals the scanner's liquidity prefilter cap
  // (MRP_MAX_SCAN_SYMBOLS) — so passed candidates can never exceed it and this
  // ceiling can't silently truncate real data. A hint shows if it's ever reached.
  const ROW_LIMIT = 2000;
  const path = `/universe/scans?limit=${ROW_LIMIT}${effectivePassed ? "&passed_only=true" : ""}${
    runId ? `&run_id=${runId}` : ""
  }`;
  const { data, error, loading, reload } = useApi<ScanResult[]>(path);
  const all = useMemo(() => data ?? [], [data]);
  const { data: meta, reload: reloadMeta } = useApi<ScanMetadata | null>("/universe/scan-metadata");

  const sectors = useMemo(
    () => Array.from(new Set(all.map((r) => r.sector).filter((s): s is string => !!s))).sort(),
    [all],
  );

  const rows = useMemo(() => {
    const filtered = sector === "all" ? all : all.filter((r) => r.sector === sector);
    const { key, dir } = sort;
    return [...filtered].sort((a, b) => {
      const av = (a[key] as number | null) ?? 0;
      const bv = (b[key] as number | null) ?? 0;
      return (av - bv) * dir;
    });
  }, [all, sector, sort]);

  const idx = Math.max(
    0,
    rows.findIndex((r) => r.symbol === symbol),
  );

  useEffect(() => {
    if (!symbol && rows.length > 0) setSymbol(rows[0].symbol);
  }, [symbol, rows, setSymbol]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
      if (rows.length === 0) return;
      if (e.key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        setSymbol(rows[Math.min(idx + 1, rows.length - 1)].symbol);
      } else if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        setSymbol(rows[Math.max(idx - 1, 0)].symbol);
      } else if (e.key === "Enter") {
        navigate("/conviction");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, idx, setSymbol, navigate]);

  const onSort = (key: SortKey): void =>
    setSort((s) =>
      s.key === key
        ? { key, dir: (s.dir * -1) as 1 | -1 }
        : { key, dir: SORTABLE.find((c) => c.key === key)?.defaultDir ?? 1 },
    );
  const caret = (key: SortKey): string => (sort.key === key ? (sort.dir === 1 ? " ▲" : " ▼") : "");

  return (
    <div className="grid h-full grid-cols-[1fr_22rem]">
      <div className="flex min-w-0 flex-col border-r border-surface-border">
        <div className="flex items-center gap-3 border-b border-surface-border px-3 py-2 text-sm">
          <ActionButton
            label="Run scan"
            path="/actions/scan"
            onDone={(job: Job) => {
              if (job.status === "succeeded" && job.result)
                setScanStats(job.result as Record<string, unknown>);
              reload();
              reloadMeta();
            }}
          />
          <span className="text-slate-500">
            {rows.length} {shortlist ? "candidates · passed" : "candidates"}
            {all.length >= ROW_LIMIT ? (
              <span className="ml-1 text-neutral" title={`Showing the first ${ROW_LIMIT} rows.`}>
                (first {ROW_LIMIT})
              </span>
            ) : null}
          </span>
          <label className="flex items-center gap-1.5 text-slate-400">
            sector
            <select
              value={sector}
              onChange={(e) => setSector(e.target.value)}
              className="rounded border border-surface-border bg-surface px-2 py-1 text-slate-200"
            >
              <option value="all">all</option>
              {sectors.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          {!shortlist ? (
            <label className="ml-auto flex items-center gap-1.5 text-slate-400">
              <input
                type="checkbox"
                checked={passedOnly}
                onChange={(e) => setPassedOnly(e.target.checked)}
              />
              passed only
            </label>
          ) : (
            <span className="ml-auto text-xs text-slate-500">tradeable set (gate passed)</span>
          )}
        </div>

        {meta ? (
          <div
            className={`flex flex-wrap items-center gap-4 border-b px-3 py-1.5 text-xs ${
              meta.stale
                ? "border-bear/40 bg-bear/10 text-bear"
                : "border-surface-border bg-surface-raised/40 text-slate-400"
            }`}
          >
            {meta.stale ? (
              <span className="rounded bg-bear px-1.5 py-0.5 text-[10px] font-bold uppercase text-white">
                Stale Data
              </span>
            ) : null}
            <Stat label="provider" value={meta.provider} />
            <Stat label="symbols" value={num(meta.symbol_count, 0)} />
            <Stat label="data age" value={fmtAge(meta.data_age_minutes)} />
            <Stat label="last pull" value={fmtTime(meta.pull_timestamp)} />
            {meta.stale ? (
              <span className="text-bear">conviction not generated — data too old</span>
            ) : null}
          </div>
        ) : null}

        <div className="px-3 pt-2">
          <ProvenancePanel screen="scan" />
        </div>

        {scanStats ? (
          <div className="flex flex-wrap items-center gap-4 border-b border-surface-border bg-surface-raised/40 px-3 py-1.5 text-xs text-slate-400">
            {scanStats.universe_label ? (
              <Stat label="universe" value={String(scanStats.universe_label)} />
            ) : null}
            <Stat label="size" value={num(Number(scanStats.universe_size ?? 0), 0)} />
            <Stat label="scanned" value={num(Number(scanStats.symbols_scanned ?? 0), 0)} />
            <Stat label="passed" value={num(Number(scanStats.symbols_passed ?? 0), 0)} />
            <Stat
              label="duration"
              value={`${Math.round(Number(scanStats.duration_ms ?? 0))} ms`}
            />
          </div>
        ) : null}

        <div className="min-h-0 flex-1 overflow-auto">
          {loading ? (
            <div className="p-6 text-sm text-slate-500">Loading…</div>
          ) : error ? (
            <div className="p-6 text-sm text-bear">Failed: {error}</div>
          ) : rows.length === 0 ? (
            <div className="p-6 text-sm text-slate-500">No scan results — run a scan.</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface-raised text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  <Th onClick={() => onSort("rank")} align="right">
                    #{caret("rank")}
                  </Th>
                  <th className="px-3 py-2 text-left font-medium">Sym</th>
                  <Th onClick={() => onSort("momentum_score")} align="right">
                    Score{caret("momentum_score")}
                  </Th>
                  <Th onClick={() => onSort("relative_volume")} align="right">
                    RVol{caret("relative_volume")}
                  </Th>
                  <Th onClick={() => onSort("distance_from_ath")} align="right">
                    ΔATH{caret("distance_from_ath")}
                  </Th>
                  <th className="px-3 py-2 text-right font-medium" title="20-day average dollar volume">
                    $ADV
                  </th>
                  <th className="px-3 py-2 text-right font-medium" title="Average true range (14)">
                    ATR
                  </th>
                  <th className="px-3 py-2 text-left font-medium">Sector</th>
                  <th className="px-3 py-2 text-left font-medium">Gate</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.symbol}
                    onClick={() => setSymbol(r.symbol)}
                    className={`cursor-pointer border-b border-surface-border/40 ${
                      r.symbol === symbol ? "bg-accent/15" : "hover:bg-surface/40"
                    }`}
                  >
                    <td className="px-3 py-1.5 text-right tabular-nums text-slate-400">
                      {num(r.rank, 0)}
                    </td>
                    <td className="px-3 py-1.5 font-medium text-slate-100">{r.symbol}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{num(r.momentum_score, 3)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {num(r.relative_volume, 2)}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {pct(r.distance_from_ath)}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-slate-400">
                      {typeof r["dollar_volume"] === "number"
                        ? `$${num(r["dollar_volume"] / 1e6, 0)}M`
                        : "—"}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-slate-400">
                      {typeof r["atr"] === "number" ? num(r["atr"], 2) : "—"}
                    </td>
                    <td className="px-3 py-1.5 text-slate-400">{r.sector ?? "—"}</td>
                    <td className="px-3 py-1.5">
                      {r.passed ? <Badge tone="bull">pass</Badge> : <Badge tone="bear">fail</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <Inspector symbol={symbol} />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex items-baseline gap-1">
      <span className="uppercase tracking-wide text-slate-500">{label}</span>
      <span className="tabular-nums text-slate-200">{value}</span>
    </span>
  );
}

function Th({
  children,
  onClick,
  align = "left",
}: {
  children: React.ReactNode;
  onClick: () => void;
  align?: "left" | "right";
}) {
  return (
    <th
      onClick={onClick}
      className={`cursor-pointer select-none px-3 py-2 font-medium hover:text-slate-200 ${
        align === "right" ? "text-right" : "text-left"
      }`}
    >
      {children}
    </th>
  );
}

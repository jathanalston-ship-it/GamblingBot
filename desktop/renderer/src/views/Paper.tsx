import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import type { AuditEvent, PortfolioSnapshot, RunDetail, Signal, Trade } from "../api/types";
import { ActionButton } from "../components/ActionButton";
import { Badge, regimeTone, type Tone } from "../components/Badge";
import { Card } from "../components/Card";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { Stat } from "../components/Stat";
import { useApi, type ApiState } from "../hooks/useApi";
import { date, money, num, pct, signed } from "../lib/format";
import { useWorkspace } from "../state/workspace";

/** 7 · Paper Trading — live paper account, sessions, positions and audit trail. */
export default function Paper() {
  const navigate = useNavigate();
  const { setRunId, setSymbol } = useWorkspace();
  const [run, setRun] = useState<string | null>(null); // selected session (null = all)
  const [showAudit, setShowAudit] = useState(false);
  const runQ = run ? `&run_id=${run}` : "";

  const runs = useApi<RunDetail[]>("/runs/recent?limit=12");
  const snaps = useApi<PortfolioSnapshot[]>("/portfolio/snapshots?limit=400");
  const openT = useApi<Trade[]>(`/trades?status=open&limit=200${runQ}`);
  const closedT = useApi<Trade[]>(`/trades?status=closed&limit=200${runQ}`);
  const sigs = useApi<Signal[]>(`/signals?limit=25${runQ}`);
  const aud = useApi<AuditEvent[]>(`/audit?limit=40${runQ}`);

  // Default the selection to the most recent paper session.
  useEffect(() => {
    if (run === null && runs.data && runs.data.length > 0) setRun(runs.data[0].run_id);
  }, [run, runs.data]);

  const reloadAll = (): void => {
    runs.reload();
    snaps.reload();
    openT.reload();
    closedT.reload();
    sigs.reload();
    aud.reload();
  };

  // Headline account stats from the latest snapshot of the selected run (or any).
  const latest = useMemo<PortfolioSnapshot | null>(() => {
    const rows = (snaps.data ?? []).filter((s) => !run || s.run_id === run);
    const pool = rows.length > 0 ? rows : (snaps.data ?? []);
    return pool.length > 0 ? pool[pool.length - 1] : null;
  }, [snaps.data, run]);

  const closedPnl = (closedT.data ?? []).reduce((a, t) => a + (t.net_pnl ?? 0), 0);
  const totalPnl = latest?.realized_pnl ?? (closedT.data ? closedPnl : null);
  const dailyPnl =
    latest?.daily_pnl ??
    (latest?.daily_return != null && latest?.equity != null
      ? latest.equity * latest.daily_return
      : null);

  const selectedRun = (runs.data ?? []).find((r) => r.run_id === run) ?? null;

  const openReplay = (t: Trade): void => {
    setRunId(t.run_id ?? run);
    setSymbol(t.symbol);
    navigate("/replay");
  };

  return (
    <div className="p-5">
      <PageTitle title="Paper Trading" subtitle="Live paper account, sessions, positions & audit">
        <div className="flex items-center gap-2">
          <ActionButton label="Refresh data" path="/actions/refresh-data" variant="ghost" />
          <ActionButton label="Run paper session" path="/actions/paper-session" onDone={reloadAll} />
        </div>
      </PageTitle>

      {/* headline account stats */}
      <div className="mb-5 grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat
          label="Account Equity"
          value={money(latest?.equity ?? null)}
          hint={latest ? `as of ${date(latest.session_date)}` : "no activity yet"}
        />
        <Stat label="Daily P&L" value={<Pnl v={dailyPnl} />} />
        <Stat label="Total P&L" value={<Pnl v={totalPnl} />} />
        <Stat
          label="Portfolio Heat"
          value={latest?.portfolio_heat != null ? pct(latest.portfolio_heat, 1) : "—"}
          hint={latest?.num_positions != null ? `${latest.num_positions} positions` : undefined}
        />
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        {/* left: positions */}
        <div className="flex flex-col gap-5 lg:col-span-2">
          <Card
            title={`Open Positions · ${openT.data?.length ?? 0}`}
            action={<RunFilterNote run={run} />}
          >
            <Async
              state={openT}
              empty="No open positions. Run a paper session to enter trades."
            >
              {(rows) => (
                <TradeTable
                  rows={rows}
                  onPick={openReplay}
                  kind="open"
                  equity={latest?.equity ?? null}
                />
              )}
            </Async>
            <p className="mt-2 text-xs text-slate-500">
              Mark-to-market (live price / unrealized P&amp;L) requires a market-data feed — coming
              with the quotes endpoint.
            </p>
          </Card>

          <Card title={`Closed Positions · ${closedT.data?.length ?? 0}`}>
            <Async state={closedT} empty="No closed positions yet.">
              {(rows) => (
                <TradeTable rows={rows} onPick={openReplay} kind="closed" equity={null} />
              )}
            </Async>
          </Card>

          <Card title={`Recent Signals · ${sigs.data?.length ?? 0}`}>
            <Async state={sigs} empty="No signals recorded.">
              {(rows) => <SignalTable rows={rows} />}
            </Async>
          </Card>
        </div>

        {/* right: sessions, details, audit */}
        <div className="flex flex-col gap-5">
          <Card title="Recent Paper Sessions">
            <Async state={runs} empty="No sessions yet. Click “Run paper session”.">
              {(rows) => (
                <SessionList rows={rows} selected={run} onSelect={setRun} />
              )}
            </Async>
          </Card>

          {selectedRun ? (
            <Card
              title="Session Details"
              action={
                <button
                  onClick={() => {
                    setRunId(selectedRun.run_id);
                    navigate("/replay");
                  }}
                  className="rounded bg-accent/15 px-2 py-1 text-xs text-accent hover:bg-accent/25"
                >
                  Open in Replay →
                </button>
              }
            >
              <SessionDetail run={selectedRun} />
            </Card>
          ) : null}

          {showAudit ? (
            <Card
              title={`Recent Audit Events · ${aud.data?.length ?? 0}`}
              action={
                <button
                  onClick={() => setShowAudit(false)}
                  className="rounded bg-surface px-2 py-1 text-xs text-slate-400 hover:text-slate-200"
                >
                  Hide
                </button>
              }
            >
              <Async state={aud} empty="No audit events.">
                {(rows) => <AuditList rows={rows} />}
              </Async>
            </Card>
          ) : (
            <button
              onClick={() => setShowAudit(true)}
              className="self-start rounded border border-surface-border bg-surface-raised px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              Show audit trail
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── small building blocks ──────────────────────────────────────────────── */

function Pnl({ v }: { v: number | null }): ReactNode {
  if (v == null) return <span className="text-slate-500">—</span>;
  return <span className={v >= 0 ? "text-bull" : "text-bear"}>{signed(v, 0)}</span>;
}

function RunFilterNote({ run }: { run: string | null }): ReactNode {
  return run ? (
    <span className="text-xs text-slate-500">
      session <b className="text-slate-300">{run}</b>
    </span>
  ) : (
    <span className="text-xs text-slate-500">all sessions</span>
  );
}

/** Loading / error / empty wrapper around a list-bearing API hook. */
function Async<T>({
  state,
  empty,
  children,
}: {
  state: ApiState<T[]>;
  empty: string;
  children: (rows: T[]) => ReactNode;
}): ReactNode {
  if (state.loading) return <Loading />;
  if (state.error) return <ErrorBox message={state.error} />;
  const rows = state.data ?? [];
  if (rows.length === 0) return <div className="py-6 text-center text-sm text-slate-500">{empty}</div>;
  return <>{children(rows)}</>;
}

function TradeTable({
  rows,
  onPick,
  kind,
  equity,
}: {
  rows: Trade[];
  onPick: (t: Trade) => void;
  kind: "open" | "closed";
  equity: number | null;
}): ReactNode {
  const open = kind === "open";
  return (
    <table className="w-full text-sm">
      <thead className="text-xs uppercase tracking-wide text-slate-400">
        <tr className="border-b border-surface-border text-left">
          <th className="px-2 py-1.5 font-medium">Symbol</th>
          <th className="px-2 py-1.5 text-right font-medium">Qty</th>
          <th className="px-2 py-1.5 text-right font-medium">Entry</th>
          <th className="px-2 py-1.5 text-right font-medium">{open ? "Opened" : "Exit"}</th>
          {open ? (
            <>
              <th className="px-2 py-1.5 text-right font-medium">% Equity</th>
              <th className="px-2 py-1.5 text-right font-medium">Heat</th>
            </>
          ) : (
            <th className="px-2 py-1.5 text-right font-medium">Net P&L</th>
          )}
        </tr>
      </thead>
      <tbody>
        {rows.map((t, i) => {
          const notional =
            t.quantity != null && t.entry_price != null ? t.quantity * t.entry_price : null;
          const pctEquity =
            notional != null && equity != null && equity !== 0 ? notional / equity : null;
          const heat =
            t.initial_risk != null && equity != null && equity !== 0
              ? t.initial_risk / equity
              : null;
          return (
            <tr
              key={t.id ?? i}
              onClick={() => onPick(t)}
              className="cursor-pointer border-b border-surface-border/40 hover:bg-surface/50"
              title="Open in Replay"
            >
              <td className="px-2 py-1.5 font-medium text-slate-200">{t.symbol}</td>
              <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">{num(t.quantity, 0)}</td>
              <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">{money(t.entry_price)}</td>
              <td className="px-2 py-1.5 text-right tabular-nums text-slate-400">
                {date(open ? t.entry_ts : t.exit_ts)}
              </td>
              {open ? (
                <>
                  <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                    {pctEquity != null ? pct(pctEquity, 1) : "—"}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                    {heat != null ? pct(heat, 2) : "—"}
                  </td>
                </>
              ) : (
                <td className="px-2 py-1.5 text-right tabular-nums">
                  <span className={(t.net_pnl ?? 0) >= 0 ? "text-bull" : "text-bear"}>
                    {money(t.net_pnl)}
                  </span>
                </td>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function SignalTable({ rows }: { rows: Signal[] }): ReactNode {
  return (
    <ul className="flex flex-col gap-1 text-sm">
      {rows.map((s) => (
        <li key={s.id} className="flex items-center justify-between gap-2 border-b border-surface-border/40 py-1">
          <span className="flex items-center gap-2">
            <span className="font-medium text-slate-200">{s.symbol}</span>
            <span className="text-xs text-slate-500">{s.signal_type ?? "—"}</span>
          </span>
          <span className="flex items-center gap-3 text-xs tabular-nums text-slate-400">
            <span>mom {num(s.momentum_score, 0)}</span>
            <span>{date(s.ts)}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function SessionList({
  rows,
  selected,
  onSelect,
}: {
  rows: RunDetail[];
  selected: string | null;
  onSelect: (id: string | null) => void;
}): ReactNode {
  return (
    <ul className="flex flex-col gap-1">
      {rows.map((r) => {
        const active = r.run_id === selected;
        const pnl = r.equity_end != null && r.equity_start != null ? r.equity_end - r.equity_start : null;
        return (
          <li key={r.run_id}>
            <button
              onClick={() => onSelect(active ? null : r.run_id)}
              className={`flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-sm ${
                active ? "bg-accent/20 ring-1 ring-accent/40" : "hover:bg-surface/60"
              }`}
            >
              <span className="flex flex-col">
                <span className="font-medium text-slate-200">{r.run_id}</span>
                <span className="text-xs text-slate-500">
                  {date(r.as_of)} · {r.num_opened ?? 0}↑ / {r.num_closed ?? 0}↓
                </span>
              </span>
              <span className="flex items-center gap-2">
                <Badge tone={statusTone(r.status)}>{r.status}</Badge>
                {pnl != null ? (
                  <span className={`text-xs tabular-nums ${pnl >= 0 ? "text-bull" : "text-bear"}`}>
                    {signed(pnl, 0)}
                  </span>
                ) : null}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function SessionDetail({ run }: { run: RunDetail }): ReactNode {
  const pnl = run.equity_end != null && run.equity_start != null ? run.equity_end - run.equity_start : null;
  const rows: [string, ReactNode][] = [
    ["Status", <Badge tone={statusTone(run.status)}>{run.status}</Badge>],
    ["Mode", run.mode],
    ["As of", date(run.as_of)],
    ["Started", run.started_at ? run.started_at.replace("T", " ").slice(0, 16) : "—"],
    ["Finished", run.finished_at ? run.finished_at.replace("T", " ").slice(0, 16) : "—"],
    ["Equity", `${money(run.equity_start)} → ${money(run.equity_end)}`],
    ["Session P&L", <Pnl v={pnl} />],
    ["Opened / Closed", `${run.num_opened ?? 0} / ${run.num_closed ?? 0}`],
  ];
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="flex flex-col">
          <dt className="text-xs uppercase tracking-wide text-slate-500">{k}</dt>
          <dd className="text-slate-200">{v}</dd>
        </div>
      ))}
      {run.error ? (
        <div className="col-span-2 rounded bg-bear/10 p-2 text-xs text-bear">{run.error}</div>
      ) : null}
    </dl>
  );
}

function AuditList({ rows }: { rows: AuditEvent[] }): ReactNode {
  return (
    <ul className="flex max-h-80 flex-col gap-0.5 overflow-auto text-xs">
      {rows.map((e) => (
        <li key={e.id} className="flex items-baseline gap-2 border-b border-surface-border/30 py-1">
          <span className="w-28 shrink-0 text-slate-500">
            {e.ts ? e.ts.replace("T", " ").slice(5, 16) : "—"}
          </span>
          <span className="w-32 shrink-0 font-medium text-slate-300">{e.event_type}</span>
          <span className="truncate text-slate-400" title={e.summary ?? ""}>
            {e.summary ?? e.symbol ?? ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

/* ── helpers ────────────────────────────────────────────────────────────── */

function statusTone(status: string): Tone {
  const s = status.toLowerCase();
  if (s === "completed") return "bull";
  if (s === "failed") return "bear";
  if (s === "running") return "neutral";
  return regimeTone(status);
}

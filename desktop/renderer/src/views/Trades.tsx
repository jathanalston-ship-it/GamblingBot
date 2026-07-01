import { useMemo, useState } from "react";

import type {
  JournalEntry,
  ManagementAnalytics,
  TrackedTrade,
  TradeEvaluation,
} from "../api/types";
import { ActionButton } from "../components/ActionButton";
import { Card } from "../components/Card";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { Stat } from "../components/Stat";
import { useApi } from "../hooks/useApi";
import { date, num, signed } from "../lib/format";

/* Health = the trade's battery percentage. Color by band. */
function healthColor(score: number | null): string {
  if (score == null) return "text-slate-400";
  if (score >= 75) return "text-emerald-400";
  if (score >= 55) return "text-accent";
  if (score >= 35) return "text-amber-400";
  return "text-bear";
}

function healthBar(score: number | null): string {
  if (score == null) return "bg-slate-600";
  if (score >= 75) return "bg-emerald-400";
  if (score >= 55) return "bg-accent";
  if (score >= 35) return "bg-amber-400";
  return "bg-bear";
}

const ACTION_CLASS: Record<string, string> = {
  Hold: "bg-slate-600/30 text-slate-300",
  "Scale In": "bg-emerald-500/20 text-emerald-300",
  "Scale Out": "bg-amber-500/20 text-amber-300",
  "Raise Stop": "bg-indigo-500/20 text-indigo-300",
  "Lower Stop": "bg-sky-500/20 text-sky-300",
  Exit: "bg-bear/20 text-bear",
};

function ActionBadge({ action }: { action: string | null }) {
  if (!action) return null;
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-xs font-medium ${ACTION_CLASS[action] ?? "bg-surface-border text-slate-300"}`}
    >
      {action}
    </span>
  );
}

function Battery({ score }: { score: number | null }) {
  const pctWidth = Math.max(0, Math.min(100, score ?? 0));
  return (
    <div className="h-1.5 w-full overflow-hidden rounded bg-surface-border/60">
      <div className={`h-full ${healthBar(score)}`} style={{ width: `${pctWidth}%` }} />
    </div>
  );
}

export default function Trades() {
  const [status, setStatus] = useState<"open" | "closed">("open");
  const [selected, setSelected] = useState<string | null>(null);

  const trades = useApi<TrackedTrade[]>(`/trade-lifecycle?status=${status}`);
  const analytics = useApi<ManagementAnalytics>("/trade-lifecycle/management-analytics");

  const rows = trades.data ?? [];
  const active = rows.find((t) => t.trade_uid === selected) ?? null;

  return (
    <div className="space-y-5 p-5">
      <PageTitle
        title="Trades — Portfolio Command Center"
        subtitle="Every recommendation tracked; health is the trade's battery percentage"
      >
        <div className="flex items-center gap-2">
          <div className="flex rounded border border-surface-border text-xs">
            {(["open", "closed"] as const).map((s) => (
              <button
                key={s}
                onClick={() => {
                  setStatus(s);
                  setSelected(null);
                }}
                className={`px-2.5 py-1 capitalize ${status === s ? "bg-surface text-slate-100" : "text-slate-400 hover:text-slate-200"}`}
              >
                {s}
              </button>
            ))}
          </div>
          <ActionButton
            label="Reevaluate now"
            path="/actions/reevaluate-trades"
            onDone={() => {
              trades.reload();
              analytics.reload();
            }}
          />
        </div>
      </PageTitle>

      {trades.loading ? (
        <Loading />
      ) : trades.error ? (
        <ErrorBox message={trades.error} />
      ) : rows.length === 0 ? (
        <Card title={`${status === "open" ? "Open" : "Closed"} trades`}>
          <div className="py-8 text-center text-sm text-slate-500">
            No {status} tracked trades yet — run a scan to turn recommendations into tracked
            trades.
          </div>
        </Card>
      ) : (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
          {rows.map((t) => (
            <button
              key={t.trade_uid}
              onClick={() => setSelected(selected === t.trade_uid ? null : t.trade_uid)}
              className={`space-y-1.5 rounded-lg border p-3 text-left ${
                selected === t.trade_uid
                  ? "border-accent ring-1 ring-accent/40"
                  : "border-surface-border hover:bg-surface/50"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-100">{t.symbol}</span>
                <ActionBadge
                  action={t.status === "closed" ? (t.close_reason ? "Exit" : null) : latestAction(t)}
                />
              </div>
              <div className={`text-2xl font-bold tabular-nums ${healthColor(t.current_health_score)}`}>
                {t.current_health_score != null ? num(t.current_health_score, 0) : "—"}
              </div>
              <Battery score={t.current_health_score} />
              <div className="text-[11px] text-slate-500">
                {t.status === "closed" && t.realized_r != null
                  ? `realized ${signed(t.realized_r, 2)}R`
                  : `since ${date(t.recommended_at)}`}
              </div>
            </button>
          ))}
        </div>
      )}

      {active ? <TradeDetail trade={active} /> : null}

      <ManagementPanel state={analytics} />
    </div>
  );
}

/* The card list shows current health; the freshest action lives on the trade's
   last evaluation, which the detail view loads. Cards fall back to health band. */
function latestAction(t: TrackedTrade): string | null {
  return t.trade_health === "Broken"
    ? "Exit"
    : t.trade_health === "Weakening"
      ? "Scale Out"
      : t.trade_health === "Strong"
        ? "Add?"
        : "Hold";
}

/* --------------------------------------------------------------------- */
/* Detail: thesis + time machine + health breakdown + explanation + journal */
/* --------------------------------------------------------------------- */
function TradeDetail({ trade }: { trade: TrackedTrade }) {
  const evals = useApi<TradeEvaluation[]>(`/trade-lifecycle/${trade.trade_uid}/evaluations`);
  const journal = useApi<JournalEntry[]>(`/trade-lifecycle/${trade.trade_uid}/journal`);

  // API returns newest-first; the time machine slides oldest → newest.
  const timeline = useMemo(() => [...(evals.data ?? [])].reverse(), [evals.data]);
  const [idx, setIdx] = useState<number | null>(null);
  const cursor = idx ?? Math.max(0, timeline.length - 1);
  const current = timeline[cursor];

  return (
    <div className="space-y-4">
      <Card title={`${trade.symbol} — thesis`}>
        <div className="grid gap-4 md:grid-cols-[2fr,3fr]">
          <div className="space-y-2 text-sm">
            <p className="text-slate-300">{trade.thesis ?? "No thesis text recorded."}</p>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-400">
              <span>Entry {num(trade.entry_price)}</span>
              <span>Stop {num(trade.stop_price)}</span>
              <span>
                Conviction{" "}
                {trade.conviction_score != null ? num(trade.conviction_score, 0) : "—"}
                {trade.conviction_band ? ` (${trade.conviction_band})` : ""}
              </span>
              <span>Regime {trade.regime ?? "—"}</span>
              <span>Sector {trade.sector ?? "—"}</span>
              <span>Opened {date(trade.recommended_at)}</span>
              {trade.status === "closed" ? (
                <>
                  <span>Closed {date(trade.closed_at)}</span>
                  <span>
                    {trade.realized_r != null ? `Realized ${signed(trade.realized_r, 2)}R` : ""}
                  </span>
                </>
              ) : null}
            </div>
            {trade.close_reason ? (
              <p className="text-xs text-slate-500">Close reason: {trade.close_reason}</p>
            ) : null}
          </div>

          {/* Time machine */}
          <div className="space-y-2">
            {evals.loading ? (
              <Loading />
            ) : evals.error ? (
              <ErrorBox message={evals.error} />
            ) : timeline.length === 0 ? (
              <div className="text-sm text-slate-500">No evaluations yet.</div>
            ) : (
              <>
                <div className="flex items-center justify-between text-xs text-slate-400">
                  <span>Time machine — {date(current?.evaluated_at ?? null)}</span>
                  <span>
                    {cursor + 1} / {timeline.length}
                  </span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={Math.max(0, timeline.length - 1)}
                  value={cursor}
                  onChange={(e) => setIdx(Number(e.target.value))}
                  className="w-full accent-indigo-400"
                />
                <div className="flex items-end gap-4">
                  <div>
                    <div
                      className={`text-4xl font-bold tabular-nums ${healthColor(current?.health_score ?? null)}`}
                    >
                      {current?.health_score != null ? num(current.health_score, 0) : "—"}
                    </div>
                    <div className="text-[11px] uppercase tracking-wide text-slate-500">
                      Trade health
                    </div>
                  </div>
                  <div className="pb-1">
                    <ActionBadge action={current?.action ?? null} />
                  </div>
                  <div className="flex-1 pb-1">
                    {/* Health history strip: every evaluation as a bar */}
                    <div className="flex h-10 items-end gap-0.5">
                      {timeline.map((ev, i) => {
                        const score = ev.health_score ?? ev.thesis_strength;
                        return (
                          <button
                            key={i}
                            onClick={() => setIdx(i)}
                            title={`${date(ev.evaluated_at)} · ${num(score, 0)}`}
                            className={`${healthBar(score)} ${i === cursor ? "opacity-100" : "opacity-40"} w-full rounded-t`}
                            style={{ height: `${Math.max(6, score)}%` }}
                          />
                        );
                      })}
                    </div>
                  </div>
                </div>
                {current?.reasons?.length ? (
                  <p className="text-xs text-slate-400">{current.reasons.join("; ")}</p>
                ) : null}
              </>
            )}
          </div>
        </div>
      </Card>

      {current ? <ExplanationPanel evaluation={current} /> : null}

      <Card title="Thesis journal — the trade's story (append-only)">
        {journal.loading ? (
          <Loading />
        ) : journal.error ? (
          <ErrorBox message={journal.error} />
        ) : (
          <ol className="space-y-0">
            {(journal.data ?? []).map((entry, i) => (
              <li
                key={i}
                className="grid grid-cols-[6.5rem,10rem,1fr] gap-2 border-b border-surface-border/40 py-1.5 text-sm last:border-0"
              >
                <span className="text-slate-500">{date(entry.at)}</span>
                <span className="flex items-center gap-2 font-medium text-slate-200">
                  {entry.label}
                  {entry.health_score != null ? (
                    <span className={`text-xs tabular-nums ${healthColor(entry.health_score)}`}>
                      {num(entry.health_score, 0)}
                    </span>
                  ) : null}
                </span>
                <span className="truncate text-xs text-slate-400" title={entry.detail ?? ""}>
                  {entry.detail ?? "—"}
                </span>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}

function ExplanationPanel({ evaluation }: { evaluation: TradeEvaluation }) {
  const explanation = evaluation.explanation;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Health breakdown — every point explained">
        {evaluation.health_breakdown?.length ? (
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wide text-slate-500">
              <tr className="border-b border-surface-border text-left">
                <th className="px-1.5 py-1 font-medium">Component</th>
                <th className="px-1.5 py-1 text-right font-medium">Points</th>
                <th className="px-1.5 py-1 text-right font-medium">±</th>
                <th className="px-1.5 py-1 font-medium">Why</th>
              </tr>
            </thead>
            <tbody>
              {evaluation.health_breakdown.map((c) => (
                <tr key={c.name} className="border-b border-surface-border/40 last:border-0">
                  <td className="px-1.5 py-1 capitalize text-slate-300">
                    {c.name.replace(/_/g, " ")}
                  </td>
                  <td className="px-1.5 py-1 text-right tabular-nums text-slate-300">
                    {num(c.earned, 1)}/{num(c.available, 0)}
                  </td>
                  <td
                    className={`px-1.5 py-1 text-right tabular-nums ${c.delta >= 0 ? "text-emerald-400" : "text-bear"}`}
                  >
                    {signed(c.delta, 1)}
                  </td>
                  <td className="px-1.5 py-1 text-slate-400">{c.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="py-4 text-center text-xs text-slate-500">
            No health breakdown for this evaluation (pre-health history).
          </div>
        )}
      </Card>

      <Card title="Explanation — what changed & why">
        {explanation ? (
          <div className="space-y-2 text-xs">
            <div>
              <div className="mb-0.5 text-[10px] uppercase tracking-wide text-slate-500">
                What changed
              </div>
              <ul className="list-inside list-disc text-slate-300">
                {explanation.what_changed.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </div>
            <div>
              <div className="mb-0.5 text-[10px] uppercase tracking-wide text-slate-500">
                Confidence {explanation.confidence.direction}
              </div>
              <p className="text-slate-400">{explanation.confidence.reason}</p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="mb-0.5 text-[10px] uppercase tracking-wide text-emerald-400">
                  Evidence for
                </div>
                <ul className="space-y-0.5 text-slate-400">
                  {explanation.supporting.length ? (
                    explanation.supporting.map((s, i) => <li key={i}>{s}</li>)
                  ) : (
                    <li className="text-slate-600">none above neutral</li>
                  )}
                </ul>
              </div>
              <div>
                <div className="mb-0.5 text-[10px] uppercase tracking-wide text-bear">
                  Evidence against
                </div>
                <ul className="space-y-0.5 text-slate-400">
                  {explanation.contradicting.length ? (
                    explanation.contradicting.map((s, i) => <li key={i}>{s}</li>)
                  ) : (
                    <li className="text-slate-600">none below neutral</li>
                  )}
                </ul>
              </div>
            </div>
          </div>
        ) : (
          <div className="py-4 text-center text-xs text-slate-500">
            No stored explanation for this evaluation (pre-explainability history).
          </div>
        )}
      </Card>
    </div>
  );
}

/* --------------------------------------------------------------------- */
/* Phase 8 — management analytics (grades the management logic itself)     */
/* --------------------------------------------------------------------- */
function ManagementPanel({
  state,
}: {
  state: { data: ManagementAnalytics | null; loading: boolean; error: string | null };
}) {
  const a = state.data;
  return (
    <Card title="Management analytics — is the management logic improving?">
      {state.loading ? (
        <Loading />
      ) : state.error ? (
        <ErrorBox message={state.error} />
      ) : !a || a.trades_tracked === 0 ? (
        <div className="py-6 text-center text-sm text-slate-500">
          No tracked trades yet — analytics appear after the first scan.
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Stat
              label="Avg conviction decay"
              value={a.avg_conviction_decay != null ? signed(a.avg_conviction_decay, 1) : "—"}
              hint="last vs entry conviction"
            />
            <Stat
              label="Avg trade health"
              value={a.avg_trade_health != null ? num(a.avg_trade_health, 0) : "—"}
              hint="across all evaluations"
            />
            <Stat
              label="Avg holding period"
              value={
                a.avg_holding_period_days != null ? `${num(a.avg_holding_period_days, 1)}d` : "—"
              }
              hint="closed trades"
            />
            <Stat
              label="Max thesis age"
              value={a.max_thesis_age_days != null ? `${num(a.max_thesis_age_days, 0)}d` : "—"}
            />
            <Stat
              label="Best health decile"
              value={a.most_successful_health ? a.most_successful_health.bucket : "—"}
              hint={
                a.most_successful_health
                  ? `${signed(a.most_successful_health.avg_realized_r, 2)}R over ${a.most_successful_health.trades} trades`
                  : "needs realized outcomes"
              }
            />
            <Stat
              label="Avg conviction recovery"
              value={
                a.avg_conviction_recovery != null ? signed(a.avg_conviction_recovery, 1) : "—"
              }
              hint="rebound after dips"
            />
            <Stat
              label="Avg stop raises"
              value={a.avg_stop_raises != null ? num(a.avg_stop_raises, 2) : "—"}
              hint="per trade"
            />
            <Stat
              label="Avg stop lowers"
              value={a.avg_stop_lowers != null ? num(a.avg_stop_lowers, 2) : "—"}
              hint="per trade"
            />
            <Stat
              label="Avg health before exit"
              value={a.avg_health_before_exit != null ? num(a.avg_health_before_exit, 0) : "—"}
              hint="final evaluation of closed trades"
            />
            <Stat label="Trades tracked" value={a.trades_tracked} />
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <ExitList title="Best exits (loss avoided)" grades={a.best_exits} />
            <ExitList title="Worst exits (upside left behind)" grades={a.worst_exits} />
          </div>
        </div>
      )}
    </Card>
  );
}

function ExitList({ title, grades }: { title: string; grades: ManagementAnalytics["best_exits"] }) {
  return (
    <div>
      <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">{title}</div>
      {grades.length === 0 ? (
        <div className="text-xs text-slate-600">No realized Exit advice yet.</div>
      ) : (
        <ul className="space-y-1 text-xs">
          {grades.map((g, i) => (
            <li key={i} className="flex items-center justify-between text-slate-300">
              <span>
                {g.symbol} · {date(g.evaluated_at)}
              </span>
              <span className={`tabular-nums ${g.remaining_r < 0 ? "text-emerald-400" : "text-bear"}`}>
                {signed(-g.remaining_r, 2)}R {g.remaining_r < 0 ? "saved" : "missed"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
